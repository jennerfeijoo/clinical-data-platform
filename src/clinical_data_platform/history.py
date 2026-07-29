"""Explicit persistence semantics for current snapshots and immutable events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HistoryMode = Literal["scd2_snapshot", "immutable_event"]


@dataclass(frozen=True, slots=True)
class ClinicalHistoryPolicy:
    """Declared historical behavior for one registered clinical dataset."""

    dataset: str
    mode: HistoryMode
    identity_column: str
    current_table: str
    history_table: str | None
    duplicate_behavior: str
    conflicting_identity_behavior: str


CLINICAL_HISTORY_POLICIES: dict[str, ClinicalHistoryPolicy] = {
    "patients": ClinicalHistoryPolicy(
        dataset="patients",
        mode="scd2_snapshot",
        identity_column="patient_id",
        current_table="clinical.patients",
        history_table="clinical.patient_history",
        duplicate_behavior="refresh current-run lineage without creating a history version",
        conflicting_identity_behavior="close the current version and append a new SCD2 version",
    ),
    "encounters": ClinicalHistoryPolicy(
        dataset="encounters",
        mode="immutable_event",
        identity_column="encounter_id",
        current_table="clinical.encounters",
        history_table=None,
        duplicate_behavior="preserve the original event and lineage",
        conflicting_identity_behavior="reject the transaction",
    ),
    "diagnoses": ClinicalHistoryPolicy(
        dataset="diagnoses",
        mode="immutable_event",
        identity_column="diagnosis_id",
        current_table="clinical.diagnoses",
        history_table=None,
        duplicate_behavior="preserve the original event and lineage",
        conflicting_identity_behavior="reject the transaction",
    ),
    "observations": ClinicalHistoryPolicy(
        dataset="observations",
        mode="immutable_event",
        identity_column="observation_id",
        current_table="clinical.observations",
        history_table=None,
        duplicate_behavior="preserve the original event and lineage",
        conflicting_identity_behavior="reject the transaction",
    ),
}


def get_clinical_history_policy(dataset: str) -> ClinicalHistoryPolicy:
    """Return the declared history policy for a supported clinical dataset."""
    try:
        return CLINICAL_HISTORY_POLICIES[dataset]
    except KeyError as exc:
        supported = ", ".join(CLINICAL_HISTORY_POLICIES)
        raise ValueError(
            f"No clinical history policy for {dataset!r}; expected one of: {supported}"
        ) from exc
