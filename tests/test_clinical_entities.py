from pathlib import Path

from clinical_data_platform.clinical_entities import (
    validate_diagnosis_records,
    validate_encounter_records,
    validate_observation_records,
)
from clinical_data_platform.ingestion import read_csv_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"


def test_encounter_validation_rejects_reversed_time_interval() -> None:
    result = validate_encounter_records(
        read_csv_records(SAMPLE_DIRECTORY / "encounters.csv")
    )

    assert result.rows_received == 8
    assert len(result.valid_records) == 7
    assert len(result.invalid_records) == 1
    assert {error.rule for error in result.errors} == {"temporal_consistency"}
    assert result.errors[0].entity_id == "E008"


def test_diagnosis_validation_rejects_unsupported_empty_code() -> None:
    result = validate_diagnosis_records(
        read_csv_records(SAMPLE_DIRECTORY / "diagnoses.csv")
    )

    assert result.rows_received == 7
    assert len(result.valid_records) == 6
    assert len(result.invalid_records) == 1
    assert {error.rule for error in result.errors} == {
        "allowed_values",
        "required_value",
    }
    assert {error.entity_id for error in result.errors} == {"D007"}


def test_observation_validation_rejects_implausible_blood_pressure() -> None:
    result = validate_observation_records(
        read_csv_records(SAMPLE_DIRECTORY / "observations.csv")
    )

    assert result.rows_received == 14
    assert len(result.valid_records) == 13
    assert len(result.invalid_records) == 1
    assert {error.rule for error in result.errors} == {"plausible_range"}
    assert result.errors[0].entity_id == "O014"
