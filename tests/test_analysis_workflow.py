import csv
import os
from datetime import date
from pathlib import Path

import pytest

from clinical_data_platform.cohort import build_hypertension_cohort
from clinical_data_platform.database import (
    apply_schema,
    connect_database,
    persist_patient_validation_outputs,
)
from clinical_data_platform.entity_database import persist_entity_validation_outputs
from clinical_data_platform.entity_pipeline import run_entity_validation
from clinical_data_platform.pipeline import run_patient_validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"
SCHEMA_PATH = REPOSITORY_ROOT / "sql" / "schema.sql"
COHORT_SQL_PATH = REPOSITORY_ROOT / "sql" / "cohorts" / "hypertension.sql"
DATABASE_URL = os.getenv("DATABASE_URL")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is not configured")
def test_full_clinical_pipeline_builds_expected_hypertension_features(
    tmp_path: Path,
) -> None:
    assert DATABASE_URL is not None
    processed = tmp_path / "processed"
    patient_summary = run_patient_validation(
        SAMPLE_DIRECTORY / "patients.csv",
        processed / "patients",
        reference_date=date(2026, 7, 29),
    )
    for dataset in ("encounters", "diagnoses", "observations"):
        run_entity_validation(
            dataset,
            SAMPLE_DIRECTORY / f"{dataset}.csv",
            processed / dataset,
            reference_date=date(2026, 7, 29),
        )

    with connect_database(DATABASE_URL) as connection:
        apply_schema(connection, SCHEMA_PATH)
        connection.execute(
            """
            TRUNCATE TABLE
                analytics.hypertension_features,
                audit.cohort_source_runs,
                audit.cohort_runs,
                clinical.observations,
                clinical.diagnoses,
                clinical.encounters,
                clinical.patients,
                audit.validation_errors,
                audit.pipeline_runs
            RESTART IDENTITY CASCADE
            """
        )
        connection.commit()

        patient_load = persist_patient_validation_outputs(
            connection,
            processed / "patients",
        )
        encounter_load = persist_entity_validation_outputs(
            connection,
            "encounters",
            processed / "encounters",
        )
        diagnosis_load = persist_entity_validation_outputs(
            connection,
            "diagnoses",
            processed / "diagnoses",
        )
        observation_load = persist_entity_validation_outputs(
            connection,
            "observations",
            processed / "observations",
        )
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

    assert patient_load.run_id == patient_summary.run_id
    assert patient_load.patients_upserted == 5
    assert encounter_load.records_upserted == 7
    assert diagnosis_load.records_upserted == 6
    assert observation_load.records_upserted == 13
    assert cohort.row_count == 2
    assert feature_rows == [
        ("P001", 146.0, 92.0, 95),
        ("P002", 151.0, 96.0, 37),
    ]

    with cohort.features_path.open(encoding="utf-8", newline="") as file:
        exported = list(csv.DictReader(file))
    assert [row["patient_id"] for row in exported] == ["P001", "P002"]
