import csv
import json
from datetime import date
from pathlib import Path

import pytest

from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.raw import verify_raw_receipt

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
        ("medications", 7, 6, 1, 1),
        ("procedures", 7, 6, 1, 1),
    ],
)
def test_pipeline_captures_raw_and_writes_consistent_contract_outputs(
    tmp_path: Path,
    dataset: str,
    received: int,
    valid: int,
    invalid: int,
    errors: int,
) -> None:
    output_directory = tmp_path / "processed" / dataset
    raw_root = tmp_path / "raw"
    summary = run_dataset_validation(
        dataset,
        SAMPLE_DIRECTORY / f"{dataset}.csv",
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )

    assert summary.dataset == dataset
    assert summary.contract_version == "1.0.0"
    assert len(summary.contract_sha256) == 64
    assert len(summary.raw_manifest_sha256) == 64
    assert summary.raw_size_bytes > 0
    assert summary.rows_received == received
    assert summary.rows_valid == valid
    assert summary.rows_invalid == invalid
    assert summary.validation_errors == errors
    assert _count_csv_rows(summary.valid_records_path) == valid
    assert _count_csv_rows(summary.invalid_records_path) == invalid
    assert _count_csv_rows(summary.validation_errors_path) == errors

    receipt = verify_raw_receipt(raw_root, summary.raw_manifest_relative_path)
    assert receipt.receipt_id == summary.raw_receipt_id
    assert receipt.sha256 == summary.source_sha256
    assert receipt.object_relative_path == summary.raw_object_relative_path

    report = json.loads(summary.quality_report_path.read_text(encoding="utf-8"))
    assert report["dataset"] == dataset
    assert report["contract_version"] == "1.0.0"
    assert report["contract_sha256"] == summary.contract_sha256
    assert report["contract_path"].endswith("v1.0.0.toml")
    assert report["raw_storage_version"] == "1.0.0"
    assert report["raw_receipt_id"] == str(summary.raw_receipt_id)
    assert report["raw_manifest_path"] == summary.raw_manifest_relative_path
    assert report["raw_manifest_sha256"] == summary.raw_manifest_sha256
    assert report["raw_object_path"] == summary.raw_object_relative_path
    assert report["raw_size_bytes"] == summary.raw_size_bytes
    assert report["rows_received"] == received
    assert report["rows_valid"] == valid
    assert report["rows_invalid"] == invalid
    assert report["validation_errors"] == errors
    assert len(report["input_sha256"]) == 64


def test_patient_rules_are_executed_from_contract(tmp_path: Path) -> None:
    summary = run_dataset_validation(
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        tmp_path / "processed",
        raw_root=tmp_path / "raw",
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
            "allergies",
            SAMPLE_DIRECTORY / "observations.csv",
            tmp_path / "processed",
            raw_root=tmp_path / "raw",
        )
