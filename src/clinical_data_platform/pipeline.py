"""Generic validation pipeline for every registered clinical dataset."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from clinical_data_platform.ingestion import read_csv_records
from clinical_data_platform.models import DatasetPipelineSummary, ValidationError
from clinical_data_platform.registry import get_dataset_definition


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
    reference_date: date | None = None,
) -> DatasetPipelineSummary:
    """Validate one registered dataset and write consistent audit outputs."""
    definition = get_dataset_definition(dataset)
    effective_reference_date = reference_date or date.today()
    run_id = uuid4()
    source_sha256 = _sha256(input_path)
    records = read_csv_records(input_path)
    result = definition.validator(records, effective_reference_date)

    output_directory.mkdir(parents=True, exist_ok=True)
    valid_records_path = output_directory / f"valid_{dataset}.csv"
    invalid_records_path = output_directory / f"invalid_{dataset}.csv"
    validation_errors_path = output_directory / "validation_errors.csv"
    quality_report_path = output_directory / "quality_report.json"

    _write_records(valid_records_path, definition.columns, result.valid_records)
    _write_records(invalid_records_path, definition.columns, result.invalid_records)
    _write_errors(validation_errors_path, result.errors)

    rule_counts = Counter(error.rule for error in result.errors)
    quality_report: dict[str, object] = {
        "run_id": str(run_id),
        "dataset": dataset,
        "generated_at": datetime.now(UTC).isoformat(),
        "input_path": str(input_path),
        "input_sha256": source_sha256,
        "reference_date": effective_reference_date.isoformat(),
        "rows_received": result.rows_received,
        "rows_valid": len(result.valid_records),
        "rows_invalid": len(result.invalid_records),
        "validation_errors": len(result.errors),
        "errors_by_rule": dict(sorted(rule_counts.items())),
        "status": "completed",
    }
    with quality_report_path.open("w", encoding="utf-8") as file:
        json.dump(quality_report, file, indent=2, sort_keys=True)
        file.write("\n")

    return DatasetPipelineSummary(
        run_id=run_id,
        dataset=dataset,
        source_sha256=source_sha256,
        rows_received=result.rows_received,
        rows_valid=len(result.valid_records),
        rows_invalid=len(result.invalid_records),
        validation_errors=len(result.errors),
        valid_records_path=valid_records_path,
        invalid_records_path=invalid_records_path,
        validation_errors_path=validation_errors_path,
        quality_report_path=quality_report_path,
    )
