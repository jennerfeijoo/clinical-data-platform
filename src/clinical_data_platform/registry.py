"""Registry of persistence behavior for contract-defined clinical datasets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from clinical_data_platform.bulk import CopyMergePlan
from clinical_data_platform.contract import (
    ContractDefinitionError,
    DatasetContract,
    contract_names,
    load_contract,
)
from clinical_data_platform.models import ClinicalRecord

RowBuilder = Callable[
    [Iterable[ClinicalRecord], UUID, str],
    Iterator[tuple[object, ...]],
]


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    """Runtime behavior that cannot be represented safely in a data contract."""

    name: str
    row_builder: RowBuilder
    copy_plan: CopyMergePlan

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
    records: Iterable[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> Iterator[tuple[object, ...]]:
    for record in records:
        death_date_text = record["death_date"].strip()
        yield (
            record["patient_id"].strip(),
            record["sex_at_birth"].strip(),
            date.fromisoformat(record["birth_date"].strip()),
            date.fromisoformat(death_date_text) if death_date_text else None,
            record["source_system"].strip(),
            run_id,
            source_sha256,
        )


def _encounter_rows(
    records: Iterable[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> Iterator[tuple[object, ...]]:
    for record in records:
        yield (
            record["encounter_id"].strip(),
            record["patient_id"].strip(),
            record["encounter_type"].strip(),
            datetime.fromisoformat(record["start_datetime"].strip()),
            datetime.fromisoformat(record["end_datetime"].strip()),
            record["source_system"].strip(),
            run_id,
            source_sha256,
        )


def _diagnosis_rows(
    records: Iterable[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> Iterator[tuple[object, ...]]:
    for record in records:
        yield (
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


def _observation_rows(
    records: Iterable[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> Iterator[tuple[object, ...]]:
    for record in records:
        yield (
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


def _medication_rows(
    records: Iterable[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> Iterator[tuple[object, ...]]:
    for record in records:
        yield (
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


def _procedure_rows(
    records: Iterable[ClinicalRecord],
    run_id: UUID,
    source_sha256: str,
) -> Iterator[tuple[object, ...]]:
    for record in records:
        yield (
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


PATIENT_COPY_PLAN = CopyMergePlan(
    schema="clinical",
    table="patients",
    columns=(
        "patient_id",
        "sex_at_birth",
        "birth_date",
        "death_date",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    conflict_columns=("patient_id",),
    update_columns=(
        "sex_at_birth",
        "birth_date",
        "death_date",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    touch_loaded_at=True,
)

ENCOUNTER_COPY_PLAN = CopyMergePlan(
    schema="clinical",
    table="encounters",
    columns=(
        "encounter_id",
        "patient_id",
        "encounter_type",
        "start_datetime",
        "end_datetime",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    conflict_columns=("encounter_id",),
    update_columns=(
        "patient_id",
        "encounter_type",
        "start_datetime",
        "end_datetime",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    touch_loaded_at=True,
)

DIAGNOSIS_COPY_PLAN = CopyMergePlan(
    schema="clinical",
    table="diagnoses",
    columns=(
        "diagnosis_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "diagnosis_code",
        "diagnosis_datetime",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    conflict_columns=("diagnosis_id",),
    update_columns=(
        "patient_id",
        "encounter_id",
        "code_system",
        "diagnosis_code",
        "diagnosis_datetime",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    touch_loaded_at=True,
)

OBSERVATION_COPY_PLAN = CopyMergePlan(
    schema="clinical",
    table="observations",
    columns=(
        "observation_id",
        "patient_id",
        "encounter_id",
        "observation_code",
        "value_numeric",
        "unit",
        "observed_at",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    conflict_columns=("observation_id",),
    update_columns=(
        "patient_id",
        "encounter_id",
        "observation_code",
        "value_numeric",
        "unit",
        "observed_at",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    touch_loaded_at=True,
)

MEDICATION_COPY_PLAN = CopyMergePlan(
    schema="clinical",
    table="medications",
    columns=(
        "medication_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "medication_code",
        "status",
        "start_datetime",
        "end_datetime",
        "dose_value",
        "dose_unit",
        "route",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    conflict_columns=("medication_id",),
    update_columns=(
        "patient_id",
        "encounter_id",
        "code_system",
        "medication_code",
        "status",
        "start_datetime",
        "end_datetime",
        "dose_value",
        "dose_unit",
        "route",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    touch_loaded_at=True,
)

PROCEDURE_COPY_PLAN = CopyMergePlan(
    schema="clinical",
    table="procedures",
    columns=(
        "procedure_id",
        "patient_id",
        "encounter_id",
        "code_system",
        "procedure_code",
        "procedure_datetime",
        "status",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    conflict_columns=("procedure_id",),
    update_columns=(
        "patient_id",
        "encounter_id",
        "code_system",
        "procedure_code",
        "procedure_datetime",
        "status",
        "source_system",
        "source_run_id",
        "source_sha256",
    ),
    touch_loaded_at=True,
)


DATASET_REGISTRY: dict[str, DatasetDefinition] = {
    "patients": DatasetDefinition(
        name="patients",
        row_builder=_patient_rows,
        copy_plan=PATIENT_COPY_PLAN,
    ),
    "encounters": DatasetDefinition(
        name="encounters",
        row_builder=_encounter_rows,
        copy_plan=ENCOUNTER_COPY_PLAN,
    ),
    "diagnoses": DatasetDefinition(
        name="diagnoses",
        row_builder=_diagnosis_rows,
        copy_plan=DIAGNOSIS_COPY_PLAN,
    ),
    "observations": DatasetDefinition(
        name="observations",
        row_builder=_observation_rows,
        copy_plan=OBSERVATION_COPY_PLAN,
    ),
    "medications": DatasetDefinition(
        name="medications",
        row_builder=_medication_rows,
        copy_plan=MEDICATION_COPY_PLAN,
    ),
    "procedures": DatasetDefinition(
        name="procedures",
        row_builder=_procedure_rows,
        copy_plan=PROCEDURE_COPY_PLAN,
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
