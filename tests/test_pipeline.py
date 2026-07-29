import csv
import json
from datetime import date
from pathlib import Path

from clinical_data_platform.pipeline import run_patient_validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATASET = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"


def _count_csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as file:
        return sum(1 for _ in csv.DictReader(file))


def test_pipeline_writes_quality_outputs(tmp_path: Path) -> None:
    summary = run_patient_validation(
        SAMPLE_DATASET,
        tmp_path,
        reference_date=date(2026, 7, 29),
    )

    assert summary.rows_received == 8
    assert summary.rows_valid == 5
    assert summary.rows_invalid == 3
    assert summary.validation_errors == 3
    assert _count_csv_rows(summary.valid_records_path) == 5
    assert _count_csv_rows(summary.invalid_records_path) == 3
    assert _count_csv_rows(summary.validation_errors_path) == 3

    report = json.loads(summary.quality_report_path.read_text(encoding="utf-8"))

    assert report["dataset"] == "patients"
    assert report["rows_received"] == 8
    assert report["rows_valid"] == 5
    assert report["rows_invalid"] == 3
    assert report["validation_errors"] == 3
    assert report["errors_by_rule"] == {
        "allowed_values": 1,
        "not_in_future": 1,
        "temporal_consistency": 1,
    }
    assert len(report["input_sha256"]) == 64
