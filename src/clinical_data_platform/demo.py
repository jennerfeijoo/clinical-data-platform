"""End-to-end demonstration workflow for the synthetic clinical dataset."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID

from clinical_data_platform.cohort import CohortSummary, build_hypertension_cohort
from clinical_data_platform.database import (
    apply_schema,
    connect_database,
    persist_patient_validation_outputs,
)
from clinical_data_platform.entity_database import persist_entity_validation_outputs
from clinical_data_platform.entity_pipeline import run_entity_validation
from clinical_data_platform.pipeline import run_patient_validation


@dataclass(frozen=True, slots=True)
class DemoSummary:
    """Key identifiers and counts produced by the demonstration workflow."""

    patient_run_id: UUID
    encounter_run_id: UUID
    diagnosis_run_id: UUID
    observation_run_id: UUID
    cohort: CohortSummary


def run_demo(
    repository_root: Path,
    database_url: str,
    *,
    reference_date: date = date(2026, 7, 29),
) -> DemoSummary:
    """Validate, persist, and analyze all bundled synthetic datasets."""
    sample_directory = repository_root / "data" / "sample"
    processed_directory = repository_root / "data" / "processed"
    analytics_directory = repository_root / "data" / "analytics"
    schema_path = repository_root / "sql" / "schema.sql"
    cohort_sql_path = repository_root / "sql" / "cohorts" / "hypertension.sql"

    patient_summary = run_patient_validation(
        sample_directory / "patients.csv",
        processed_directory / "patients",
        reference_date=reference_date,
    )
    entity_summaries = {
        dataset: run_entity_validation(
            dataset,
            sample_directory / f"{dataset}.csv",
            processed_directory / dataset,
            reference_date=reference_date,
        )
        for dataset in ("encounters", "diagnoses", "observations")
    }

    with connect_database(database_url) as connection:
        apply_schema(connection, schema_path)
        persist_patient_validation_outputs(connection, processed_directory / "patients")
        for dataset in ("encounters", "diagnoses", "observations"):
            persist_entity_validation_outputs(
                connection,
                dataset,
                processed_directory / dataset,
            )
        cohort_summary = build_hypertension_cohort(
            connection,
            cohort_sql_path,
            analytics_directory,
        )

    return DemoSummary(
        patient_run_id=patient_summary.run_id,
        encounter_run_id=entity_summaries["encounters"].run_id,
        diagnosis_run_id=entity_summaries["diagnoses"].run_id,
        observation_run_id=entity_summaries["observations"].run_id,
        cohort=cohort_summary,
    )
