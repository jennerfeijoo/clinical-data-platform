"""Generic PostgreSQL persistence for contract-governed clinical datasets."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import UUID

import psycopg

from clinical_data_platform.bulk import copy_merge_rows, copy_rows
from clinical_data_platform.contract import load_contract_by_resource
from clinical_data_platform.execution import (
    EXECUTION_JOURNAL_VERSION,
    ExecutionAuditError,
    ExecutionJournalSummary,
    read_execution_journal,
)
from clinical_data_platform.ingestion import CsvInspection, inspect_csv_records, iter_csv_records
from clinical_data_platform.raw import RAW_STORAGE_VERSION, verify_raw_receipt
from clinical_data_platform.registry import get_dataset_definition
from clinical_data_platform.run_audit import (
    RunAuditError,
    RunRegistration,
    begin_loading_attempt,
    complete_loading_attempt,
    fail_loading_attempt,
    register_validated_run,
)
from clinical_data_platform.structured_logging import (
    bind_log_context,
    emit_log,
    ensure_correlation_id,
    get_logger,
    log_operation,
    safe_exception_fields,
)

LOGGER = get_logger("database")
VALIDATION_ERROR_SOURCE_COLUMNS = (
    "row_number",
    "entity_id",
    "patient_id",
    "field",
    "rule",
    "message",
    "value",
)
VALIDATION_ERROR_TARGET_COLUMNS = (
    "run_id",
    "row_number",
    "entity_id",
    "patient_id",
    "field_name",
    "rule_name",
    "message",
    "rejected_value",
)


class DatabaseConfigurationError(RuntimeError):
    """Raised when the database connection is not configured."""


class PersistenceError(RuntimeError):
    """Raised when validation outputs are incomplete or inconsistent."""


class QualityReport(TypedDict):
    """Required fields shared by every dataset quality report."""

    run_id: str
    dataset: str
    generated_at: str
    input_path: str
    input_sha256: str
    raw_storage_version: str
    raw_receipt_id: str
    raw_received_at: str
    raw_manifest_path: str
    raw_manifest_sha256: str
    raw_object_path: str
    raw_size_bytes: int
    contract_path: str
    contract_version: str
    contract_sha256: str
    reference_date: str
    rows_received: int
    rows_valid: int
    rows_invalid: int
    validation_errors: int
    execution_journal_version: str
    execution_journal_path: str
    execution_event_count: int
    execution_journal_head_sha256: str
    status: str


@dataclass(frozen=True, slots=True)
class DatasetPersistenceSummary:
    """Result of loading one registered dataset into PostgreSQL."""

    run_id: UUID
    dataset: str
    contract_version: str
    already_loaded: bool
    attempt_number: int
    final_status: str
    records_upserted: int
    validation_errors_inserted: int
    records_merged: int = 0
    loading_method: str = "postgresql_copy"


def database_url_from_environment() -> str:
    """Read the PostgreSQL connection URL from ``DATABASE_URL``."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required, for example: "
            "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
        )
    return database_url


def connect_database(database_url: str) -> psycopg.Connection[Any]:
    """Open a PostgreSQL connection without logging its credentials."""
    return psycopg.connect(database_url)


