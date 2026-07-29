"""End-to-end demonstration workflow for the synthetic clinical datasets."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from uuid import UUID

from clinical_data_platform.cohort import CohortSummary, build_hypertension_cohort
from clinical_data_platform.database import (
    connect_database,
    persist_dataset_validation_outputs,
)
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.registry import dataset_names
from clinical_data_platform.structured_logging import (
    emit_log,
    ensure_correlation_id,
    get_logger,
    log_operation,
)

LOGGER = get_logger("demo")


@dataclass(frozen=True, slots=True)
class DemoSummary:
    """Key identifiers and counts produced by the demonstration workflow."""

    dataset_run_ids: dict[str, UUID]
    raw_receipt_ids: dict[str, UUID]
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
    baseline_existing: bool = False,
) -> DemoSummary:
    """Capture, migrate, validate, persist, and analyze bundled datasets."""
    sample_directory = repository_root / "data" / "sample"
    raw_directory = repository_root / "data" / "raw"
    processed_directory = repository_root / "data" / "processed"
    analytics_directory = repository_root / "data" / "analytics"
    cohort_sql_path = repository_root / "sql" / "cohorts" / "hypertension.sql"
    datasets = dataset_names()

    with ensure_correlation_id():
        emit_log(
            LOGGER,
            logging.INFO,
            "demo.run.started",
            "Started complete synthetic-data demonstration.",
            dataset_count=len(datasets),
            reference_date=reference_date.isoformat(),
            baseline_existing=baseline_existing,
        )
        with log_operation(
            LOGGER,
            "demo.validation",
            operation="validate_all_datasets",
            stage="validation",
            dataset_count=len(datasets),
        ) as validation_log:
            validation_summaries = {
                dataset: run_dataset_validation(
                    dataset,
                    sample_directory / f"{dataset}.csv",
                    processed_directory / dataset,
                    raw_root=raw_directory,
                    reference_date=reference_date,
                )
                for dataset in datasets
            }
            validation_log["validated_dataset_count"] = len(validation_summaries)
            validation_log["rows_valid"] = sum(
                summary.rows_valid for summary in validation_summaries.values()
            )
            validation_log["rows_invalid"] = sum(
                summary.rows_invalid for summary in validation_summaries.values()
            )

        with connect_database(database_url) as connection:
            with log_operation(
                LOGGER,
                "demo.migration",
                operation="migrate_database",
                stage="migration",
            ) as migration_log:
                migration_summary = migrate_database(
                    connection,
                    baseline_existing=baseline_existing,
                )
                migration_log["previous_version"] = migration_summary.previous_version
                migration_log["current_version"] = migration_summary.current_version
                migration_log["applied_versions"] = migration_summary.applied_versions

            with log_operation(
                LOGGER,
                "demo.persistence",
                operation="persist_all_datasets",
                stage="persistence",
                dataset_count=len(datasets),
            ) as persistence_log:
                persistence_summaries = {
                    dataset: persist_dataset_validation_outputs(
                        connection,
                        dataset,
                        processed_directory / dataset,
                        raw_root=raw_directory,
                    )
                    for dataset in datasets
                }
                persistence_log["persisted_dataset_count"] = len(persistence_summaries)
                persistence_log["records_persisted"] = sum(
                    summary.records_upserted for summary in persistence_summaries.values()
                )

            cohort_summary = build_hypertension_cohort(
                connection,
                cohort_sql_path,
                analytics_directory,
            )

        emit_log(
            LOGGER,
            logging.INFO,
            "demo.run.completed",
            "Completed complete synthetic-data demonstration.",
            outcome="success",
            dataset_count=len(datasets),
            cohort_row_count=cohort_summary.row_count,
        )
        return DemoSummary(
            dataset_run_ids={
                dataset: summary.run_id
                for dataset, summary in validation_summaries.items()
            },
            raw_receipt_ids={
                dataset: summary.raw_receipt_id
                for dataset, summary in validation_summaries.items()
            },
            cohort=cohort_summary,
        )
