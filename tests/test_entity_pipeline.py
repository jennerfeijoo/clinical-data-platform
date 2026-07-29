import json
from datetime import date
from pathlib import Path

import pytest

from clinical_data_platform.entity_pipeline import run_entity_validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"


@pytest.mark.parametrize(
    ("dataset", "expected_valid", "expected_invalid", "expected_errors"),
    [
        ("encounters", 7, 1, 1),
        ("diagnoses", 6, 1, 2),
        ("observations", 13, 1, 1),
    ],
)
def test_entity_pipeline_writes_auditable_outputs(
    tmp_path: Path,
    dataset: str,
    expected_valid: int,
    expected_invalid: int,
    expected_errors: int,
) -> None:
    summary = run_entity_validation(
        dataset,
        SAMPLE_DIRECTORY / f"{dataset}.csv",
        tmp_path,
        reference_date=date(2026, 7, 29),
    )

    assert summary.rows_valid == expected_valid
    assert summary.rows_invalid == expected_invalid
    assert summary.validation_errors == expected_errors
    assert summary.valid_records_path.exists()
    assert summary.invalid_records_path.exists()
    assert summary.validation_errors_path.exists()

    report = json.loads(summary.quality_report_path.read_text(encoding="utf-8"))
    assert report["run_id"] == str(summary.run_id)
    assert report["dataset"] == dataset
    assert report["rows_valid"] == expected_valid
    assert len(report["input_sha256"]) == 64


def test_entity_pipeline_rejects_unknown_dataset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported dataset"):
        run_entity_validation(
            "medications",
            SAMPLE_DIRECTORY / "observations.csv",
            tmp_path,
        )