def _read_quality_report(path: Path) -> QualityReport:
    if not path.exists():
        raise FileNotFoundError(f"Quality report not found: {path}")

    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise PersistenceError("The quality report must contain a JSON object.")

    string_fields = (
        "run_id",
        "dataset",
        "generated_at",
        "input_path",
        "input_sha256",
        "raw_storage_version",
        "raw_receipt_id",
        "raw_received_at",
        "raw_manifest_path",
        "raw_manifest_sha256",
        "raw_object_path",
        "contract_path",
        "contract_version",
        "contract_sha256",
        "reference_date",
        "execution_journal_version",
        "execution_journal_path",
        "execution_journal_head_sha256",
        "status",
    )
    integer_fields = (
        "raw_size_bytes",
        "rows_received",
        "rows_valid",
        "rows_invalid",
        "validation_errors",
        "execution_event_count",
    )
    for field in string_fields:
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise PersistenceError(f"Quality report field must be a non-empty string: {field}")
    for field in integer_fields:
        value = raw.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise PersistenceError(
                f"Quality report field must be a non-negative integer: {field}"
            )

    return QualityReport(
        run_id=raw["run_id"],
        dataset=raw["dataset"],
        generated_at=raw["generated_at"],
        input_path=raw["input_path"],
        input_sha256=raw["input_sha256"],
        raw_storage_version=raw["raw_storage_version"],
        raw_receipt_id=raw["raw_receipt_id"],
        raw_received_at=raw["raw_received_at"],
        raw_manifest_path=raw["raw_manifest_path"],
        raw_manifest_sha256=raw["raw_manifest_sha256"],
        raw_object_path=raw["raw_object_path"],
        raw_size_bytes=raw["raw_size_bytes"],
        contract_path=raw["contract_path"],
        contract_version=raw["contract_version"],
        contract_sha256=raw["contract_sha256"],
        reference_date=raw["reference_date"],
        rows_received=raw["rows_received"],
        rows_valid=raw["rows_valid"],
        rows_invalid=raw["rows_invalid"],
        validation_errors=raw["validation_errors"],
        execution_journal_version=raw["execution_journal_version"],
        execution_journal_path=raw["execution_journal_path"],
        execution_event_count=raw["execution_event_count"],
        execution_journal_head_sha256=raw["execution_journal_head_sha256"],
        status=raw["status"],
    )


def _validate_output_counts(
    report: QualityReport,
    valid_rows: int,
    invalid_rows: int,
    validation_error_rows: int,
) -> None:
    if report["rows_received"] != valid_rows + invalid_rows:
        raise PersistenceError("rows_received does not match the generated CSV outputs.")
    if report["rows_valid"] != valid_rows:
        raise PersistenceError("rows_valid does not match the valid-record output.")
    if report["rows_invalid"] != invalid_rows:
        raise PersistenceError("rows_invalid does not match the invalid-record output.")
    if report["validation_errors"] != validation_error_rows:
        raise PersistenceError("validation_errors does not match validation_errors.csv.")


def _validate_output_columns(
    inspection: CsvInspection,
    expected_columns: tuple[str, ...],
    label: str,
) -> None:
    if inspection.columns != expected_columns:
        raise PersistenceError(
            f"{label} columns do not match the expected validated-output schema."
        )


def _validate_contract_lineage(report: QualityReport, dataset: str) -> None:
    contract = load_contract_by_resource(report["contract_path"])
    if contract.name != dataset:
        raise PersistenceError(
            f"Contract contains dataset {contract.name!r}, expected {dataset!r}."
        )
    if report["contract_version"] != contract.version:
        raise PersistenceError("contract_version does not match the referenced contract.")
    if report["contract_sha256"] != contract.sha256:
        raise PersistenceError("contract_sha256 does not match the referenced contract bytes.")


def _validate_raw_lineage(report: QualityReport, dataset: str, raw_root: Path) -> None:
    if report["raw_storage_version"] != RAW_STORAGE_VERSION:
        raise PersistenceError("raw_storage_version is not supported by this application.")

    try:
        receipt = verify_raw_receipt(raw_root, report["raw_manifest_path"])
        reported_receipt_id = UUID(report["raw_receipt_id"])
        reported_received_at = datetime.fromisoformat(report["raw_received_at"])
    except (ValueError, RuntimeError) as exc:
        raise PersistenceError("Raw landing lineage could not be verified.") from exc

    if receipt.dataset != dataset:
        raise PersistenceError("Raw receipt dataset does not match the requested dataset.")
    if receipt.receipt_id != reported_receipt_id:
        raise PersistenceError("raw_receipt_id does not match the immutable receipt.")
    if receipt.received_at != reported_received_at:
        raise PersistenceError("raw_received_at does not match the immutable receipt.")
    if receipt.manifest_sha256 != report["raw_manifest_sha256"]:
        raise PersistenceError("raw_manifest_sha256 does not match the receipt bytes.")
    if receipt.object_relative_path != report["raw_object_path"]:
        raise PersistenceError("raw_object_path does not match the immutable receipt.")
    if receipt.size_bytes != report["raw_size_bytes"]:
        raise PersistenceError("raw_size_bytes does not match the immutable object.")
    if receipt.sha256 != report["input_sha256"]:
        raise PersistenceError("input_sha256 does not match the immutable raw object.")


