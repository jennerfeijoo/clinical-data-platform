import csv
import json
from datetime import date
from pathlib import Path

import pytest

from clinical_data_platform.pipeline import run_dataset_validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"


def _count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as file:
        return sum(1 for _ in csv.DictReader(file))


@pytest.mark.parametrize(
    ("dataset", "received", "valid", "invalid", "errors"),
    [
        ("patients", 8, 5, 3, 3),
        ("encounters", 8, 7, 1, 1),
        ("diagnoses", 7, 6, 1, 2),
        ("observations", 14, 13, 1, 1),
    ],
)
def test_generic_pipeline_writes_consistent_contract_governed_outputs(
    tmp_path: Path,
    dataset: str,
    received: int,
    valid: int,
    invalid: int,
    errors: int,
) -> None:
    output_directory = tmp_path / dataset
    summary = run_dataset_validation(
        dataset,
        SAMPLE_DIRECTORY / f"{dataset}.csv",
        output_directory,
        reference_date=date(2026, 7, 29),
    )

    assert summary.dataset == dataset
    assert summary.contract_version == "1.0.0"
    assert len(summary.contract_sha256) == 64
    assert summary.rows_received == received
    assert summary.rows_valid == valid
    assert summary.rows_invalid == invalid
    assert summary.validation_errors == errors
    assert _count_csv_rows(summary.valid_records_path) == valid
    assert _count_csv_rows(summary.invalid_records_path) == invalid
    assert _count_csv_rows(summary.validation_errors_path) == errors

    report = json.loads(summary.quality_report_path.read_text(encoding="utf-8"))
    assert report["dataset"] == dataset
    assert report["contract_version"] == "1.0.0"
    assert report["contract_sha256"] == summary.contract_sha256
    assert report["contract_path"].endswith("v1.0.0.toml")
    assert report["rows_received"] == received
    assert report["rows_valid"] == valid
    assert report["rows_invalid"] == invalid
    assert report["validation_errors"] == errors
    assert len(report["input_sha256"]) == 64


def test_patient_rules_are_executed_from_contract(tmp_path: Path) -> None:
    summary = run_dataset_validation(
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        tmp_path,
        reference_date=date(2026, 7, 29),
    )
    report = json.loads(summary.quality_report_path.read_text(encoding="utf-8"))

    assert report["errors_by_rule"] == {
        "allowed_values": 1,
        "not_in_future": 1,
        "temporal_consistency": 1,
    }


def test_generic_pipeline_rejects_unknown_dataset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported dataset"):
        run_dataset_validation(
            "medications",
            SAMPLE_DIRECTORY / "observations.csv",
            tmp_path,
        )
