from pathlib import Path

import pytest

from clinical_data_platform.ingestion import DatasetReadError, read_csv_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATASET = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"


def test_patient_dataset_can_be_read() -> None:
    records = read_csv_records(SAMPLE_DATASET)

    assert len(records) == 8
    assert records[0]["patient_id"] == "P001"


def test_missing_dataset_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError, match="Dataset not found"):
        read_csv_records(Path("missing.csv"))


def test_non_csv_dataset_is_rejected(tmp_path: Path) -> None:
    dataset = tmp_path / "patients.txt"
    dataset.write_text("patient_id\nP001\n", encoding="utf-8")

    with pytest.raises(DatasetReadError, match="Expected a CSV file"):
        read_csv_records(dataset)


def test_rows_with_more_values_than_headers_are_rejected(tmp_path: Path) -> None:
    dataset = tmp_path / "malformed.csv"
    dataset.write_text("patient_id,birth_date\nP001,2000-01-01,extra\n", encoding="utf-8")

    with pytest.raises(DatasetReadError, match="more values"):
        read_csv_records(dataset)
