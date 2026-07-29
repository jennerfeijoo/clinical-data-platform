import os
from datetime import date
from pathlib import Path

import pytest

from clinical_data_platform.database import (
    DatabaseConfigurationError,
    apply_schema,
    connect_database,
    database_url_from_environment,
    persist_patient_validation_outputs,
)
from clinical_data_platform.pipeline import run_patient_validation

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATASET = REPOSITORY_ROOT / "data" / "sample" / "patients.csv"
SCHEMA_PATH = REPOSITORY_ROOT / "sql" / "schema.sql"
DATABASE_URL = os.getenv("DATABASE_URL")


def test_database_url_is_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = "postgresql://user:password@localhost:5432/database"
    monkeypatch.setenv("DATABASE_URL", expected)

    assert database_url_from_environment() == expected


def test_missing_database_url_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(DatabaseConfigurationError, match="DATABASE_URL is required"):
        database_url_from_environment()


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is not configured")
def test_validation_outputs_are_persisted_transactionally(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    validation_summary = run_patient_validation(
        SAMPLE_DATASET,
        tmp_path,
        reference_date=date(2026, 7, 29),
    )

    with connect_database(DATABASE_URL) as connection:
        apply_schema(connection, SCHEMA_PATH)
        persistence_summary = persist_patient_validation_outputs(connection, tmp_path)

        assert persistence_summary.run_id == validation_summary.run_id
        assert persistence_summary.already_loaded is False
        assert persistence_summary.patients_upserted == 5
        assert persistence_summary.validation_errors_inserted == 3

        run_count = connection.execute(
            "SELECT COUNT(*) FROM audit.pipeline_runs WHERE run_id = %s",
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

        assert run_count is not None and run_count[0] == 1
        assert patient_count is not None and patient_count[0] == 5
        assert error_count is not None and error_count[0] == 3

        repeated_load = persist_patient_validation_outputs(connection, tmp_path)
        assert repeated_load.already_loaded is True
        assert repeated_load.patients_upserted == 0
        assert repeated_load.validation_errors_inserted == 0
