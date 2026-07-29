import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.migration import migrate_database
from clinical_data_platform.synthea import (
    SyntheaAdapterError,
    SyntheaManifestError,
    adapt_synthea_csv,
    build_synthea_command,
    load_adapted_synthea_dataset,
    load_synthea_profile,
    synthea_profile_document,
    verify_synthea_adaptation,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "tests" / "fixtures" / "synthea" / "csv"


def test_packaged_synthea_profile_pins_every_reproducibility_control() -> None:
    profile = load_synthea_profile()
    document = synthea_profile_document(profile)

    assert profile.name == "synthea-us-small-v1"
    assert profile.upstream_ref == "v4.0.0"
    assert profile.upstream_version == "4.0.0"
    assert profile.population_size == 100
    assert profile.random_seed == 20260729
    assert profile.clinician_seed == 20260730
    assert profile.reference_date.isoformat() == "2026-07-29"
    assert profile.thread_pool_size == 1
    assert profile.years_of_history == 0
    assert len(profile.sha256) == 64
    assert document["sha256"] == profile.sha256


def test_synthea_command_is_shell_free_and_deterministically_configured(tmp_path: Path) -> None:
    profile = load_synthea_profile()
    checkout = tmp_path / "synthea"
    output = tmp_path / "output"

    command = build_synthea_command(profile, checkout, output, windows=False)

    assert command[0] == str(checkout / "run_synthea")
    assert command[1:9] == (
        "-s",
        "20260729",
        "-cs",
        "20260730",
        "-p",
        "100",
        "-r",
        "20260729",
    )
    assert "--exporter.csv.export=true" in command
    assert "--exporter.csv.append_mode=false" in command
    assert "--exporter.csv.folder_per_run=false" in command
    assert "--exporter.fhir.export=false" in command
    assert "--exporter.years_of_history=0" in command
    assert "--generate.thread_pool_size=1" in command
    assert command[-1] == "Massachusetts"


def test_synthea_adapter_is_deterministic_and_contract_ready(tmp_path: Path) -> None:
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"

    first = adapt_synthea_csv(FIXTURE_DIRECTORY, first_directory)
    second = adapt_synthea_csv(FIXTURE_DIRECTORY, second_directory)

    assert first.adaptation_fingerprint == second.adaptation_fingerprint
    assert first.dataset_rows == {
        "patients": 2,
        "encounters": 2,
        "diagnoses": 2,
        "observations": 3,
        "medications": 2,
        "procedures": 1,
    }
    assert first.omitted_rows == {"observation_outside_supported_subset": 1}
    assert first.terminology_concepts == 5

    for filename in (
        "patients.csv",
        "encounters.csv",
        "diagnoses.csv",
        "observations.csv",
        "medications.csv",
        "procedures.csv",
        "terminology.csv",
    ):
        assert (first_directory / filename).read_bytes() == (
            second_directory / filename
        ).read_bytes()

    verified = verify_synthea_adaptation(first_directory)
    assert verified.adaptation_fingerprint == first.adaptation_fingerprint

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["adapter_version"] == "1.0.0"
    assert manifest["dataset_rows"] == first.dataset_rows


def test_synthea_adaptation_detects_output_tampering(tmp_path: Path) -> None:
    output_directory = tmp_path / "adapted"
    adapt_synthea_csv(FIXTURE_DIRECTORY, output_directory)
    patients_path = output_directory / "patients.csv"
    patients_path.write_text(
        patients_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SyntheaManifestError, match="hash mismatch"):
        verify_synthea_adaptation(output_directory)


def test_synthea_adapter_rejects_upstream_schema_drift(tmp_path: Path) -> None:
    copied = tmp_path / "csv"
    copied.mkdir()
    for source in FIXTURE_DIRECTORY.iterdir():
        (copied / source.name).write_bytes(source.read_bytes())
    patient_path = copied / "patients.csv"
    patient_path.write_text(
        patient_path.read_text(encoding="utf-8").replace("BIRTHDATE", "DATE_OF_BIRTH", 1),
        encoding="utf-8",
    )

    with pytest.raises(SyntheaAdapterError, match="Unexpected header"):
        adapt_synthea_csv(copied, tmp_path / "adapted")


@pytest.mark.integration
def test_adapted_synthea_population_loads_through_all_existing_controls(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    normalized = tmp_path / "normalized"
    adapt_synthea_csv(FIXTURE_DIRECTORY, normalized)

    connection = clean_database_connection
    migrate_database(connection)
    loaded = load_adapted_synthea_dataset(
        connection,
        normalized,
        tmp_path / "processed",
        raw_root=tmp_path / "raw",
    )

    assert loaded.terminology.concepts_received == 5
    assert loaded.terminology.concepts_inserted == 2
    assert loaded.terminology.concepts_existing == 3
    assert loaded.records_persisted == {
        "patients": 2,
        "encounters": 2,
        "diagnoses": 2,
        "observations": 3,
        "medications": 2,
        "procedures": 1,
    }
    assert set(loaded.run_ids) == set(loaded.records_persisted)

    counts = connection.execute(
        """
        SELECT 'patients', COUNT(*) FROM clinical.patients
        UNION ALL SELECT 'encounters', COUNT(*) FROM clinical.encounters
        UNION ALL SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
        UNION ALL SELECT 'observations', COUNT(*) FROM clinical.observations
        UNION ALL SELECT 'medications', COUNT(*) FROM clinical.medications
        UNION ALL SELECT 'procedures', COUNT(*) FROM clinical.procedures
        ORDER BY 1
        """
    ).fetchall()
    assert counts == [
        ("diagnoses", 2),
        ("encounters", 2),
        ("medications", 2),
        ("observations", 3),
        ("patients", 2),
        ("procedures", 1),
    ]

    unverified = connection.execute(
        """
        SELECT code_system_id, code, domain
        FROM terminology.concepts
        WHERE source_reference LIKE 'Synthea 4.0.0 CSV export%'
        ORDER BY code_system_id, code
        """
    ).fetchall()
    assert unverified == [
        ("SNOMEDCT", "38341003", "condition"),
        ("SNOMEDCT", "44054006", "condition"),
    ]
