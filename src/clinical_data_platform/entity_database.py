"""PostgreSQL persistence for validated clinical entity outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import UUID

import psycopg

from clinical_data_platform.ingestion import read_csv_records

SUPPORTED_DATASETS = frozenset({"encounters", "diagnoses", "observations"})


class EntityPersistenceError(RuntimeError):
    """Raised when entity validation outputs are incomplete or inconsistent."""


class EntityQualityReport(TypedDict):
    run_id: str
    dataset: str
    generated_at: str
    input_path: str
    input_sha256: str
    reference_date: str
    rows_received: int
    rows_valid: int
    rows_invalid: int
    validation_errors: int
    status: str


@dataclass(frozen=True, slots=True)
class EntityPersistenceSummary:
    """Result of loading one entity validation run into PostgreSQL."""

    run_id: UUID
    dataset: str
    already_loaded: bool
    records_upserted: int
    validation_errors_inserted: int


def _read_quality_report(path: Path) -> EntityQualityReport:
    if not path.exists():
        raise FileNotFoundError(f"Quality report not found: {path}")
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise EntityPersistenceError("The quality report must contain a JSON object.")

    string_fields = (
        "run_id",
        "dataset",
        "generated_at",
        "input_path",
        "input_sha256",
        "reference_date",
        "status",
    )
    integer_fields = (
        "rows_received",
        "rows_valid",
        "rows_invalid",
        "validation_errors",
    )
    for field in string_fields:
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise EntityPersistenceError(
                f"Quality report field must be a non-empty string: {field}"
            )
    for field in integer_fields:
        value = raw.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise EntityPersistenceError(
                f"Quality report field must be a non-negative integer: {field}"
            )

    return EntityQualityReport(
        run_id=raw["run_id"],
        dataset=raw["dataset"],
        generated_at=raw["generated_at"],
        input_path=raw["input_path"],
        input_sha256=raw["input_sha256"],
        reference_date=raw["reference_date"],
        rows_received=raw["rows_received"],
        rows_valid=raw["rows_valid"],
        rows_invalid=raw["rows_invalid"],
        validation_errors=raw["validation_errors"],
        status=raw["status"],
    )


def _validate_counts(
    report: EntityQualityReport,
    valid_records: list[dict[str, str]],
    invalid_records: list[dict[str, str]],
    validation_errors: list[dict[str, str]],
) -> None:
    if report["rows_received"] != len(valid_records) + len(invalid_records):
        raise EntityPersistenceError("rows_received does not match the CSV outputs.")
    if report["rows_valid"] != len(valid_records):
        raise EntityPersistenceError("rows_valid does not match the valid-record output.")
    if report["rows_invalid"] != len(invalid_records):
        raise EntityPersistenceError("rows_invalid does not match the invalid-record output.")
    if report["validation_errors"] != len(validation_errors):
        raise EntityPersistenceError(
            "validation_errors does not match validation_errors.csv."
        )


def _encounter_values(
    records: list[dict[str, str]],
    run_id: UUID,
    source_sha256: str,
) -> list[tuple[object, ...]]:
    return [
        (
            record["encounter_id"],
            record["patient_id"],
            record["encounter_type"],
            datetime.fromisoformat(record["start_datetime"]),
            datetime.fromisoformat(record["end_datetime"]),
            record["source_system"],
            run_id,
            source_sha256,
        )
        for record in records
    ]


def _diagnosis_values(
    records: list[dict[str, str]],
    run_id: UUID,
    source_sha256: str,
) -> list[tuple[object, ...]]:
    return [
        (
            record["diagnosis_id"],
            record["patient_id"],
            record["encounter_id"],
            record["code_system"],
            record["diagnosis_code"],
            datetime.fromisoformat(record["diagnosis_datetime"]),
            record["source_system"],
            run_id,
            source_sha256,
        )
        for record in records
    ]


def _observation_values(
    records: list[dict[str, str]],
    run_id: UUID,
    source_sha256: str,
) -> list[tuple[object, ...]]:
    return [
        (
            record["observation_id"],
            record["patient_id"],
            record["encounter_id"],
            record["observation_code"],
            float(record["value_numeric"]),
            record["unit"],
            datetime.fromisoformat(record["observed_at"]),
            record["source_system"],
            run_id,
            source_sha256,
        )
        for record in records
    ]


def _upsert_records(
    connection: psycopg.Connection[Any],
    dataset: str,
    records: list[dict[str, str]],
    run_id: UUID,
    source_sha256: str,
) -> None:
    if not records:
        return

    if dataset == "encounters":
        values = _encounter_values(records, run_id, source_sha256)
        statement = """
            INSERT INTO clinical.encounters (
                encounter_id, patient_id, encounter_type, start_datetime,
                end_datetime, source_system, source_run_id, source_sha256
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (encounter_id) DO UPDATE SET
                patient_id = EXCLUDED.patient_id,
                encounter_type = EXCLUDED.encounter_type,
                start_datetime = EXCLUDED.start_datetime,
                end_datetime = EXCLUDED.end_datetime,
                source_system = EXCLUDED.source_system,
                source_run_id = EXCLUDED.source_run_id,
                source_sha256 = EXCLUDED.source_sha256,
                loaded_at = CURRENT_TIMESTAMP
        """
    elif dataset == "diagnoses":
        values = _diagnosis_values(records, run_id, source_sha256)
        statement = """
            INSERT INTO clinical.diagnoses (
                diagnosis_id, patient_id, encounter_id, code_system,
                diagnosis_code, diagnosis_datetime, source_system,
                source_run_id, source_sha256
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (diagnosis_id) DO UPDATE SET
                patient_id = EXCLUDED.patient_id,
                encounter_id = EXCLUDED.encounter_id,
                code_system = EXCLUDED.code_system,
                diagnosis_code = EXCLUDED.diagnosis_code,
                diagnosis_datetime = EXCLUDED.diagnosis_datetime,
                source_system = EXCLUDED.source_system,
                source_run_id = EXCLUDED.source_run_id,
                source_sha256 = EXCLUDED.source_sha256,
                loaded_at = CURRENT_TIMESTAMP
        """
    elif dataset == "observations":
        values = _observation_values(records, run_id, source_sha256)
        statement = """
            INSERT INTO clinical.observations (
                observation_id, patient_id, encounter_id, observation_code,
                value_numeric, unit, observed_at, source_system,
                source_run_id, source_sha256
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (observation_id) DO UPDATE SET
                patient_id = EXCLUDED.patient_id,
                encounter_id = EXCLUDED.encounter_id,
                observation_code = EXCLUDED.observation_code,
                value_numeric = EXCLUDED.value_numeric,
                unit = EXCLUDED.unit,
                observed_at = EXCLUDED.observed_at,
                source_system = EXCLUDED.source_system,
                source_run_id = EXCLUDED.source_run_id,
                source_sha256 = EXCLUDED.source_sha256,
                loaded_at = CURRENT_TIMESTAMP
        """
    else:
        raise EntityPersistenceError(f"Unsupported dataset: {dataset}")

    with connection.cursor() as cursor:
        cursor.executemany(statement, values)


def persist_entity_validation_outputs(
    connection: psycopg.Connection[Any],
    dataset: str,
    output_directory: Path,
) -> EntityPersistenceSummary:
    """Persist one encounter, diagnosis, or observation validation run."""
    if dataset not in SUPPORTED_DATASETS:
        supported = ", ".join(sorted(SUPPORTED_DATASETS))
        raise EntityPersistenceError(
            f"Unsupported dataset {dataset!r}; expected one of: {supported}"
        )

    report = _read_quality_report(output_directory / "quality_report.json")
    valid_records = read_csv_records(output_directory / f"valid_{dataset}.csv")
    invalid_records = read_csv_records(output_directory / f"invalid_{dataset}.csv")
    validation_errors = read_csv_records(output_directory / "validation_errors.csv")
    _validate_counts(report, valid_records, invalid_records, validation_errors)

    if report["dataset"] != dataset:
        raise EntityPersistenceError(
            f"Quality report contains {report['dataset']!r}, expected {dataset!r}."
        )
    if report["status"] != "completed":
        raise EntityPersistenceError("Only completed validation runs can be persisted.")
    if len(report["input_sha256"]) != 64:
        raise EntityPersistenceError("input_sha256 must contain 64 characters.")

    try:
        run_id = UUID(report["run_id"])
        generated_at = datetime.fromisoformat(report["generated_at"])
        reference_date = date.fromisoformat(report["reference_date"])
    except ValueError as exc:
        raise EntityPersistenceError(
            "The quality report contains an invalid UUID or date."
        ) from exc

    error_values = [
        (
            run_id,
            int(error["row_number"]),
            error["entity_id"] or None,
            error["patient_id"] or None,
            error["field"],
            error["rule"],
            error["message"],
            error["value"] or None,
        )
        for error in validation_errors
    ]

    with connection.transaction():
        inserted_run = connection.execute(
            """
            INSERT INTO audit.pipeline_runs (
                run_id, dataset_name, source_path, source_sha256,
                reference_date, rows_received, rows_valid, rows_invalid,
                validation_errors, status, generated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            """,
            (
                run_id,
                dataset,
                report["input_path"],
                report["input_sha256"],
                reference_date,
                report["rows_received"],
                report["rows_valid"],
                report["rows_invalid"],
                report["validation_errors"],
                report["status"],
                generated_at,
            ),
        )
        if inserted_run.rowcount == 0:
            return EntityPersistenceSummary(run_id, dataset, True, 0, 0)

        _upsert_records(
            connection,
            dataset,
            valid_records,
            run_id,
            report["input_sha256"],
        )
        if error_values:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO audit.validation_errors (
                        run_id, row_number, entity_id, patient_id,
                        field_name, rule_name, message, rejected_value
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    error_values,
                )

    return EntityPersistenceSummary(
        run_id=run_id,
        dataset=dataset,
        already_loaded=False,
        records_upserted=len(valid_records),
        validation_errors_inserted=len(error_values),
    )
