import csv
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest

from clinical_data_platform.database import persist_dataset_validation_outputs
from clinical_data_platform.history import get_clinical_history_policy
from clinical_data_platform.migration import migrate_database
from clinical_data_platform.pipeline import run_dataset_validation
from clinical_data_platform.run_audit import (
    get_pipeline_run,
    list_pipeline_run_events,
    validate_pipeline_run_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIRECTORY = REPOSITORY_ROOT / "data" / "sample"


def _replace_csv_value(
    source_path: Path,
    target_path: Path,
    *,
    identity_column: str,
    identity_value: str,
    field: str,
    value: str,
) -> None:
    with source_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise AssertionError("Test fixture must contain a CSV header.")
        rows = list(reader)
        fieldnames = reader.fieldnames

    found = False
    for row in rows:
        if row[identity_column] == identity_value:
            row[field] = value
            found = True
    if not found:
        raise AssertionError(f"Fixture identity not found: {identity_value}")

    with target_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _validate_and_load(
    connection: psycopg.Connection[Any],
    tmp_path: Path,
    dataset: str,
    source_path: Path,
    run_name: str,
):
    output_directory = tmp_path / "processed" / run_name
    raw_root = tmp_path / "raw"
    summary = run_dataset_validation(
        dataset,
        source_path,
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )
    persist_dataset_validation_outputs(
        connection,
        dataset,
        output_directory,
        raw_root=raw_root,
    )
    return summary


def test_history_policy_is_explicit_for_every_current_dataset() -> None:
    assert get_clinical_history_policy("patients").mode == "scd2_snapshot"
    assert get_clinical_history_policy("patients").history_table == (
        "clinical.patient_history"
    )

    for dataset in (
        "encounters",
        "diagnoses",
        "observations",
        "medications",
        "procedures",
    ):
        policy = get_clinical_history_policy(dataset)
        assert policy.mode == "immutable_event"
        assert policy.history_table is None
        assert policy.conflicting_identity_behavior == "reject the transaction"


def test_unknown_history_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="No clinical history policy"):
        get_clinical_history_policy("allergies")


@pytest.mark.integration
def test_patient_snapshot_creates_history_only_when_business_data_changes(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)

    first = _validate_and_load(
        connection,
        tmp_path,
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        "patients-first",
    )
    second = _validate_and_load(
        connection,
        tmp_path,
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        "patients-identical",
    )

    history_count = connection.execute(
        "SELECT COUNT(*) FROM clinical.patient_history"
    ).fetchone()
    current_p001 = connection.execute(
        """
        SELECT source_run_id, record_sha256
        FROM clinical.patients
        WHERE patient_id = 'P001'
        """
    ).fetchone()

    assert history_count == (5,)
    assert current_p001 is not None
    assert current_p001[0] == second.run_id
    assert len(str(current_p001[1]).strip()) == 64
    assert first.run_id != second.run_id

    changed_source = tmp_path / "patients-changed.csv"
    _replace_csv_value(
        SAMPLE_DIRECTORY / "patients.csv",
        changed_source,
        identity_column="patient_id",
        identity_value="P001",
        field="sex_at_birth",
        value="OTHER",
    )
    changed = _validate_and_load(
        connection,
        tmp_path,
        "patients",
        changed_source,
        "patients-changed",
    )

    versions = connection.execute(
        """
        SELECT
            sex_at_birth,
            is_current,
            valid_to IS NOT NULL,
            valid_from_run_id,
            valid_to_run_id,
            record_sha256
        FROM clinical.patient_history
        WHERE patient_id = 'P001'
        ORDER BY patient_version_id
        """
    ).fetchall()
    current_snapshot = connection.execute(
        """
        SELECT sex_at_birth, source_run_id, record_sha256
        FROM clinical.patients
        WHERE patient_id = 'P001'
        """
    ).fetchone()

    assert len(versions) == 2
    assert versions[0][0:3] == ("F", False, True)
    assert versions[0][3] == first.run_id
    assert versions[0][4] == changed.run_id
    assert versions[1][0:3] == ("OTHER", True, False)
    assert versions[1][3] == changed.run_id
    assert versions[1][4] is None
    assert str(versions[0][5]).strip() != str(versions[1][5]).strip()
    assert current_snapshot is not None
    assert current_snapshot[0] == "OTHER"
    assert current_snapshot[1] == changed.run_id
    assert current_snapshot[2] == versions[1][5]


@pytest.mark.integration
def test_immutable_event_accepts_exact_duplicate_and_audits_conflict(
    tmp_path: Path,
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    _validate_and_load(
        connection,
        tmp_path,
        "patients",
        SAMPLE_DIRECTORY / "patients.csv",
        "patients",
    )
    first = _validate_and_load(
        connection,
        tmp_path,
        "encounters",
        SAMPLE_DIRECTORY / "encounters.csv",
        "encounters-first",
    )
    _validate_and_load(
        connection,
        tmp_path,
        "encounters",
        SAMPLE_DIRECTORY / "encounters.csv",
        "encounters-identical",
    )

    original_event = connection.execute(
        """
        SELECT encounter_type, source_run_id, record_sha256
        FROM clinical.encounters
        WHERE encounter_id = 'E001'
        """
    ).fetchone()
    assert original_event is not None
    assert original_event[1] == first.run_id
    assert len(str(original_event[2]).strip()) == 64

    conflicting_source = tmp_path / "encounters-conflicting.csv"
    _replace_csv_value(
        SAMPLE_DIRECTORY / "encounters.csv",
        conflicting_source,
        identity_column="encounter_id",
        identity_value="E001",
        field="encounter_type",
        value="EMERGENCY",
    )
    output_directory = tmp_path / "processed" / "encounters-conflicting"
    raw_root = tmp_path / "raw"
    conflict = run_dataset_validation(
        "encounters",
        conflicting_source,
        output_directory,
        raw_root=raw_root,
        reference_date=date(2026, 7, 29),
    )

    with pytest.raises(psycopg.IntegrityError, match="Immutable encounter conflict"):
        persist_dataset_validation_outputs(
            connection,
            "encounters",
            output_directory,
            raw_root=raw_root,
        )

    preserved_event = connection.execute(
        """
        SELECT encounter_type, source_run_id, record_sha256
        FROM clinical.encounters
        WHERE encounter_id = 'E001'
        """
    ).fetchone()
    snapshot = get_pipeline_run(connection, conflict.run_id)
    events = list_pipeline_run_events(connection, conflict.run_id)
    audit = validate_pipeline_run_audit(connection, conflict.run_id)

    assert preserved_event == original_event
    assert snapshot.status == "failed"
    assert snapshot.attempt_count == 1
    assert snapshot.failure_message is not None
    assert "Immutable encounter conflict" in snapshot.failure_message
    assert [event.to_status for event in events] == [
        "created",
        "raw_captured",
        "validating",
        "validated",
        "loading",
        "failed",
    ]
    assert audit.current_status == "failed"
    assert audit.event_count == 6
