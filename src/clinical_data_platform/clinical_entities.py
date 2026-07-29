"""Validation rules for encounters, diagnoses, and observations."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

ClinicalRecord = dict[str, str]

ENCOUNTER_COLUMNS = (
    "encounter_id",
    "patient_id",
    "encounter_type",
    "start_datetime",
    "end_datetime",
    "source_system",
)
DIAGNOSIS_COLUMNS = (
    "diagnosis_id",
    "patient_id",
    "encounter_id",
    "code_system",
    "diagnosis_code",
    "diagnosis_datetime",
    "source_system",
)
OBSERVATION_COLUMNS = (
    "observation_id",
    "patient_id",
    "encounter_id",
    "observation_code",
    "value_numeric",
    "unit",
    "observed_at",
    "source_system",
)

ALLOWED_ENCOUNTER_TYPES = frozenset({"OUTPATIENT", "INPATIENT", "EMERGENCY"})
ALLOWED_CODE_SYSTEMS = frozenset({"ICD10", "SNOMED"})
OBSERVATION_RULES: dict[str, tuple[str, float, float]] = {
    "SYSTOLIC_BP": ("mmHg", 50.0, 300.0),
    "DIASTOLIC_BP": ("mmHg", 30.0, 200.0),
    "HEART_RATE": ("bpm", 20.0, 250.0),
}


@dataclass(frozen=True, slots=True)
class EntityValidationError:
    """One structured validation failure for a clinical entity."""

    row_number: int
    entity_id: str
    patient_id: str
    field: str
    rule: str
    message: str
    value: str


@dataclass(frozen=True, slots=True)
class EntityValidationResult:
    """Valid rows, rejected rows, and their structured errors."""

    valid_records: tuple[ClinicalRecord, ...]
    invalid_records: tuple[ClinicalRecord, ...]
    errors: tuple[EntityValidationError, ...]

    @property
    def rows_received(self) -> int:
        return len(self.valid_records) + len(self.invalid_records)


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone offset is required")
    return parsed


def _required_errors(
    *,
    row_number: int,
    record: Mapping[str, str],
    normalized: Mapping[str, str],
    columns: Sequence[str],
    required_values: Sequence[str],
    entity_id: str,
    patient_id: str,
) -> list[EntityValidationError]:
    errors: list[EntityValidationError] = []
    for field in columns:
        if field not in record:
            errors.append(
                EntityValidationError(
                    row_number=row_number,
                    entity_id=entity_id,
                    patient_id=patient_id,
                    field=field,
                    rule="required_column",
                    message=f"Required column is missing: {field}",
                    value="",
                )
            )
    for field in required_values:
        value = normalized.get(field, "")
        if not value:
            errors.append(
                EntityValidationError(
                    row_number=row_number,
                    entity_id=entity_id,
                    patient_id=patient_id,
                    field=field,
                    rule="required_value",
                    message=f"{field} cannot be empty",
                    value=value,
                )
            )
    return errors


def _unique_error(
    *,
    row_number: int,
    entity_id: str,
    patient_id: str,
    field: str,
    seen_ids: set[str],
) -> EntityValidationError | None:
    if not entity_id:
        return None
    if entity_id in seen_ids:
        return EntityValidationError(
            row_number=row_number,
            entity_id=entity_id,
            patient_id=patient_id,
            field=field,
            rule="unique",
            message=f"Duplicate {field}: {entity_id}",
            value=entity_id,
        )
    seen_ids.add(entity_id)
    return None


def validate_encounter_records(
    records: Sequence[Mapping[str, str]],
) -> EntityValidationResult:
    """Validate encounter identifiers, categories, and temporal consistency."""
    valid: list[ClinicalRecord] = []
    invalid: list[ClinicalRecord] = []
    errors: list[EntityValidationError] = []
    seen_ids: set[str] = set()

    for row_number, source_record in enumerate(records, start=2):
        record = dict(source_record)
        normalized = {key: value.strip() for key, value in record.items()}
        encounter_id = normalized.get("encounter_id", "")
        patient_id = normalized.get("patient_id", "")
        row_errors = _required_errors(
            row_number=row_number,
            record=record,
            normalized=normalized,
            columns=ENCOUNTER_COLUMNS,
            required_values=ENCOUNTER_COLUMNS,
            entity_id=encounter_id,
            patient_id=patient_id,
        )
        duplicate_error = _unique_error(
            row_number=row_number,
            entity_id=encounter_id,
            patient_id=patient_id,
            field="encounter_id",
            seen_ids=seen_ids,
        )
        if duplicate_error is not None:
            row_errors.append(duplicate_error)

        encounter_type = normalized.get("encounter_type", "")
        if encounter_type and encounter_type not in ALLOWED_ENCOUNTER_TYPES:
            row_errors.append(
                EntityValidationError(
                    row_number,
                    encounter_id,
                    patient_id,
                    "encounter_type",
                    "allowed_values",
                    "encounter_type must be OUTPATIENT, INPATIENT, or EMERGENCY",
                    encounter_type,
                )
            )

        start: datetime | None = None
        end: datetime | None = None
        for field in ("start_datetime", "end_datetime"):
            value = normalized.get(field, "")
            if not value:
                continue
            try:
                parsed = _parse_iso_datetime(value)
            except ValueError:
                row_errors.append(
                    EntityValidationError(
                        row_number,
                        encounter_id,
                        patient_id,
                        field,
                        "iso_datetime",
                        f"{field} must be an ISO 8601 datetime with timezone",
                        value,
                    )
                )
            else:
                if field == "start_datetime":
                    start = parsed
                else:
                    end = parsed

        if start is not None and end is not None and end < start:
            row_errors.append(
                EntityValidationError(
                    row_number,
                    encounter_id,
                    patient_id,
                    "end_datetime",
                    "temporal_consistency",
                    "end_datetime cannot precede start_datetime",
                    normalized.get("end_datetime", ""),
                )
            )

        if row_errors:
            invalid.append(record)
            errors.extend(row_errors)
        else:
            valid.append(normalized)

    return EntityValidationResult(tuple(valid), tuple(invalid), tuple(errors))


def validate_diagnosis_records(
    records: Sequence[Mapping[str, str]],
) -> EntityValidationResult:
    """Validate diagnosis identifiers, vocabularies, and timestamps."""
    valid: list[ClinicalRecord] = []
    invalid: list[ClinicalRecord] = []
    errors: list[EntityValidationError] = []
    seen_ids: set[str] = set()

    for row_number, source_record in enumerate(records, start=2):
        record = dict(source_record)
        normalized = {key: value.strip() for key, value in record.items()}
        diagnosis_id = normalized.get("diagnosis_id", "")
        patient_id = normalized.get("patient_id", "")
        row_errors = _required_errors(
            row_number=row_number,
            record=record,
            normalized=normalized,
            columns=DIAGNOSIS_COLUMNS,
            required_values=DIAGNOSIS_COLUMNS,
            entity_id=diagnosis_id,
            patient_id=patient_id,
        )
        duplicate_error = _unique_error(
            row_number=row_number,
            entity_id=diagnosis_id,
            patient_id=patient_id,
            field="diagnosis_id",
            seen_ids=seen_ids,
        )
        if duplicate_error is not None:
            row_errors.append(duplicate_error)

        code_system = normalized.get("code_system", "")
        if code_system and code_system not in ALLOWED_CODE_SYSTEMS:
            row_errors.append(
                EntityValidationError(
                    row_number,
                    diagnosis_id,
                    patient_id,
                    "code_system",
                    "allowed_values",
                    "code_system must be ICD10 or SNOMED",
                    code_system,
                )
            )

        diagnosis_datetime = normalized.get("diagnosis_datetime", "")
        if diagnosis_datetime:
            try:
                _parse_iso_datetime(diagnosis_datetime)
            except ValueError:
                row_errors.append(
                    EntityValidationError(
                        row_number,
                        diagnosis_id,
                        patient_id,
                        "diagnosis_datetime",
                        "iso_datetime",
                        "diagnosis_datetime must be an ISO 8601 datetime with timezone",
                        diagnosis_datetime,
                    )
                )

        if row_errors:
            invalid.append(record)
            errors.extend(row_errors)
        else:
            valid.append(normalized)

    return EntityValidationResult(tuple(valid), tuple(invalid), tuple(errors))


def validate_observation_records(
    records: Sequence[Mapping[str, str]],
) -> EntityValidationResult:
    """Validate supported measurements, units, plausible ranges, and timestamps."""
    valid: list[ClinicalRecord] = []
    invalid: list[ClinicalRecord] = []
    errors: list[EntityValidationError] = []
    seen_ids: set[str] = set()

    for row_number, source_record in enumerate(records, start=2):
        record = dict(source_record)
        normalized = {key: value.strip() for key, value in record.items()}
        observation_id = normalized.get("observation_id", "")
        patient_id = normalized.get("patient_id", "")
        row_errors = _required_errors(
            row_number=row_number,
            record=record,
            normalized=normalized,
            columns=OBSERVATION_COLUMNS,
            required_values=OBSERVATION_COLUMNS,
            entity_id=observation_id,
            patient_id=patient_id,
        )
        duplicate_error = _unique_error(
            row_number=row_number,
            entity_id=observation_id,
            patient_id=patient_id,
            field="observation_id",
            seen_ids=seen_ids,
        )
        if duplicate_error is not None:
            row_errors.append(duplicate_error)

        observation_code = normalized.get("observation_code", "")
        rule = OBSERVATION_RULES.get(observation_code)
        if observation_code and rule is None:
            row_errors.append(
                EntityValidationError(
                    row_number,
                    observation_id,
                    patient_id,
                    "observation_code",
                    "allowed_values",
                    "Unsupported observation_code",
                    observation_code,
                )
            )

        numeric_text = normalized.get("value_numeric", "")
        numeric_value: float | None = None
        if numeric_text:
            try:
                numeric_value = float(numeric_text)
            except ValueError:
                row_errors.append(
                    EntityValidationError(
                        row_number,
                        observation_id,
                        patient_id,
                        "value_numeric",
                        "numeric",
                        "value_numeric must be a finite number",
                        numeric_text,
                    )
                )
            else:
                if not math.isfinite(numeric_value):
                    row_errors.append(
                        EntityValidationError(
                            row_number,
                            observation_id,
                            patient_id,
                            "value_numeric",
                            "numeric",
                            "value_numeric must be a finite number",
                            numeric_text,
                        )
                    )

        if rule is not None:
            expected_unit, minimum, maximum = rule
            unit = normalized.get("unit", "")
            if unit and unit != expected_unit:
                row_errors.append(
                    EntityValidationError(
                        row_number,
                        observation_id,
                        patient_id,
                        "unit",
                        "unit_consistency",
                        f"{observation_code} must use {expected_unit}",
                        unit,
                    )
                )
            if numeric_value is not None and math.isfinite(numeric_value):
                if not minimum <= numeric_value <= maximum:
                    row_errors.append(
                        EntityValidationError(
                            row_number,
                            observation_id,
                            patient_id,
                            "value_numeric",
                            "plausible_range",
                            f"{observation_code} must be between {minimum:g} and {maximum:g}",
                            numeric_text,
                        )
                    )

        observed_at = normalized.get("observed_at", "")
        if observed_at:
            try:
                _parse_iso_datetime(observed_at)
            except ValueError:
                row_errors.append(
                    EntityValidationError(
                        row_number,
                        observation_id,
                        patient_id,
                        "observed_at",
                        "iso_datetime",
                        "observed_at must be an ISO 8601 datetime with timezone",
                        observed_at,
                    )
                )

        if row_errors:
            invalid.append(record)
            errors.extend(row_errors)
        else:
            valid.append(normalized)

    return EntityValidationResult(tuple(valid), tuple(invalid), tuple(errors))
