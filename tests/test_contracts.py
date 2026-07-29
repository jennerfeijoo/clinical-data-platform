from datetime import date
from pathlib import Path

from clinical_data_platform.contract import (
    contract_names,
    load_contract,
    validate_all_contracts,
    validate_records_against_contract,
)
from clinical_data_platform.ingestion import read_csv_records

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"


def test_manifest_loads_every_active_versioned_contract() -> None:
    contracts = validate_all_contracts()

    assert contract_names() == (
        "patients",
        "encounters",
        "diagnoses",
        "observations",
        "medications",
        "procedures",
    )
    assert [contract.version for contract in contracts] == ["1.0.0"] * 6
    assert all(len(contract.sha256) == 64 for contract in contracts)
    assert all(contract.resource_path.endswith("v1.0.0.toml") for contract in contracts)


def test_patient_contract_executes_categorical_and_temporal_rules() -> None:
    result = validate_records_against_contract(
        read_csv_records(SAMPLE_DIRECTORY / "patients.csv"),
        load_contract("patients"),
        reference_date=date(2026, 7, 29),
    )

    assert result.rows_received == 8
    assert len(result.valid_records) == 5
    assert len(result.invalid_records) == 3
    assert {error.rule for error in result.errors} == {
        "allowed_values",
        "not_in_future",
        "temporal_consistency",
    }


def test_diagnosis_contract_executes_required_and_vocabulary_rules() -> None:
    result = validate_records_against_contract(
        read_csv_records(SAMPLE_DIRECTORY / "diagnoses.csv"),
        load_contract("diagnoses"),
    )

    assert len(result.valid_records) == 6
    assert len(result.invalid_records) == 1
    assert {error.rule for error in result.errors} == {
        "allowed_values",
        "required_value",
    }
    assert {error.entity_id for error in result.errors} == {"D007"}


def test_observation_contract_executes_measurement_profiles() -> None:
    result = validate_records_against_contract(
        read_csv_records(SAMPLE_DIRECTORY / "observations.csv"),
        load_contract("observations"),
    )

    assert len(result.valid_records) == 13
    assert len(result.invalid_records) == 1
    assert {error.rule for error in result.errors} == {"plausible_range"}
    assert result.errors[0].entity_id == "O014"


def test_medication_contract_executes_optional_and_temporal_rules() -> None:
    result = validate_records_against_contract(
        read_csv_records(SAMPLE_DIRECTORY / "medications.csv"),
        load_contract("medications"),
        reference_date=date(2026, 7, 29),
    )

    assert result.rows_received == 7
    assert len(result.valid_records) == 6
    assert len(result.invalid_records) == 1
    assert {error.rule for error in result.errors} == {"temporal_consistency"}
    assert result.errors[0].entity_id == "M007"


def test_procedure_contract_executes_vocabulary_rules() -> None:
    result = validate_records_against_contract(
        read_csv_records(SAMPLE_DIRECTORY / "procedures.csv"),
        load_contract("procedures"),
        reference_date=date(2026, 7, 29),
    )

    assert result.rows_received == 7
    assert len(result.valid_records) == 6
    assert len(result.invalid_records) == 1
    assert {error.rule for error in result.errors} == {"allowed_values"}
    assert result.errors[0].entity_id == "PR007"


def test_contract_rejects_an_unexpected_column() -> None:
    record = {
        "patient_id": "P100",
        "sex_at_birth": "F",
        "birth_date": "2000-01-01",
        "death_date": "",
        "source_system": "synthetic_ehr",
        "secret_note": "not declared",
    }

    result = validate_records_against_contract(
        [record],
        load_contract("patients"),
        reference_date=date(2026, 7, 29),
    )

    assert len(result.invalid_records) == 1
    assert result.errors[0].rule == "unexpected_column"
    assert result.errors[0].field == "secret_note"
