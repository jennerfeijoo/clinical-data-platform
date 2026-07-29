"""Registry of supported clinical datasets and their executable behavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from clinical_data_platform.clinical_entities import (
    DIAGNOSIS_COLUMNS,
    ENCOUNTER_COLUMNS,
    OBSERVATION_COLUMNS,
    EntityValidationResult,
    validate_diagnosis_records,
    validate_encounter_records,
    validate_observation_records,
)
from clinical_data_platform.models import ClinicalRecord, ValidationError, ValidationResult
from clinical_data_platform.validation import PATIENT_COLUMNS, validate_patient_records

Validator = Callable[[Sequence[Mapping[str, str]], date], ValidationResult]
RowBuilder = Callable[
    [list[ClinicalRecord], UUID, str],
    list[tuple[object, ...]],
]


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    """Executable definition of one supported clinical dataset."""

    name: str
    columns: tuple[str, ...]
    id_column: str
    validator: Validator
    row_builder: RowBuilder
    upsert_sql: str


def _validate_patients(
    records: Sequence[Mapping[str, str]],
    reference_date: date,
) -> ValidationResult:
    result = validate_patient_records(records, reference_date=reference_date)
    errors = tuple(
        ValidationError(
            row_number=error.row_number,
            entity_id=error.patient_id,
            patient_id=error.patient_id,
            field=error.field,
            rule=error.rule,
            message=error.message,
            value=error.value,
        )
        for error in result.errors
    )
    return ValidationResult(result.valid_records, result.invalid_records, errors)


def _normalize_entity_result(result: EntityValidationResult) -> ValidationResult:
    errors = tuple(
        ValidationError(
            row_number=error.row_number,
            entity_id=error.entity_id,
            patient_id=error.patient_id,
            field=error.field,
            rule=error.rule,
            message=error.message,
            value=error.value,
        )
        for error in result.errors
    )
    return ValidationResult(result.valid_records, result.invalid_records, errors)


def _validate_encounters(
    records: Sequence[Mapping[str, str]],
    reference_date: date,
) -> ValidationResult:
    del reference_date
    return _normalize_entity_result(validate_encounter_records(records))


def _validate_diagnoses(
    records: Sequence[Mapping[str, str]],
    reference_date: date,
) -> ValidationResult:
    del reference_date
    return _normalize_entity_result(validate_diagnosis_records(records))


def _validate_observations(
    records: Sequence[Mapping[str, str]],
    reference_date: date,
) -> ValidationResult:
    del reference_date
    return _normalize_entity_result(validate_observation_records(records))


def _patient_rows(
    records: list[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for record in records:
        death_date_text = record["death_date"].strip()
        rows.append(
            (
                record["patient_id"].strip(),
                record["sex_at_birth"].strip(),
                date.fromisoformat(record["birth_date"].strip()),
                date.fromisoformat(death_date_text) if death_date_text else None,
                record["source_system"].strip(),
                run_id,
                source_sha256,
            )
        )
    return rows


def _encounter_rows(
    records: list[ClinicalRecord],
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


def _diagnosis_rows(
    records: list[ClinicalRecord],
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


def _observation_rows(
    records: list[ClinicalRecord],
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


PATIENT_UPSERT_SQL = """
    INSERT INTO clinical.patients (
        patient_id, sex_at_birth, birth_date, death_date, source_system,
        source_run_id, source_sha256
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (patient_id) DO UPDATE SET
        sex_at_birth = EXCLUDED.sex_at_birth,
        birth_date = EXCLUDED.birth_date,
        death_date = EXCLUDED.death_date,
        source_system = EXCLUDED.source_system,
        source_run_id = EXCLUDED.source_run_id,
        source_sha256 = EXCLUDED.source_sha256,
        loaded_at = CURRENT_TIMESTAMP
"""

ENCOUNTER_UPSERT_SQL = """
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

DIAGNOSIS_UPSERT_SQL = """
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

OBSERVATION_UPSERT_SQL = """
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


DATASET_REGISTRY: dict[str, DatasetDefinition] = {
    "patients": DatasetDefinition(
        name="patients",
        columns=PATIENT_COLUMNS,
        id_column="patient_id",
        validator=_validate_patients,
        row_builder=_patient_rows,
        upsert_sql=PATIENT_UPSERT_SQL,
    ),
    "encounters": DatasetDefinition(
        name="encounters",
        columns=ENCOUNTER_COLUMNS,
        id_column="encounter_id",
        validator=_validate_encounters,
        row_builder=_encounter_rows,
        upsert_sql=ENCOUNTER_UPSERT_SQL,
    ),
    "diagnoses": DatasetDefinition(
        name="diagnoses",
        columns=DIAGNOSIS_COLUMNS,
        id_column="diagnosis_id",
        validator=_validate_diagnoses,
        row_builder=_diagnosis_rows,
        upsert_sql=DIAGNOSIS_UPSERT_SQL,
    ),
    "observations": DatasetDefinition(
        name="observations",
        columns=OBSERVATION_COLUMNS,
        id_column="observation_id",
        validator=_validate_observations,
        row_builder=_observation_rows,
        upsert_sql=OBSERVATION_UPSERT_SQL,
    ),
}


def dataset_names() -> tuple[str, ...]:
    """Return supported dataset names in deterministic order."""
    return tuple(DATASET_REGISTRY)


def get_dataset_definition(dataset: str) -> DatasetDefinition:
    """Return one registered dataset or raise a descriptive error."""
    try:
        return DATASET_REGISTRY[dataset]
    except KeyError as exc:
        supported = ", ".join(dataset_names())
        raise ValueError(
            f"Unsupported dataset {dataset!r}; expected one of: {supported}"
        ) from exc
