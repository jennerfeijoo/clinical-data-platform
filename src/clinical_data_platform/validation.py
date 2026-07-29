"""Validation rules for synthetic patient records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

PatientRecord = dict[str, str]

ALLOWED_SEX_VALUES = frozenset({"F", "M", "OTHER", "UNKNOWN"})
PATIENT_COLUMNS = (
    "patient_id",
    "sex_at_birth",
    "birth_date",
    "death_date",
    "source_system",
)
REQUIRED_PATIENT_VALUES = (
    "patient_id",
    "sex_at_birth",
    "birth_date",
    "source_system",
)


@dataclass(frozen=True, slots=True)
class ValidationError:
    """One structured validation failure."""

    row_number: int
    patient_id: str
    field: str
    rule: str
    message: str
    value: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Valid rows, rejected rows, and their structured errors."""

    valid_records: tuple[PatientRecord, ...]
    invalid_records: tuple[PatientRecord, ...]
    errors: tuple[ValidationError, ...]

    @property
    def rows_received(self) -> int:
        """Return the total number of evaluated rows."""
        return len(self.valid_records) + len(self.invalid_records)


def _parse_iso_date(value: str) -> date:
    """Parse a calendar date that strictly follows YYYY-MM-DD."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def validate_patient_records(
    records: Sequence[Mapping[str, str]],
    *,
    reference_date: date | None = None,
) -> ValidationResult:
    """Validate patient rows using structural, categorical, and temporal rules."""
    current_date = reference_date or date.today()
    valid_records: list[PatientRecord] = []
    invalid_records: list[PatientRecord] = []
    errors: list[ValidationError] = []
    seen_patient_ids: set[str] = set()

    for row_number, source_record in enumerate(records, start=2):
        record = dict(source_record)
        normalized = {key: value.strip() for key, value in record.items()}
        row_errors: list[ValidationError] = []
        patient_id = normalized.get("patient_id", "")

        missing_columns = [column for column in PATIENT_COLUMNS if column not in record]
        for field in missing_columns:
            row_errors.append(
                ValidationError(
                    row_number=row_number,
                    patient_id=patient_id,
                    field=field,
                    rule="required_column",
                    message=f"Required column is missing: {field}",
                    value="",
                )
            )

        for field in REQUIRED_PATIENT_VALUES:
            value = normalized.get(field, "")
            if not value:
                row_errors.append(
                    ValidationError(
                        row_number=row_number,
                        patient_id=patient_id,
                        field=field,
                        rule="required_value",
                        message=f"{field} cannot be empty",
                        value=value,
                    )
                )

        if patient_id:
            if patient_id in seen_patient_ids:
                row_errors.append(
                    ValidationError(
                        row_number=row_number,
                        patient_id=patient_id,
                        field="patient_id",
                        rule="unique",
                        message=f"Duplicate patient_id: {patient_id}",
                        value=patient_id,
                    )
                )
            else:
                seen_patient_ids.add(patient_id)

        sex_at_birth = normalized.get("sex_at_birth", "")
        if sex_at_birth and sex_at_birth not in ALLOWED_SEX_VALUES:
            allowed = ", ".join(sorted(ALLOWED_SEX_VALUES))
            row_errors.append(
                ValidationError(
                    row_number=row_number,
                    patient_id=patient_id,
                    field="sex_at_birth",
                    rule="allowed_values",
                    message=f"sex_at_birth must be one of: {allowed}",
                    value=sex_at_birth,
                )
            )

        birth_date: date | None = None
        birth_date_text = normalized.get("birth_date", "")
        if birth_date_text:
            try:
                birth_date = _parse_iso_date(birth_date_text)
            except ValueError:
                row_errors.append(
                    ValidationError(
                        row_number=row_number,
                        patient_id=patient_id,
                        field="birth_date",
                        rule="iso_date",
                        message="birth_date must use YYYY-MM-DD format",
                        value=birth_date_text,
                    )
                )
            else:
                if birth_date > current_date:
                    row_errors.append(
                        ValidationError(
                            row_number=row_number,
                            patient_id=patient_id,
                            field="birth_date",
                            rule="not_in_future",
                            message="birth_date cannot be in the future",
                            value=birth_date_text,
                        )
                    )

        death_date_text = normalized.get("death_date", "")
        if death_date_text:
            try:
                death_date = _parse_iso_date(death_date_text)
            except ValueError:
                row_errors.append(
                    ValidationError(
                        row_number=row_number,
                        patient_id=patient_id,
                        field="death_date",
                        rule="iso_date",
                        message="death_date must use YYYY-MM-DD format",
                        value=death_date_text,
                    )
                )
            else:
                if birth_date is not None and death_date < birth_date:
                    row_errors.append(
                        ValidationError(
                            row_number=row_number,
                            patient_id=patient_id,
                            field="death_date",
                            rule="temporal_consistency",
                            message="death_date cannot precede birth_date",
                            value=death_date_text,
                        )
                    )

        if row_errors:
            invalid_records.append(record)
            errors.extend(row_errors)
        else:
            valid_records.append(normalized)

    return ValidationResult(
        valid_records=tuple(valid_records),
        invalid_records=tuple(invalid_records),
        errors=tuple(errors),
    )
