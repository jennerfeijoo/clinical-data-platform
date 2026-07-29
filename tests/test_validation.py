from datetime import date
from pathlib import Path

from clinical_data_platform.ingestion import read_csv_records
from clinical_data_platform.validation import validate_patient_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATASET = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"


def test_validation_separates_valid_and_invalid_records() -> None:
    result = validate_patient_records(
        read_csv_records(SAMPLE_DATASET),
        reference_date=date(2026, 7, 29),
    )

    assert result.rows_received == 8
    assert len(result.valid_records) == 5
    assert len(result.invalid_records) == 3
    assert len(result.errors) == 3


def test_validation_reports_expected_rules() -> None:
    result = validate_patient_records(
        read_csv_records(SAMPLE_DATASET),
        reference_date=date(2026, 7, 29),
    )

    errors_by_patient = {error.patient_id: error.rule for error in result.errors}

    assert errors_by_patient == {
        "P006": "not_in_future",
        "P007": "allowed_values",
        "P008": "temporal_consistency",
    }


def test_duplicate_patient_identifier_is_rejected() -> None:
    records = [
        {
            "patient_id": "P001",
            "sex_at_birth": "F",
            "birth_date": "2000-01-01",
            "death_date": "",
            "source_system": "synthetic_ehr",
        },
        {
            "patient_id": "P001",
            "sex_at_birth": "F",
            "birth_date": "2001-01-01",
            "death_date": "",
            "source_system": "synthetic_ehr",
        },
    ]

    result = validate_patient_records(records, reference_date=date(2026, 7, 29))

    assert len(result.valid_records) == 1
    assert len(result.invalid_records) == 1
    assert result.errors[0].rule == "unique"


def test_missing_required_value_is_reported() -> None:
    records = [
        {
            "patient_id": "P001",
            "sex_at_birth": "F",
            "birth_date": "",
            "death_date": "",
            "source_system": "synthetic_ehr",
        }
    ]

    result = validate_patient_records(records, reference_date=date(2026, 7, 29))

    assert len(result.invalid_records) == 1
    assert result.errors[0].field == "birth_date"
    assert result.errors[0].rule == "required_value"
