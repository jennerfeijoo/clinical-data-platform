"""Generic validation pipeline governed by versioned executable contracts."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from clinical_data_platform.contract import validate_records_against_contract
from clinical_data_platform.execution import (
    EXECUTION_JOURNAL_VERSION,
    ExecutionAuditError,
    ExecutionJournal,
)
from clinical_data_platform.ingestion import read_csv_records
from clinical_data_platform.models import DatasetPipelineSummary, ValidationError
from clinical_data_platform.raw import RAW_STORAGE_VERSION, capture_raw_source
from clinical_data_platform.registry import get_dataset_definition


def _write_records(
    path: Path,
    columns: Sequence[str],
    records: Sequence[Mapping[str, str]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _write_errors(path: Path, errors: Sequence[ValidationError]) -> None:
    fieldnames = (
        "row_number",
        "entity_id",
        "patient_id",
        "field",
        "rule",
        "message",
        "value",
    )
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(error) for error in errors)


def run_dataset_validation(
    dataset: str,
    input_path: Path,
    output_directory: Path,
    *,
    raw_root: Path,
    reference_date: date | None = None,
) -> DatasetPipelineSummary:
    """Capture and validate one dataset while preserving an execution journal."""
    definition = get_dataset_definition(dataset)
    contract = definition.contract
    effective_reference_date = reference_date or date.today()
    run_id = uuid4()

    output_directory.mkdir(parents=True, exist_ok=True)
    execution_journal_path = output_directory / "execution" / f"{run_id}.jsonl"
    journal = ExecutionJournal.create(
        execution_journal_path,
        run_id,
        dataset,
        source_path=input_path,
    )
    current_stage = "raw_capture"

    try:
        raw_receipt = capture_raw_source(dataset, input_path, raw_root)
        journal.transition(
            "raw_captured",
            "raw_capture",
            details={
                "raw_receipt_id": str(raw_receipt.receipt_id),
                "source_sha256": raw_receipt.sha256,
                "raw_size_bytes": raw_receipt.size_bytes,
            },
        )

        current_stage = "validation"
        journal.transition(
            "validating",
            "validation",
            details={
                "contract_path": contract.resource_path,
                "contract_version": contract.version,
                "contract_sha256": contract.sha256,
            },
        )
        records = read_csv_records(raw_receipt.object_path)
        result = validate_records_against_contract(
            records,
            contract,
            reference_date=effective_reference_date,
        )

        current_stage = "output_write"
        valid_records_path = output_directory / f"valid_{dataset}.csv"
        invalid_records_path = output_directory / f"invalid_{dataset}.csv"
        validation_errors_path = output_directory / "validation_errors.csv"
        quality_report_path = output_directory / "quality_report.json"

        _write_records(valid_records_path, contract.column_names, result.valid_records)
        _write_records(invalid_records_path, contract.column_names, result.invalid_records)
        _write_errors(validation_errors_path, result.errors)

        validated_event = journal.transition(
            "validated",
            "validation",
            details={
                "rows_received": result.rows_received,
                "rows_valid": len(result.valid_records),
                "rows_invalid": len(result.invalid_records),
                "validation_errors": len(result.errors),
            },
        )

        current_stage = "quality_report"
        rule_counts = Counter(error.rule for error in result.errors)
        quality_report: dict[str, object] = {
            "run_id": str(run_id),
            "dataset": dataset,
            "generated_at": validated_event.occurred_at.isoformat(),
            "input_path": str(input_path),
            "input_sha256": raw_receipt.sha256,
            "raw_storage_version": RAW_STORAGE_VERSION,
            "raw_receipt_id": str(raw_receipt.receipt_id),
            "raw_received_at": raw_receipt.received_at.isoformat(),
            "raw_manifest_path": raw_receipt.manifest_relative_path,
            "raw_manifest_sha256": raw_receipt.manifest_sha256,
            "raw_object_path": raw_receipt.object_relative_path,
            "raw_size_bytes": raw_receipt.size_bytes,
            "contract_path": contract.resource_path,
            "contract_version": contract.version,
            "contract_sha256": contract.sha256,
            "reference_date": effective_reference_date.isoformat(),
            "rows_received": result.rows_received,
            "rows_valid": len(result.valid_records),
            "rows_invalid": len(result.invalid_records),
            "validation_errors": len(result.errors),
            "errors_by_rule": dict(sorted(rule_counts.items())),
            "execution_journal_version": EXECUTION_JOURNAL_VERSION,
            "execution_journal_path": str(
                execution_journal_path.relative_to(output_directory)
            ),
            "execution_event_count": len(journal.events),
            "execution_journal_head_sha256": journal.head_sha256,
            "status": "validated",
        }
        with quality_report_path.open("w", encoding="utf-8") as file:
            json.dump(quality_report, file, indent=2, sort_keys=True)
            file.write("\n")

        return DatasetPipelineSummary(
            run_id=run_id,
            dataset=dataset,
            contract_version=contract.version,
            contract_sha256=contract.sha256,
            source_sha256=raw_receipt.sha256,
            raw_receipt_id=raw_receipt.receipt_id,
            raw_manifest_relative_path=raw_receipt.manifest_relative_path,
            raw_manifest_sha256=raw_receipt.manifest_sha256,
            raw_object_relative_path=raw_receipt.object_relative_path,
            raw_size_bytes=raw_receipt.size_bytes,
            rows_received=result.rows_received,
            rows_valid=len(result.valid_records),
            rows_invalid=len(result.invalid_records),
            validation_errors=len(result.errors),
            execution_event_count=len(journal.events),
            execution_journal_head_sha256=journal.head_sha256,
            valid_records_path=valid_records_path,
            invalid_records_path=invalid_records_path,
            validation_errors_path=validation_errors_path,
            quality_report_path=quality_report_path,
            execution_journal_path=execution_journal_path,
        )
    except Exception as exc:
        if journal.current_status not in {"failed", "completed"}:
            try:
                journal.fail(current_stage, exc)
            except (OSError, ExecutionAuditError):
                pass
        raise
