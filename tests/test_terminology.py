import csv
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.database import persist_dataset_validation_outputs
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.registry import dataset_names
from clinical_data_platform.terminology import (
    list_terminology_systems,
    resolve_terminology_concept,
    validate_terminology_bindings,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"
REFERENCE_DATE = date(2026, 7, 29)


def _validate_and_load(
    connection: psycopg.Connection[Any],
    tmp_path: Path,
    dataset: str,
    source_path: Path,
    run_name: str,
):
    output_directory = tmp_path / "processed" / run_name
    raw_root = tmp_path / "raw"
    validation = run_dataset_validation(
        dataset,
        source_path,
        output_directory,
        raw_root=raw_root,
        reference_date=REFERENCE_DATE,
    )
    persistence = persist_dataset_validation_outputs(
        connection,
        dataset,
        output_directory,
        raw_root=raw_root,
    )
    return validation, persistence


def _replace_csv_value(
    source_path: Path,
    target_path: Path,
    *,
    identity_column: str,
    identity_value: str,
    field: str,
    value: str,
) -> None:
    with source_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise AssertionError("Fixture must have a CSV header.")
        rows = list(reader)
        fieldnames = reader.fieldnames

    for row in rows:
        if row[identity_column] == identity_value:
            row[field] = value
            break
    else:
        raise AssertionError(f"Fixture identity not found: {identity_value}")

    with target_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.integration
def test_minimal_terminology_registry_resolves_aliases_and_local_mappings(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)

    systems = list_terminology_systems(connection)
    local_systolic = resolve_terminology_concept(
        connection,
        "LOCAL_OBSERVATION",
        "SYSTOLIC_BP",
        "observation",
    )
    hypertension = resolve_terminology_concept(
        connection,
        "ICD10",
        "I10",
        "condition",
    )

    assert len(systems) == 8
    assert {system.code_system_id for system in systems} == {
        "ATC",
        "CPT",
        "ICD10CM",
        "ICD10PCS",
        "LOCAL_OBSERVATION",
        "LOINC",
        "RXNORM",
        "SNOMEDCT",
    }
    assert all(system.subset_version for system in systems)
    assert sum(system.complete_release for system in systems) == 1

    assert local_systolic.code_system_id == "LOINC"
    assert local_systolic.code == "8480-6"
    assert local_systolic.display == "Systolic blood pressure"
    assert local_systolic.verification_status == "verified"

    assert hypertension.code_system_id == "ICD10CM"
    assert hypertension.code == "I10"
    assert hypertension.domain == "condition"


@pytest.mark.integration
def test_six_entity_demo_rows_are_bound_to_active_normalized_concepts(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)

    for dataset in dataset_names():
        _validate_and_load(
            connection,
            tmp_path,
            dataset,
            SAMPLE_DIRECTORY / f"{dataset}.csv",
            dataset,
        )

    summary = validate_terminology_bindings(connection)
    systolic_binding = connection.execute(
        """
        SELECT
            source_system,
            source_code,
            normalized_system,
            normalized_code,
            normalized_display,
            verification_status
        FROM terminology.normalized_clinical_codes
        WHERE dataset_name = 'observations'
          AND entity_id = 'O001'
        """
    ).fetchone()
    medication_binding = connection.execute(
        """
        SELECT normalized_system, normalized_code, normalized_display
        FROM terminology.normalized_clinical_codes
        WHERE dataset_name = 'medications'
          AND entity_id = 'M001'
        """
    ).fetchone()

    assert summary.code_systems == 8
    assert summary.concepts == 22
    assert summary.mappings == 3
    assert summary.normalized_clinical_rows == 31
    assert summary.invalid_bindings == 0
    assert systolic_binding == (
        "LOCAL_OBSERVATION",
        "SYSTOLIC_BP",
        "LOINC",
        "8480-6",
        "Systolic blood pressure",
        "verified",
    )
    assert medication_binding == (
        "RXNORM",
        "197361",
        "amlodipine 5 MG Oral Tablet",
    )


@pytest.mark.integration
def test_unknown_code_is_rejected_and_the_dataset_transaction_rolls_back(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)

    for dataset in ("patients", "encounters"):
        _validate_and_load(
            connection,
            tmp_path,
            dataset,
            SAMPLE_DIRECTORY / f"{dataset}.csv",
            dataset,
        )

    unknown_source = tmp_path / "diagnoses-unknown-code.csv"
    _replace_csv_value(
        SAMPLE_DIRECTORY / "diagnoses.csv",
        unknown_source,
        identity_column="diagnosis_id",
        identity_value="D001",
        field="diagnosis_code",
        value="ZZZ.999",
    )
    output_directory = tmp_path / "processed" / "diagnoses-unknown-code"
    raw_root = tmp_path / "raw"
    validation = run_dataset_validation(
        "diagnoses",
        unknown_source,
        output_directory,
        raw_root=raw_root,
        reference_date=REFERENCE_DATE,
    )

    assert validation.rows_valid == 6
    assert validation.rows_invalid == 1

    with pytest.raises(psycopg.IntegrityError, match="Unknown terminology concept"):
        persist_dataset_validation_outputs(
            connection,
            "diagnoses",
            output_directory,
            raw_root=raw_root,
        )

    diagnosis_count = connection.execute(
        "SELECT COUNT(*) FROM clinical.diagnoses"
    ).fetchone()
    failed_run = connection.execute(
        "SELECT COUNT(*) FROM audit.pipeline_runs WHERE run_id = %s",
        (validation.run_id,),
    ).fetchone()

    assert diagnosis_count == (0,)
    assert failed_run == (0,)
