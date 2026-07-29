"""End-to-end demonstration workflow for the synthetic clinical datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID

from clinical_data_platform.cohort import CohortSummary, build_hypertension_cohort
from clinical_data_platform.database import (
    apply_schema,
    connect_database,
    persist_dataset_validation_outputs,
)
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.registry import dataset_names


@dataclass(frozen=True, slots=True)
class DemoSummary:
    """Key identifiers and counts produced by the demonstration workflow."""

    dataset_run_ids: dict[str, UUID]
    cohort: CohortSummary

    @property
    def patient_run_id(self) -> UUID:
        """Return the patient run identifier for concise CLI reporting."""
        return self.dataset_run_ids["patients"]


def run_demo(
    repository_root: Path,
    database_url: str,
    *,
    reference_date: date = date(2026, 7, 29),
) -> DemoSummary:
    """Validate, persist, and analyze all registered bundled datasets."""
    sample_directory = repository_root / "data" / "sample"
    processed_directory = repository_root / "data" / "processed"
    analytics_directory = repository_root / "data" / "analytics"
    schema_path = repository_root / "sql" / "schema.sql"
    cohort_sql_path = repository_root / "sql" / "cohorts" / "hypertension.sql"

    validation_summaries = {
        dataset: run_dataset_validation(
            dataset,
            sample_directory / f"{dataset}.csv",
            processed_directory / dataset,
            reference_date=reference_date,
        )
        for dataset in dataset_names()
    }

    with connect_database(database_url) as connection:
        apply_schema(connection, schema_path)
        for dataset in dataset_names():
            persist_dataset_validation_outputs(
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
        dataset_run_ids={
            dataset: summary.run_id for dataset, summary in validation_summaries.items()
        },
        cohort=cohort_summary,
    )
