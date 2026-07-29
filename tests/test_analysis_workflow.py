import csv
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.cohort import build_hypertension_cohort
from clinical_data_platform.database import persist_dataset_validation_outputs
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.registry import dataset_names

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"
COHORT_SQL_PATH = REPOSITORY_ROOT / "sql" / "cohorts" / "hypertension.sql"


@pytest.mark.integration
def test_full_clinical_pipeline_builds_expected_hypertension_features(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    processed = tmp_path / "processed"
    summaries = {
        dataset: run_dataset_validation(
            dataset,
            SAMPLE_DIRECTORY / f"{dataset}.csv",
            processed / dataset,
            reference_date=date(2026, 7, 29),
        )
        for dataset in dataset_names()
    }

    connection = clean_database_connection
    migrate_database(connection)
    loads = {
        dataset: persist_dataset_validation_outputs(
            connection,
            dataset,
            processed / dataset,
        )
        for dataset in dataset_names()
    }
    cohort = build_hypertension_cohort(
        connection,
        COHORT_SQL_PATH,
        tmp_path / "analytics",
    )

    feature_rows = connection.execute(
        """
        SELECT
            patient_id,
            baseline_systolic_bp,
            baseline_diastolic_bp,
            follow_up_days
        FROM analytics.hypertension_features
        WHERE cohort_run_id = %s
        ORDER BY patient_id
        """,
        (cohort.cohort_run_id,),
    ).fetchall()

    assert loads["patients"].run_id == summaries["patients"].run_id
    assert loads["patients"].records_upserted == 5
    assert loads["encounters"].records_upserted == 7
    assert loads["diagnoses"].records_upserted == 6
    assert loads["observations"].records_upserted == 13
    assert cohort.row_count == 2
    assert feature_rows == [
        ("P001", 146.0, 92.0, 95),
        ("P002", 151.0, 96.0, 37),
    ]

    with cohort.features_path.open(encoding="utf-8", newline="") as file:
        exported = list(csv.DictReader(file))
    assert [row["patient_id"] for row in exported] == ["P001", "P002"]
