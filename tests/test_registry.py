import pytest

from clinical_data_platform.contract import contract_names, load_contract
from clinical_data_platform.registry import dataset_names, get_dataset_definition


def test_registry_contains_every_active_contract() -> None:
    expected = (
        "patients",
        "encounters",
        "diagnoses",
        "observations",
        "medications",
        "procedures",
    )

    assert dataset_names() == expected
    assert contract_names() == expected
    assert get_dataset_definition("patients").id_column == "patient_id"
    assert get_dataset_definition("observations").id_column == "observation_id"
    assert get_dataset_definition("medications").id_column == "medication_id"
    assert get_dataset_definition("procedures").id_column == "procedure_id"


def test_registry_uses_contract_columns_as_source_of_truth() -> None:
    observations = get_dataset_definition("observations")
    contract = load_contract("observations")

    assert observations.columns == contract.column_names
    assert observations.id_column == contract.primary_key
    assert contract.version == "1.0.0"


def test_registry_reports_unknown_dataset() -> None:
    with pytest.raises(ValueError, match="Unsupported dataset"):
        get_dataset_definition("allergies")
