from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.database import persist_dataset_validation_outputs
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.run_audit import (
    RunAuditError,
    get_pipeline_run,
    list_pipeline_run_events,
    validate_pipeline_run_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"
REFERENCE_DATE = date(2026, 7, 29)


@pytest.mark.integration
def test_failed_loading_attempt_can_be_retried_after_dependency_is_fixed(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    raw_root = tmp_path / "raw"

    encounter_output = tmp_path / "processed" / "encounters"
    encounter_validation = run_dataset_validation(
        "encounters",
        SAMPLE_DIRECTORY / "encounters.csv",
        encounter_output,
        raw_root=raw_root,
        reference_date=REFERENCE_DATE,
    )

    with pytest.raises(psycopg.IntegrityError):
        persist_dataset_validation_outputs(
            connection,
            "encounters",
            encounter_output,
            raw_root=raw_root,
        )

    failed = get_pipeline_run(connection, encounter_validation.run_id)
    assert failed.status == "failed"
    assert failed.attempt_count == 1
    assert failed.failure_code == "23503"
    assert connection.execute(
        "SELECT COUNT(*) FROM clinical.encounters"
    ).fetchone() == (0,)

    patient_output = tmp_path / "processed" / "patients"
    run_dataset_validation(
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        patient_output,
        raw_root=raw_root,
        reference_date=REFERENCE_DATE,
    )
    persist_dataset_validation_outputs(
        connection,
        "patients",
        patient_output,
        raw_root=raw_root,
    )

    retry = persist_dataset_validation_outputs(
        connection,
        "encounters",
        encounter_output,
        raw_root=raw_root,
    )
    completed = get_pipeline_run(connection, encounter_validation.run_id)
    events = list_pipeline_run_events(connection, encounter_validation.run_id)
    audit = validate_pipeline_run_audit(connection, encounter_validation.run_id)

    assert retry.already_loaded is False
    assert retry.attempt_number == 2
    assert retry.final_status == "completed"
    assert retry.records_upserted == 7
    assert completed.status == "completed"
    assert completed.attempt_count == 2
    assert completed.failed_at is None
    assert completed.failure_type is None
    assert completed.failure_message is None
    assert connection.execute(
        "SELECT COUNT(*) FROM clinical.encounters"
    ).fetchone() == (7,)
    assert [event.to_status for event in events] == [
        "created",
        "raw_captured",
        "validating",
        "validated",
        "loading",
        "failed",
        "loading",
        "completed",
    ]
    assert [event.attempt_number for event in events] == [0, 0, 0, 0, 1, 1, 2, 2]
    assert events[6].details == {"retry": True}
    assert audit.current_status == "completed"
    assert audit.event_count == 8
    assert audit.attempt_count == 2


@pytest.mark.integration
def test_database_event_tampering_is_detected(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    output_directory = tmp_path / "processed"
    raw_root = tmp_path / "raw"
    summary = run_dataset_validation(
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        output_directory,
        raw_root=raw_root,
        reference_date=REFERENCE_DATE,
    )
    persist_dataset_validation_outputs(
        connection,
        "patients",
        output_directory,
        raw_root=raw_root,
    )

    connection.execute(
        """
        UPDATE audit.pipeline_run_events
        SET event_sha256 = %s
        WHERE run_id = %s AND sequence_number = 2
        """,
        ("0" * 64, summary.run_id),
    )
    connection.commit()

    with pytest.raises(RunAuditError, match="invalid"):
        validate_pipeline_run_audit(connection, summary.run_id)


@pytest.mark.integration
def test_database_rejects_illegal_terminal_state_transition(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    output_directory = tmp_path / "processed"
    raw_root = tmp_path / "raw"
    summary = run_dataset_validation(
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        output_directory,
        raw_root=raw_root,
        reference_date=REFERENCE_DATE,
    )
    persist_dataset_validation_outputs(
        connection,
        "patients",
        output_directory,
        raw_root=raw_root,
    )

    with pytest.raises(psycopg.IntegrityError, match="Unsupported pipeline status transition"):
        with connection.transaction():
            connection.execute(
                """
                UPDATE audit.pipeline_runs
                SET status = 'loading', completed_at = NULL
                WHERE run_id = %s
                """,
                (summary.run_id,),
            )

    assert get_pipeline_run(connection, summary.run_id).status == "completed"
