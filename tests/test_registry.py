from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from clinical_data_platform.models import ValidationResult
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.registry import (
    DATASET_REGISTRY,
    DatasetDefinition,
    dataset_names,
    get_dataset_definition,
)


def test_registry_contains_every_supported_dataset() -> None:
    assert dataset_names() == (
        "patients",
        "encounters",
        "diagnoses",
        "observations",
    )
    assert get_dataset_definition("patients").id_column == "patient_id"
    assert get_dataset_definition("observations").id_column == "observation_id"


def test_registry_reports_unknown_dataset() -> None:
    with pytest.raises(ValueError, match="Unsupported dataset"):
        get_dataset_definition("medications")


def test_pipeline_accepts_new_registry_entry_without_code_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "labs.csv"
    source.write_text("lab_id,patient_id,value\nL001,P001,4.2\n", encoding="utf-8")

    def validate_labs(
        records: Sequence[Mapping[str, str]],
        reference_date: date,
    ) -> ValidationResult:
        del reference_date
        normalized = tuple(
            {key: value.strip() for key, value in record.items()} for record in records
        )
        return ValidationResult(normalized, (), ())

    def lab_rows(
        records: list[dict[str, str]],
        run_id: UUID,
        source_sha256: str,
    ) -> list[tuple[object, ...]]:
        del run_id, source_sha256
        return [(record["lab_id"], record["patient_id"], float(record["value"])) for record in records]

    definition = DatasetDefinition(
        name="labs",
        columns=("lab_id", "patient_id", "value"),
        id_column="lab_id",
        validator=validate_labs,
        row_builder=lab_rows,
        upsert_sql="SELECT 1",
    )
    monkeypatch.setitem(DATASET_REGISTRY, "labs", definition)

    summary = run_dataset_validation(
        "labs",
        source,
        tmp_path / "processed",
        reference_date=date(2026, 7, 29),
    )

    assert summary.dataset == "labs"
    assert summary.rows_valid == 1
    assert summary.rows_invalid == 0
