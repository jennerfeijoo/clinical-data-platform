import json
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.database import (
    DatabaseConfigurationError,
    PersistenceError,
    database_url_from_environment,
    persist_dataset_validation_outputs,
)
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.run_audit import (
    get_pipeline_run,
    list_pipeline_run_events,
    validate_pipeline_run_audit,
)

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
def test_dataset_is_persisted_with_complete_execution_audit(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    output_directory = tmp_path / "processed"
    raw_root = tmp_path / "raw"
    validation_summary = run_dataset_validation(
        "patients",
        SAMPLE_DATASET,
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )
    connection = clean_database_connection
    migrate_database(connection)
    persistence_summary = persist_dataset_validation_outputs(
        connection,
        "patients",
        output_directory,
        raw_root=raw_root,
    )

    assert persistence_summary.run_id == validation_summary.run_id
    assert persistence_summary.dataset == "patients"
    assert persistence_summary.contract_version == "1.0.0"
    assert persistence_summary.already_loaded is False
    assert persistence_summary.attempt_number == 1
    assert persistence_summary.final_status == "completed"
    assert persistence_summary.records_upserted == 5
    assert persistence_summary.validation_errors_inserted == 3

    run_row = connection.execute(
        """
        SELECT
            contract_version,
            contract_sha256,
            contract_path,
            raw_receipt_id,
            raw_manifest_path,
            raw_manifest_sha256,
            raw_object_path,
            raw_size_bytes,
            status,
            current_stage,
            attempt_count,
            local_journal_event_count,
            audit_event_count,
            failure_type
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
    assert run_row[3] == validation_summary.raw_receipt_id
    assert run_row[4] == validation_summary.raw_manifest_relative_path
    assert run_row[5] == validation_summary.raw_manifest_sha256
    assert run_row[6] == validation_summary.raw_object_relative_path
    assert run_row[7] == validation_summary.raw_size_bytes
    assert run_row[8:14] == ("completed", "completed", 1, 4, 6, None)
    assert patient_count == (5,)
    assert error_count == (3,)

    snapshot = get_pipeline_run(connection, validation_summary.run_id)
    events = list_pipeline_run_events(connection, validation_summary.run_id)
    audit_validation = validate_pipeline_run_audit(connection, validation_summary.run_id)

    assert snapshot.status == "completed"
    assert snapshot.completed_at is not None
    assert snapshot.failed_at is None
    assert [event.to_status for event in events] == [
        "created",
        "raw_captured",
        "validating",
        "validated",
        "loading",
        "completed",
    ]
    assert [event.attempt_number for event in events] == [0, 0, 0, 0, 1, 1]
    assert audit_validation.current_status == "completed"
    assert audit_validation.event_count == 6
    assert audit_validation.audit_gap_reason is None

    repeated_load = persist_dataset_validation_outputs(
        connection,
        "patients",
        output_directory,
        raw_root=raw_root,
    )
    assert repeated_load.already_loaded is True
    assert repeated_load.attempt_number == 1
    assert repeated_load.final_status == "completed"
    assert repeated_load.records_upserted == 0
    assert repeated_load.validation_errors_inserted == 0
    assert len(list_pipeline_run_events(connection, validation_summary.run_id)) == 6


@pytest.mark.integration
def test_persistence_rejects_tampered_raw_manifest_lineage(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    output_directory = tmp_path / "processed"
    raw_root = tmp_path / "raw"
    summary = run_dataset_validation(
        "patients",
        SAMPLE_DATASET,
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )
    report_path = summary.quality_report_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["raw_manifest_sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")

    connection = clean_database_connection
    migrate_database(connection)
    with pytest.raises(PersistenceError, match="raw_manifest_sha256"):
        persist_dataset_validation_outputs(
            connection,
            "patients",
            output_directory,
            raw_root=raw_root,
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM audit.pipeline_runs WHERE run_id = %s",
        (summary.run_id,),
    ).fetchone() == (0,)


@pytest.mark.integration
def test_persistence_rejects_tampered_execution_journal(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    output_directory = tmp_path / "processed"
    raw_root = tmp_path / "raw"
    summary = run_dataset_validation(
        "patients",
        SAMPLE_DATASET,
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )
    lines = summary.execution_journal_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[1])
    event["stage"] = "tampered"
    lines[1] = json.dumps(event)
    summary.execution_journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    connection = clean_database_connection
    migrate_database(connection)
    with pytest.raises(PersistenceError, match="Execution journal"):
        persist_dataset_validation_outputs(
            connection,
            "patients",
            output_directory,
            raw_root=raw_root,
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM audit.pipeline_runs WHERE run_id = %s",
        (summary.run_id,),
    ).fetchone() == (0,)
