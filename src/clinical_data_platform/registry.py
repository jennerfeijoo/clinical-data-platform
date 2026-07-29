"""Registry of persistence behavior for contract-defined clinical datasets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from clinical_data_platform.contract import (
    ContractDefinitionError,
    DatasetContract,
    contract_names,
    load_contract,
)
from clinical_data_platform.models import ClinicalRecord

RowBuilder = Callable[
    [list[ClinicalRecord], UUID, str],
    list[tuple[object, ...]],
]


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    """Runtime behavior that cannot be represented safely in a data contract."""

    name: str
    row_builder: RowBuilder
    upsert_sql: str

    @property
    def contract(self) -> DatasetContract:
        """Return the active executable contract for this dataset."""
        return load_contract(self.name)

    @property
    def columns(self) -> tuple[str, ...]:
        """Expose contract columns for output generation and inspection."""
        return self.contract.column_names

    @property
    def id_column(self) -> str:
        """Expose the primary key declared by the active contract."""
        return self.contract.primary_key


def _optional_datetime(value: str) -> datetime | None:
    stripped = value.strip()
    return datetime.fromisoformat(stripped) if stripped else None


def _optional_float(value: str) -> float | None:
    stripped = value.strip()
    return float(stripped) if stripped else None


def _optional_text(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


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
            record["encounter_id"].strip(),
            record["patient_id"].strip(),
            record["encounter_type"].strip(),
            datetime.fromisoformat(record["start_datetime"].strip()),
            datetime.fromisoformat(record["end_datetime"].strip()),
            record["source_system"].strip(),
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
            record["diagnosis_id"].strip(),
            record["patient_id"].strip(),
            record["encounter_id"].strip(),
            record["code_system"].strip(),
            record["diagnosis_code"].strip(),
            datetime.fromisoformat(record["diagnosis_datetime"].strip()),
            record["source_system"].strip(),
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
            record["observation_id"].strip(),
            record["patient_id"].strip(),
            record["encounter_id"].strip(),
            record["observation_code"].strip(),
            float(record["value_numeric"].strip()),
            record["unit"].strip(),
            datetime.fromisoformat(record["observed_at"].strip()),
            record["source_system"].strip(),
            run_id,
            source_sha256,
        )
        for record in records
    ]


def _medication_rows(
    records: list[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> list[tuple[object, ...]]:
    return [
        (
            record["medication_id"].strip(),
            record["patient_id"].strip(),
            record["encounter_id"].strip(),
            record["code_system"].strip(),
            record["medication_code"].strip(),
            record["status"].strip(),
            datetime.fromisoformat(record["start_datetime"].strip()),
            _optional_datetime(record["end_datetime"]),
            _optional_float(record["dose_value"]),
            _optional_text(record["dose_unit"]),
            _optional_text(record["route"]),
            record["source_system"].strip(),
            run_id,
            source_sha256,
        )
        for record in records
    ]


def _procedure_rows(
    records: list[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> list[tuple[object, ...]]:
    return [
        (
            record["procedure_id"].strip(),
            record["patient_id"].strip(),
            record["encounter_id"].strip(),
            record["code_system"].strip(),
            record["procedure_code"].strip(),
            datetime.fromisoformat(record["procedure_datetime"].strip()),
            record["status"].strip(),
            record["source_system"].strip(),
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

MEDICATION_UPSERT_SQL = """
    INSERT INTO clinical.medications (
        medication_id, patient_id, encounter_id, code_system,
        medication_code, status, start_datetime, end_datetime,
        dose_value, dose_unit, route, source_system,
        source_run_id, source_sha256
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (medication_id) DO UPDATE SET
        patient_id = EXCLUDED.patient_id,
        encounter_id = EXCLUDED.encounter_id,
        code_system = EXCLUDED.code_system,
        medication_code = EXCLUDED.medication_code,
        status = EXCLUDED.status,
        start_datetime = EXCLUDED.start_datetime,
        end_datetime = EXCLUDED.end_datetime,
        dose_value = EXCLUDED.dose_value,
        dose_unit = EXCLUDED.dose_unit,
        route = EXCLUDED.route,
        source_system = EXCLUDED.source_system,
        source_run_id = EXCLUDED.source_run_id,
        source_sha256 = EXCLUDED.source_sha256,
        loaded_at = CURRENT_TIMESTAMP
"""

PROCEDURE_UPSERT_SQL = """
    INSERT INTO clinical.procedures (
        procedure_id, patient_id, encounter_id, code_system,
        procedure_code, procedure_datetime, status, source_system,
        source_run_id, source_sha256
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (procedure_id) DO UPDATE SET
        patient_id = EXCLUDED.patient_id,
        encounter_id = EXCLUDED.encounter_id,
        code_system = EXCLUDED.code_system,
        procedure_code = EXCLUDED.procedure_code,
        procedure_datetime = EXCLUDED.procedure_datetime,
        status = EXCLUDED.status,
        source_system = EXCLUDED.source_system,
        source_run_id = EXCLUDED.source_run_id,
        source_sha256 = EXCLUDED.source_sha256,
        loaded_at = CURRENT_TIMESTAMP
"""


DATASET_REGISTRY: dict[str, DatasetDefinition] = {
    "patients": DatasetDefinition(
        name="patients",
        row_builder=_patient_rows,
        upsert_sql=PATIENT_UPSERT_SQL,
    ),
    "encounters": DatasetDefinition(
        name="encounters",
        row_builder=_encounter_rows,
        upsert_sql=ENCOUNTER_UPSERT_SQL,
    ),
    "diagnoses": DatasetDefinition(
        name="diagnoses",
        row_builder=_diagnosis_rows,
        upsert_sql=DIAGNOSIS_UPSERT_SQL,
    ),
    "observations": DatasetDefinition(
        name="observations",
        row_builder=_observation_rows,
        upsert_sql=OBSERVATION_UPSERT_SQL,
    ),
    "medications": DatasetDefinition(
        name="medications",
        row_builder=_medication_rows,
        upsert_sql=MEDICATION_UPSERT_SQL,
    ),
    "procedures": DatasetDefinition(
        name="procedures",
        row_builder=_procedure_rows,
        upsert_sql=PROCEDURE_UPSERT_SQL,
    ),
}


def dataset_names() -> tuple[str, ...]:
    """Return datasets only when runtime behavior and contract manifest agree."""
    registry_names = tuple(DATASET_REGISTRY)
    manifest_names = contract_names()
    if registry_names != manifest_names:
        raise ContractDefinitionError(
            "Dataset registry order and contract manifest entries must match exactly."
        )
    return registry_names


def get_dataset_definition(dataset: str) -> DatasetDefinition:
    """Return one registered dataset or raise a descriptive error."""
    try:
        definition = DATASET_REGISTRY[dataset]
    except KeyError as exc:
        supported = ", ".join(dataset_names())
        raise ValueError(
            f"Unsupported dataset {dataset!r}; expected one of: {supported}"
        ) from exc
    if definition.contract.name != definition.name:
        raise ContractDefinitionError(
            f"Runtime definition {definition.name!r} does not match its contract."
        )
    return definition
