"""Reproducible cohort construction and feature export."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from clinical_data_platform.structured_logging import (
    bind_log_context,
    emit_log,
    ensure_correlation_id,
    get_logger,
    log_operation,
)

REQUIRED_SOURCE_DATASETS = frozenset(
    {"patients", "encounters", "diagnoses", "observations"}
)
HYPERTENSION_DEFINITION_VERSION = "hypertension-v1"
HYPERTENSION_DEFINITION_PACKAGE: Final = "clinical_data_platform.cohort_definitions"
HYPERTENSION_DEFINITION_RESOURCE: Final = "hypertension.sql"
HYPERTENSION_FIELDS = (
    "patient_id",
    "index_date",
    "age_at_index",
    "sex_at_birth",
    "baseline_systolic_bp",
    "baseline_diastolic_bp",
    "prior_encounter_count_365d",
    "prior_diagnosis_count_365d",
    "follow_up_days",
)
LOGGER = get_logger("cohort")


class CohortBuildError(RuntimeError):
    """Raised when cohort prerequisites are missing or inconsistent."""


@dataclass(frozen=True, slots=True)
class CohortSummary:
    """Result and output locations for one cohort build."""

    cohort_run_id: UUID
    cohort_name: str
    definition_version: str
    row_count: int
    features_path: Path
    metadata_path: Path


def load_hypertension_cohort_sql(sql_path: Path | None = None) -> tuple[str, str]:
    """Load the packaged cohort definition or an explicit reviewed override."""
    if sql_path is None:
        resource = files(HYPERTENSION_DEFINITION_PACKAGE).joinpath(
            HYPERTENSION_DEFINITION_RESOURCE
        )
        if not resource.is_file():
            raise FileNotFoundError(
                "Packaged hypertension cohort definition was not found."
            )
        return (
            resource.read_text(encoding="utf-8"),
            f"{HYPERTENSION_DEFINITION_PACKAGE}:{HYPERTENSION_DEFINITION_RESOURCE}",
        )

    if not sql_path.exists():
        raise FileNotFoundError(f"Cohort SQL file not found: {sql_path}")
    if not sql_path.is_file():
        raise FileNotFoundError(f"Cohort SQL path is not a file: {sql_path}")
    return sql_path.read_text(encoding="utf-8"), str(sql_path)


def _source_runs(
    connection: psycopg.Connection[Any],
) -> tuple[tuple[UUID, str], ...]:
    rows = connection.execute(
        """
        SELECT DISTINCT ON (dataset_name)
            run_id,
            dataset_name
        FROM audit.pipeline_runs
        WHERE status = 'completed'
          AND dataset_name = ANY(%s)
        ORDER BY dataset_name, loaded_at DESC, run_id DESC
        """,
        (list(REQUIRED_SOURCE_DATASETS),),
    ).fetchall()
    typed_rows = tuple((row[0], str(row[1])) for row in rows)
    available = {dataset for _, dataset in typed_rows}
    missing = REQUIRED_SOURCE_DATASETS - available
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise CohortBuildError(f"Missing persisted source datasets: {missing_text}")
    return typed_rows


def build_hypertension_cohort(
    connection: psycopg.Connection[Any],
    sql_path: Path | None,
    output_directory: Path,
    *,
    minimum_age: int = 18,
    minimum_follow_up_days: int = 30,
    baseline_window_days: int = 30,
) -> CohortSummary:
    """Build and export the versioned hypertension baseline-feature cohort."""
    if minimum_age < 18:
        raise ValueError("minimum_age must be at least 18")
    if minimum_follow_up_days < 0:
        raise ValueError("minimum_follow_up_days cannot be negative")
    if baseline_window_days < 0:
        raise ValueError("baseline_window_days cannot be negative")

    cohort_sql, cohort_sql_source = load_hypertension_cohort_sql(sql_path)

    with ensure_correlation_id():
        emit_log(
            LOGGER,
            logging.INFO,
            "cohort.run.started",
            "Started hypertension cohort build.",
            cohort_name="hypertension",
            definition_version=HYPERTENSION_DEFINITION_VERSION,
            cohort_sql_source=cohort_sql_source,
            minimum_age=minimum_age,
            minimum_follow_up_days=minimum_follow_up_days,
            baseline_window_days=baseline_window_days,
        )
        with log_operation(
            LOGGER,
            "cohort.source_runs",
            operation="resolve_source_runs",
            stage="source_resolution",
            cohort_name="hypertension",
        ) as source_log:
            source_runs = _source_runs(connection)
            source_log["source_run_count"] = len(source_runs)
            source_log["source_datasets"] = sorted(dataset for _, dataset in source_runs)

        cohort_run_id = uuid4()
        generated_at = datetime.now(UTC)
        parameters = {
            "minimum_age": minimum_age,
            "minimum_follow_up_days": minimum_follow_up_days,
            "baseline_window_days": baseline_window_days,
        }

        with bind_log_context(
            cohort_run_id=str(cohort_run_id),
            cohort_name="hypertension",
        ):
            with log_operation(
                LOGGER,
                "cohort.database_build",
                operation="execute_cohort_sql",
                stage="database_build",
                definition_version=HYPERTENSION_DEFINITION_VERSION,
                cohort_sql_source=cohort_sql_source,
                source_run_count=len(source_runs),
            ) as database_log:
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO audit.cohort_runs (
                            cohort_run_id, cohort_name, definition_version,
                            parameters, row_count, generated_at
                        )
                        VALUES (%s, %s, %s, %s, 0, %s)
                        """,
                        (
                            cohort_run_id,
                            "hypertension",
                            HYPERTENSION_DEFINITION_VERSION,
                            Jsonb(parameters),
                            generated_at,
                        ),
                    )
                    with connection.cursor() as cursor:
                        cursor.executemany(
                            """
                            INSERT INTO audit.cohort_source_runs (
                                cohort_run_id,
                                source_run_id
                            )
                            VALUES (%s, %s)
                            """,
                            [(cohort_run_id, run_id) for run_id, _ in source_runs],
                        )

                    rows = connection.execute(
                        cohort_sql,
                        {
                            "cohort_run_id": cohort_run_id,
                            "minimum_age": minimum_age,
                            "minimum_follow_up_days": minimum_follow_up_days,
                            "baseline_window_days": baseline_window_days,
                        },
                        prepare=False,
                    ).fetchall()
                    connection.execute(
                        """
                        UPDATE audit.cohort_runs
                        SET row_count = %s
                        WHERE cohort_run_id = %s
                        """,
                        (len(rows), cohort_run_id),
                    )
                database_log["row_count"] = len(rows)

            output_directory.mkdir(parents=True, exist_ok=True)
            features_path = output_directory / "hypertension_features.csv"
            metadata_path = output_directory / "hypertension_cohort_metadata.json"

            with log_operation(
                LOGGER,
                "cohort.export",
                operation="export_cohort_outputs",
                stage="export",
                row_count=len(rows),
            ) as export_log:
                with features_path.open("w", encoding="utf-8", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow(HYPERTENSION_FIELDS)
                    writer.writerows(rows)

                metadata = {
                    "cohort_run_id": str(cohort_run_id),
                    "cohort_name": "hypertension",
                    "definition_version": HYPERTENSION_DEFINITION_VERSION,
                    "cohort_sql_source": cohort_sql_source,
                    "generated_at": generated_at.isoformat(),
                    "parameters": parameters,
                    "row_count": len(rows),
                    "source_run_ids": [str(run_id) for run_id, _ in source_runs],
                    "output": str(features_path),
                }
                with metadata_path.open("w", encoding="utf-8") as file:
                    json.dump(metadata, file, indent=2, sort_keys=True)
                    file.write("\n")
                export_log["features_file"] = features_path.name
                export_log["metadata_file"] = metadata_path.name

            emit_log(
                LOGGER,
                logging.INFO,
                "cohort.run.completed",
                "Completed hypertension cohort build.",
                outcome="success",
                row_count=len(rows),
                definition_version=HYPERTENSION_DEFINITION_VERSION,
            )
            return CohortSummary(
                cohort_run_id=cohort_run_id,
                cohort_name="hypertension",
                definition_version=HYPERTENSION_DEFINITION_VERSION,
                row_count=len(rows),
                features_path=features_path,
                metadata_path=metadata_path,
            )