def _validate_execution_journal(
    report: QualityReport,
    dataset: str,
    output_directory: Path,
) -> ExecutionJournalSummary:
    if report["execution_journal_version"] != EXECUTION_JOURNAL_VERSION:
        raise PersistenceError("execution_journal_version is not supported.")
    relative_path = Path(report["execution_journal_path"])
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise PersistenceError("execution_journal_path must remain inside the output directory.")
    try:
        journal = read_execution_journal(output_directory / relative_path)
        reported_run_id = UUID(report["run_id"])
    except (ValueError, FileNotFoundError, ExecutionAuditError) as exc:
        raise PersistenceError("Execution journal could not be verified.") from exc

    if journal.run_id != reported_run_id or journal.dataset != dataset:
        raise PersistenceError("Execution journal identity does not match the quality report.")
    if journal.status != "validated" or report["status"] != "validated":
        raise PersistenceError("Only validated execution journals can be persisted.")
    if journal.event_count != report["execution_event_count"]:
        raise PersistenceError("execution_event_count does not match the journal.")
    if journal.head_sha256 != report["execution_journal_head_sha256"]:
        raise PersistenceError("execution_journal_head_sha256 does not match the journal.")
    return journal


def _registration(
    report: QualityReport,
    run_id: UUID,
    raw_receipt_id: UUID,
    generated_at: datetime,
    raw_received_at: datetime,
    reference_date: date,
) -> RunRegistration:
    return RunRegistration(
        run_id=run_id,
        dataset=report["dataset"],
        source_path=report["input_path"],
        source_sha256=report["input_sha256"],
        raw_receipt_id=raw_receipt_id,
        raw_received_at=raw_received_at,
        raw_storage_version=report["raw_storage_version"],
        raw_manifest_path=report["raw_manifest_path"],
        raw_manifest_sha256=report["raw_manifest_sha256"],
        raw_object_path=report["raw_object_path"],
        raw_size_bytes=report["raw_size_bytes"],
        contract_path=report["contract_path"],
        contract_version=report["contract_version"],
        contract_sha256=report["contract_sha256"],
        reference_date=reference_date,
        rows_received=report["rows_received"],
        rows_valid=report["rows_valid"],
        rows_invalid=report["rows_invalid"],
        validation_errors=report["validation_errors"],
        generated_at=generated_at,
    )


def _validation_error_rows(path: Path, run_id: UUID) -> Iterator[tuple[object, ...]]:
    for error in iter_csv_records(path):
        yield (
            run_id,
            int(error["row_number"]),
            error["entity_id"] or None,
            error["patient_id"] or None,
            error["field"],
            error["rule"],
            error["message"],
            error["value"] or None,
        )


