import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.cohort_cli import build_parser
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.synthea import adapt_synthea_csv
from clinical_data_platform.synthea_cohorts import (
    DEFAULT_COHORT_A_PROFILE,
    DEFAULT_COHORT_B_PROFILE,
    SyntheaCohortError,
    compare_synthea_cohorts,
    load_packaged_synthea_profile,
    load_synthea_cohort_pair,
    packaged_synthea_profile_names,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_A = REPOSITORY_ROOT / "tests" / "fixtures" / "synthea" / "csv"
FIXTURE_B = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "synthea" / "cohort_b" / "csv"
)


def _adapt_pair(tmp_path: Path) -> tuple[Path, Path]:
    cohort_a_directory = tmp_path / "cohort_a"
    cohort_b_directory = tmp_path / "cohort_b"
    adapt_synthea_csv(
        FIXTURE_A,
        cohort_a_directory,
        profile=load_packaged_synthea_profile(DEFAULT_COHORT_A_PROFILE),
    )
    adapt_synthea_csv(
        FIXTURE_B,
        cohort_b_directory,
        profile=load_packaged_synthea_profile(DEFAULT_COHORT_B_PROFILE),
    )
    return cohort_a_directory, cohort_b_directory


def test_packaged_profiles_define_matched_design_independent_cohorts() -> None:
    assert packaged_synthea_profile_names() == (
        DEFAULT_COHORT_A_PROFILE,
        DEFAULT_COHORT_B_PROFILE,
    )
    cohort_a = load_packaged_synthea_profile(DEFAULT_COHORT_A_PROFILE)
    cohort_b = load_packaged_synthea_profile(DEFAULT_COHORT_B_PROFILE)

    assert cohort_a.sha256 != cohort_b.sha256
    assert cohort_a.random_seed != cohort_b.random_seed
    assert cohort_a.clinician_seed != cohort_b.clinician_seed
    assert cohort_b.random_seed == 20260829
    assert cohort_b.clinician_seed == 20260830
    assert cohort_a.population_size == cohort_b.population_size == 100
    assert cohort_a.reference_date == cohort_b.reference_date
    assert cohort_a.state == cohort_b.state == "Massachusetts"
    assert cohort_a.upstream_ref == cohort_b.upstream_ref == "v4.0.0"
    assert cohort_a.thread_pool_size == cohort_b.thread_pool_size == 1
    assert cohort_a.years_of_history == cohort_b.years_of_history == 0
    assert cohort_a.included_files == cohort_b.included_files


def test_cohort_cli_exposes_profile_and_pair_controls() -> None:
    parser = build_parser()
    profile_args = parser.parse_args(["profile", DEFAULT_COHORT_B_PROFILE])
    compare_args = parser.parse_args(
        [
            "compare",
            "a",
            "b",
            "--cohort-a-profile",
            DEFAULT_COHORT_A_PROFILE,
            "--cohort-b-profile",
            DEFAULT_COHORT_B_PROFILE,
            "--cohort-a-label",
            "replica_1",
            "--cohort-b-label",
            "replica_2",
        ]
    )

    assert profile_args.profile_name == DEFAULT_COHORT_B_PROFILE
    assert compare_args.cohort_a_profile == DEFAULT_COHORT_A_PROFILE
    assert compare_args.cohort_b_profile == DEFAULT_COHORT_B_PROFILE
    assert compare_args.cohort_a_label == "replica_1"
    assert compare_args.cohort_b_label == "replica_2"


def test_cohort_comparison_is_deterministic_and_identifier_disjoint(
    tmp_path: Path,
) -> None:
    cohort_a_directory, cohort_b_directory = _adapt_pair(tmp_path)

    first = compare_synthea_cohorts(
        cohort_a_directory,
        cohort_b_directory,
        tmp_path / "comparison_1",
    )
    second = compare_synthea_cohorts(
        cohort_a_directory,
        cohort_b_directory,
        tmp_path / "comparison_2",
    )

    assert first.comparison_fingerprint == second.comparison_fingerprint
    assert first.cohort_a.adaptation_fingerprint != first.cohort_b.adaptation_fingerprint
    assert first.overlap_counts == {
        "patients": 0,
        "encounters": 0,
        "diagnoses": 0,
        "observations": 0,
        "medications": 0,
        "procedures": 0,
    }
    assert first.cohort_a.dataset_rows == first.cohort_b.dataset_rows == {
        "patients": 2,
        "encounters": 2,
        "diagnoses": 2,
        "observations": 3,
        "medications": 2,
        "procedures": 1,
    }
    assert first.manifest_path.exists()
    assert first.markdown_path.exists()

    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["comparison_fingerprint"] == first.comparison_fingerprint
    assert manifest["identifier_overlap_counts"] == first.overlap_counts
    assert [cohort["profile_name"] for cohort in manifest["cohorts"]] == [
        DEFAULT_COHORT_A_PROFILE,
        DEFAULT_COHORT_B_PROFILE,
    ]


def test_cohort_comparison_rejects_overlapping_clinical_identifiers(
    tmp_path: Path,
) -> None:
    cohort_a_directory = tmp_path / "cohort_a"
    overlapping_directory = tmp_path / "overlapping"
    adapt_synthea_csv(
        FIXTURE_A,
        cohort_a_directory,
        profile=load_packaged_synthea_profile(DEFAULT_COHORT_A_PROFILE),
    )
    adapt_synthea_csv(
        FIXTURE_A,
        overlapping_directory,
        profile=load_packaged_synthea_profile(DEFAULT_COHORT_B_PROFILE),
    )

    with pytest.raises(SyntheaCohortError, match="identifiers overlap"):
        compare_synthea_cohorts(
            cohort_a_directory,
            overlapping_directory,
            tmp_path / "comparison",
        )


@pytest.mark.integration
def test_disjoint_cohort_pair_loads_with_separate_run_lineage(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    cohort_a_directory, cohort_b_directory = _adapt_pair(tmp_path)
    connection = clean_database_connection
    migrate_database(connection)

    loaded = load_synthea_cohort_pair(
        connection,
        cohort_a_directory,
        cohort_b_directory,
        tmp_path / "processed",
        tmp_path / "comparison",
        raw_root=tmp_path / "raw",
    )

    assert set(loaded.cohort_a_load.run_ids) == set(loaded.cohort_b_load.run_ids)
    assert set(loaded.cohort_a_load.run_ids.values()).isdisjoint(
        loaded.cohort_b_load.run_ids.values()
    )
    assert loaded.cohort_a_load.records_persisted == {
        "patients": 2,
        "encounters": 2,
        "diagnoses": 2,
        "observations": 3,
        "medications": 2,
        "procedures": 1,
    }
    assert loaded.cohort_b_load.records_persisted == loaded.cohort_a_load.records_persisted
    assert loaded.load_manifest_path.exists()
    assert len(loaded.load_execution_fingerprint) == 64

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
        ("diagnoses", 4),
        ("encounters", 4),
        ("medications", 4),
        ("observations", 6),
        ("patients", 4),
        ("procedures", 2),
    ]
    assert connection.execute(
        "SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'completed'"
    ).fetchone() == (12,)

    with pytest.raises(SyntheaCohortError, match="already contains patients identifiers"):
        load_synthea_cohort_pair(
            connection,
            cohort_a_directory,
            cohort_b_directory,
            tmp_path / "processed_again",
            tmp_path / "comparison_again",
            raw_root=tmp_path / "raw_again",
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'completed'"
    ).fetchone() == (12,)
