"""Shared data structures for contract validation and pipeline execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

ClinicalRecord = dict[str, str]


@dataclass(frozen=True, slots=True)
class ValidationError:
    """One normalized validation failure for any registered dataset."""

    row_number: int
    entity_id: str
    patient_id: str
    field: str
    rule: str
    message: str
    value: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Valid rows, rejected rows, and normalized validation failures."""

    valid_records: tuple[ClinicalRecord, ...]
    invalid_records: tuple[ClinicalRecord, ...]
    errors: tuple[ValidationError, ...]

    @property
    def rows_received(self) -> int:
        """Return the total number of evaluated rows."""
        return len(self.valid_records) + len(self.invalid_records)


@dataclass(frozen=True, slots=True)
class DatasetPipelineSummary:
    """Summary and output locations for one contract-governed validation run."""

    run_id: UUID
    dataset: str
    contract_version: str
    contract_sha256: str
    source_sha256: str
    raw_receipt_id: UUID
    raw_manifest_relative_path: str
    raw_manifest_sha256: str
    raw_object_relative_path: str
    raw_size_bytes: int
    rows_received: int
    rows_valid: int
    rows_invalid: int
    validation_errors: int
    execution_event_count: int
    execution_journal_head_sha256: str
    valid_records_path: Path
    invalid_records_path: Path
    validation_errors_path: Path
    quality_report_path: Path
    execution_journal_path: Path