def persist_dataset_validation_outputs(
    connection: psycopg.Connection[Any],
    dataset: str,
    output_directory: Path,
    *,
    raw_root: Path,
) -> DatasetPersistenceSummary:
    """Load one verified dataset with COPY while auditing every loading attempt."""
    definition = get_dataset_definition(dataset)
    valid_path = output_directory / f"valid_{dataset}.csv"
    invalid_path = output_directory / f"invalid_{dataset}.csv"
    validation_errors_path = output_directory / "validation_errors.csv"

    with ensure_correlation_id():
        with log_operation(
            LOGGER,
            "persistence.preflight",
            operation="verify_validation_outputs",
            stage="preflight",
            dataset=dataset,
        ) as preflight_log:
            report = _read_quality_report(output_directory / "quality_report.json")
            valid_output = inspect_csv_records(valid_path)
            invalid_output = inspect_csv_records(invalid_path)
            error_output = inspect_csv_records(validation_errors_path)
            _validate_output_columns(valid_output, definition.columns, "Valid-record output")
            _validate_output_columns(invalid_output, definition.columns, "Invalid-record output")
            _validate_output_columns(
                error_output,
                VALIDATION_ERROR_SOURCE_COLUMNS,
                "Validation-error output",
            )
            _validate_output_counts(
                report,
                valid_output.row_count,
                invalid_output.row_count,
                error_output.row_count,
            )

            if report["dataset"] != dataset:
                raise PersistenceError(
                    f"Quality report contains {report['dataset']!r}, expected {dataset!r}."
                )
            for field in (
                "input_sha256",
                "raw_manifest_sha256",
                "contract_sha256",
                "execution_journal_head_sha256",
            ):
                if len(report[field]) != 64:
                    raise PersistenceError(
                        f"{field} must contain 64 hexadecimal characters."
                    )
            _validate_contract_lineage(report, dataset)
            _validate_raw_lineage(report, dataset, raw_root)
            journal = _validate_execution_journal(report, dataset, output_directory)

            try:
                run_id = UUID(report["run_id"])
                raw_receipt_id = UUID(report["raw_receipt_id"])
                generated_at = datetime.fromisoformat(report["generated_at"])
                raw_received_at = datetime.fromisoformat(report["raw_received_at"])
                reference_date = date.fromisoformat(report["reference_date"])
            except ValueError as exc:
                raise PersistenceError(
                    "The quality report contains an invalid UUID or date."
                ) from exc

            preflight_log.update(
                {
                    "run_id": str(run_id),
                    "rows_valid": valid_output.row_count,
                    "rows_invalid": invalid_output.row_count,
                    "validation_errors": error_output.row_count,
                    "contract_version": report["contract_version"],
                    "loading_method": "postgresql_copy",
                }
            )

        with bind_log_context(run_id=str(run_id), dataset=dataset):
            emit_log(
                LOGGER,
                logging.INFO,
                "persistence.run.started",
                "Started dataset persistence run.",
                stage="audit_registration",
                rows_valid=valid_output.row_count,
                validation_errors=error_output.row_count,
                loading_method="postgresql_copy",
            )
            try:
                with log_operation(
                    LOGGER,
                    "persistence.audit_registration",
                    operation="register_validated_run",
                    stage="audit_registration",
                ) as registration_log:
                    register_validated_run(
                        connection,
                        _registration(
                            report,
                            run_id,
                            raw_receipt_id,
                            generated_at,
                            raw_received_at,
                            reference_date,
                        ),
                        journal,
                    )
                    attempt = begin_loading_attempt(connection, run_id)
                    registration_log["attempt_number"] = attempt.attempt_number
                    registration_log["already_completed"] = attempt.already_completed
            except RunAuditError as exc:
                raise PersistenceError(
                    "Pipeline execution audit could not begin loading."
                ) from exc

            if attempt.already_completed:
                emit_log(
                    LOGGER,
                    logging.INFO,
                    "persistence.run.idempotent",
                    "Dataset run was already completed; no rows were written.",
                    stage="persistence",
                    status="completed",
                    attempt_number=attempt.attempt_number,
                    already_loaded=True,
                    loading_method="postgresql_copy",
                )
                return DatasetPersistenceSummary(
                    run_id=run_id,
                    dataset=dataset,
                    contract_version=report["contract_version"],
                    already_loaded=True,
                    attempt_number=attempt.attempt_number,
                    final_status="completed",
                    records_upserted=0,
                    validation_errors_inserted=0,
                )

            records_copied = 0
            records_merged = 0
            errors_copied = 0
            try:
                with log_operation(
                    LOGGER,
                    "persistence.transaction",
                    operation="persist_clinical_dataset",
                    stage="persistence",
                    attempt_number=attempt.attempt_number,
                    records_attempted=valid_output.row_count,
                    validation_errors_attempted=error_output.row_count,
                    loading_method="postgresql_copy",
                ) as transaction_log:
                    with connection.transaction():
                        with log_operation(
                            LOGGER,
                            "persistence.copy",
                            operation="copy_records_to_staging",
                            stage="copy_staging",
                            attempt_number=attempt.attempt_number,
                            records_attempted=valid_output.row_count,
                            loading_method="postgresql_copy",
                        ) as copy_log:
                            copy_summary = copy_merge_rows(
                                connection,
                                definition.copy_plan,
                                definition.row_builder(
                                    iter_csv_records(valid_path),
                                    run_id,
                                    report["input_sha256"],
                                ),
                            )
                            records_copied = copy_summary.rows_copied
                            records_merged = copy_summary.rows_merged
                            if records_copied != valid_output.row_count:
                                raise PersistenceError(
                                    "COPY row count changed after validation-output preflight."
                                )
                            copy_log.update(
                                {
                                    "rows_copied": records_copied,
                                    "rows_merged": records_merged,
                                    "staging_table": copy_summary.staging_table,
                                }
                            )

                        with log_operation(
                            LOGGER,
                            "persistence.validation_error_copy",
                            operation="copy_validation_errors",
                            stage="copy_validation_errors",
                            attempt_number=attempt.attempt_number,
                            validation_errors_attempted=error_output.row_count,
                            loading_method="postgresql_copy",
                        ) as error_copy_log:
                            errors_copied = copy_rows(
                                connection,
                                schema="audit",
                                table="validation_errors",
                                columns=VALIDATION_ERROR_TARGET_COLUMNS,
                                rows=_validation_error_rows(
                                    validation_errors_path,
                                    run_id,
                                ),
                            )
                            if errors_copied != error_output.row_count:
                                raise PersistenceError(
                                    "Validation-error COPY count changed after preflight."
                                )
                            error_copy_log["validation_errors_copied"] = errors_copied

                        complete_loading_attempt(
                            connection,
                            run_id,
                            attempt.attempt_number,
                            records_persisted=records_copied,
                            validation_errors_persisted=errors_copied,
                        )
                    transaction_log["records_copied"] = records_copied
                    transaction_log["records_merged"] = records_merged
                    transaction_log["validation_errors_copied"] = errors_copied
            except Exception as exc:
                try:
                    fail_loading_attempt(
                        connection,
                        run_id,
                        attempt.attempt_number,
                        exc,
                        details={
                            "dataset": dataset,
                            "loading_method": "postgresql_copy",
                            "records_attempted": valid_output.row_count,
                            "records_copied_before_failure": records_copied,
                            "validation_errors_attempted": error_output.row_count,
                            "validation_errors_copied_before_failure": errors_copied,
                        },
                    )
                    emit_log(
                        LOGGER,
                        logging.ERROR,
                        "persistence.failure_audited",
                        "Persisted durable failure state after clinical rollback.",
                        stage="persistence",
                        status="failed",
                        attempt_number=attempt.attempt_number,
                        loading_method="postgresql_copy",
                        **safe_exception_fields(exc),
                    )
                except Exception as audit_exc:
                    emit_log(
                        LOGGER,
                        logging.CRITICAL,
                        "persistence.failure_audit_failed",
                        "Clinical rollback succeeded but durable failure audit failed.",
                        stage="failure_audit",
                        attempt_number=attempt.attempt_number,
                        loading_method="postgresql_copy",
                        **safe_exception_fields(audit_exc),
                    )
                    exc.add_note(f"Failure audit could not be persisted: {audit_exc}")
                raise

            emit_log(
                LOGGER,
                logging.INFO,
                "persistence.run.completed",
                "Completed dataset persistence run.",
                stage="completed",
                status="completed",
                attempt_number=attempt.attempt_number,
                records_persisted=records_copied,
                records_merged=records_merged,
                validation_errors_persisted=errors_copied,
                loading_method="postgresql_copy",
            )
            return DatasetPersistenceSummary(
                run_id=run_id,
                dataset=dataset,
                contract_version=report["contract_version"],
                already_loaded=False,
                attempt_number=attempt.attempt_number,
                final_status="completed",
                records_upserted=records_copied,
                validation_errors_inserted=errors_copied,
                records_merged=records_merged,
            )
