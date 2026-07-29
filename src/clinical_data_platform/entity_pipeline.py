"""Reusable validation pipeline for non-patient clinical entities."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

from clinical_data_platform.clinical_entities import (
    DIAGNOSIS_COLUMNS,
    ENCOUNTER_COLUMNS,
    OBSERVATION_COLUMNS,
    EntityValidationError,
    EntityValidationResult,
    validate_diagnosis_records,
    validate_encounter_records,
    validate_observation_records,
)
from clinical_data_platform.ingestion import read_csv_records

Validator = Callable[[Sequence[Mapping[str, str]]], EntityValidationResult]

DATASET_CONFIGURATION: dict[str, tuple[tuple[str, ...], Validator]] = {
    "encounters": (ENCOUNTER_COLUMNS, validate_encounter_records),
    "diagnoses": (DIAGNOSIS_COLUMNS, validate_diagnosis_records),
    "observations": (OBSERVATION_COLUMNS, validate_observation_records),
}


@dataclass(frozen=True, slots=True)
class EntityPipelineSummary:
    """Summary and output paths for one entity-validation run."""

    run_id: UUID
    dataset: str
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


def _write_records(
    path: Path,
    columns: Sequence[str],
    records: Sequence[Mapping[str, str]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _write_errors(path: Path, errors: Sequence[EntityValidationError]) -> None:
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


def run_entity_validation(
    dataset: str,
    input_path: Path,
    output_directory: Path,
    *,
    reference_date: date | None = None,
) -> EntityPipelineSummary:
    """Validate one supported clinical dataset and write auditable outputs."""
    try:
        columns, validator = DATASET_CONFIGURATION[dataset]
    except KeyError as exc:
        supported = ", ".join(sorted(DATASET_CONFIGURATION))
        raise ValueError(f"Unsupported dataset {dataset!r}; expected one of: {supported}") from exc

    effective_reference_date = reference_date or date.today()
    run_id = uuid4()
    records = read_csv_records(input_path)
    result = validator(records)

    output_directory.mkdir(parents=True, exist_ok=True)
    valid_records_path = output_directory / f"valid_{dataset}.csv"
    invalid_records_path = output_directory / f"invalid_{dataset}.csv"
    validation_errors_path = output_directory / "validation_errors.csv"
    quality_report_path = output_directory / "quality_report.json"

    _write_records(valid_records_path, columns, result.valid_records)
    _write_records(invalid_records_path, columns, result.invalid_records)
    _write_errors(validation_errors_path, result.errors)

    rule_counts = Counter(error.rule for error in result.errors)
    quality_report: dict[str, object] = {
        "run_id": str(run_id),
        "dataset": dataset,
        "generated_at": datetime.now(UTC).isoformat(),
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

    return EntityPipelineSummary(
        run_id=run_id,
        dataset=dataset,
        rows_received=result.rows_received,
        rows_valid=len(result.valid_records),
        rows_invalid=len(result.invalid_records),
        validation_errors=len(result.errors),
        valid_records_path=valid_records_path,
        invalid_records_path=invalid_records_path,
        validation_errors_path=validation_errors_path,
        quality_report_path=quality_report_path,
    )
