from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.database import (
    DatabaseConfigurationError,
    database_url_from_environment,
    persist_dataset_validation_outputs,
)
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATASET = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"


def test_database_url_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "postgresql://user:password@localhost:5432/database"
    monkeypatch.setenv("DATABASE_URL", expected)

    assert database_url_from_environment() == expected


def test_missing_database_url_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(DatabaseConfigurationError, match="DATABASE_URL is required"):
        database_url_from_environment()


@pytest.mark.integration
def test_registered_dataset_is_persisted_with_contract_lineage(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    validation_summary = run_dataset_validation(
        "patients",
        SAMPLE_DATASET,
        tmp_path,
        reference_date=date(2026, 7, 29),
    )
    connection = clean_database_connection
    migrate_database(connection)
    persistence_summary = persist_dataset_validation_outputs(
        connection,
        "patients",
        tmp_path,
    )

    assert persistence_summary.run_id == validation_summary.run_id
    assert persistence_summary.dataset == "patients"
    assert persistence_summary.contract_version == "1.0.0"
    assert persistence_summary.already_loaded is False
    assert persistence_summary.records_upserted == 5
    assert persistence_summary.validation_errors_inserted == 3

    run_row = connection.execute(
        """
        SELECT contract_version, contract_sha256, contract_path
        FROM audit.pipeline_runs
        WHERE run_id = %s
        """,
        (validation_summary.run_id,),
    ).fetchone()
    patient_count = connection.execute(
        "SELECT COUNT(*) FROM clinical.patients WHERE source_run_id = %s",
        (validation_summary.run_id,),
    ).fetchone()
    error_count = connection.execute(
        "SELECT COUNT(*) FROM audit.validation_errors WHERE run_id = %s",
        (validation_summary.run_id,),
    ).fetchone()

    assert run_row is not None
    assert run_row[0] == "1.0.0"
    assert run_row[1] == validation_summary.contract_sha256
    assert str(run_row[2]).endswith("v1.0.0.toml")
    assert patient_count is not None and patient_count[0] == 5
    assert error_count is not None and error_count[0] == 3

    repeated_load = persist_dataset_validation_outputs(
        connection,
        "patients",
        tmp_path,
    )
    assert repeated_load.already_loaded is True
    assert repeated_load.records_upserted == 0
    assert repeated_load.validation_errors_inserted == 0
