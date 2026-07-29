"""End-to-end patient validation workflow."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from clinical_data_platform.ingestion import read_csv_records
from clinical_data_platform.validation import (
    PATIENT_COLUMNS,
    ValidationError,
    validate_patient_records,
)


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    """Summary and output locations for one validation run."""

    rows_received: int
    rows_valid: int
    rows_invalid: int
    validation_errors: int
    valid_records_path: Path
    invalid_records_path: Path
    validation_errors_path: Path
    quality_report_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_records(path: Path, records: Sequence[Mapping[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PATIENT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _write_validation_errors(path: Path, errors: Sequence[ValidationError]) -> None:
    fieldnames = ("row_number", "patient_id", "field", "rule", "message", "value")
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(error) for error in errors)


def run_patient_validation(
    input_path: Path,
    output_directory: Path,
    *,
    reference_date: date | None = None,
) -> PipelineSummary:
    """Read, validate, and write patient data-quality outputs."""
    effective_reference_date = reference_date or date.today()
    records = read_csv_records(input_path)
    result = validate_patient_records(records, reference_date=effective_reference_date)

    output_directory.mkdir(parents=True, exist_ok=True)
    valid_records_path = output_directory / "valid_patients.csv"
    invalid_records_path = output_directory / "invalid_patients.csv"
    validation_errors_path = output_directory / "validation_errors.csv"
    quality_report_path = output_directory / "quality_report.json"

    _write_records(valid_records_path, result.valid_records)
    _write_records(invalid_records_path, result.invalid_records)
    _write_validation_errors(validation_errors_path, result.errors)

    rule_counts = Counter(error.rule for error in result.errors)
    quality_report: dict[str, object] = {
        "dataset": "patients",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "input_sha256": _sha256(input_path),
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

    return PipelineSummary(
        rows_received=result.rows_received,
        rows_valid=len(result.valid_records),
        rows_invalid=len(result.invalid_records),
        validation_errors=len(result.errors),
        valid_records_path=valid_records_path,
        invalid_records_path=invalid_records_path,
        validation_errors_path=validation_errors_path,
        quality_report_path=quality_report_path,
    )
