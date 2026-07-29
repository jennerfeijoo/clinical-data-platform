"""Reproducible cohort construction and feature export."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

REQUIRED_SOURCE_DATASETS = frozenset(
    {"patients", "encounters", "diagnoses", "observations"}
)
HYPERTENSION_DEFINITION_VERSION = "hypertension-v1"
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
    sql_path: Path,
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
    if not sql_path.exists():
        raise FileNotFoundError(f"Cohort SQL file not found: {sql_path}")

    source_runs = _source_runs(connection)
    cohort_run_id = uuid4()
    generated_at = datetime.now(UTC)
    parameters = {
        "minimum_age": minimum_age,
        "minimum_follow_up_days": minimum_follow_up_days,
        "baseline_window_days": baseline_window_days,
    }
    cohort_sql = sql_path.read_text(encoding="utf-8")

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
                INSERT INTO audit.cohort_source_runs (cohort_run_id, source_run_id)
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

    output_directory.mkdir(parents=True, exist_ok=True)
    features_path = output_directory / "hypertension_features.csv"
    metadata_path = output_directory / "hypertension_cohort_metadata.json"

    with features_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(HYPERTENSION_FIELDS)
        writer.writerows(rows)

    metadata = {
        "cohort_run_id": str(cohort_run_id),
        "cohort_name": "hypertension",
        "definition_version": HYPERTENSION_DEFINITION_VERSION,
        "generated_at": generated_at.isoformat(),
        "parameters": parameters,
        "row_count": len(rows),
        "source_run_ids": [str(run_id) for run_id, _ in source_runs],
        "output": str(features_path),
    }
    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, sort_keys=True)
        file.write("\n")

    return CohortSummary(
        cohort_run_id=cohort_run_id,
        cohort_name="hypertension",
        definition_version=HYPERTENSION_DEFINITION_VERSION,
        row_count=len(rows),
        features_path=features_path,
        metadata_path=metadata_path,
    )
