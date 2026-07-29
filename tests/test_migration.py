from typing import Any

import psycopg
import pytest

from clinical_data_platform.migration import (
    MigrationChecksumError,
    MigrationHistoryError,
    discover_migrations,
    migrate_database,
    migration_status,
    validate_database_migrations,
)

EXPECTED_MIGRATIONS = [
    "V001__create_core_clinical_schema.sql",
    "V002__add_longitudinal_entities_and_cohorts.sql",
    "V003__add_contract_lineage.sql",
    "V004__add_raw_landing_lineage.sql",
    "V005__add_clinical_history_policy.sql",
    "V006__add_medications_and_procedures.sql",
    "V007__add_minimal_clinical_terminologies.sql",
    "V008__add_execution_lifecycle_audit.sql",
]


def test_packaged_migrations_are_contiguous_and_versioned() -> None:
    migrations = discover_migrations()

    assert [migration.version for migration in migrations] == list(range(1, 9))
    assert [migration.resource_path for migration in migrations] == EXPECTED_MIGRATIONS
    assert all(len(migration.checksum) == 64 for migration in migrations)


@pytest.mark.integration
def test_fresh_database_is_migrated_and_reexecution_is_idempotent(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection

    first = migrate_database(connection)
    status = validate_database_migrations(connection)
    repeated = migrate_database(connection)

    assert first.previous_version == 0
    assert first.applied_versions == tuple(range(1, 9))
    assert first.baselined_versions == ()
    assert status.current_version == 8
    assert status.detected_schema_version == 8
    assert status.is_current is True
    assert repeated.previous_version == 8
    assert repeated.applied_versions == ()

    rows = connection.execute(
        """
        SELECT version, execution_type
        FROM public.schema_migrations
        ORDER BY version
        """
    ).fetchall()
    assert rows == [(version, "migration") for version in range(1, 9)]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "pending", "applied"),
    [
        (1, [2, 3, 4, 5, 6, 7, 8], (2, 3, 4, 5, 6, 7, 8)),
        (3, [4, 5, 6, 7, 8], (4, 5, 6, 7, 8)),
        (4, [5, 6, 7, 8], (5, 6, 7, 8)),
        (5, [6, 7, 8], (6, 7, 8)),
        (6, [7, 8], (7, 8)),
        (7, [8], (8,)),
    ],
)
def test_database_can_upgrade_from_each_managed_milestone(
    clean_database_connection: psycopg.Connection[Any],
    target: int,
    pending: list[int],
    applied: tuple[int, ...],
) -> None:
    connection = clean_database_connection
    initial = migrate_database(connection, target_version=target)
    intermediate = migration_status(connection)
    upgraded = migrate_database(connection)
    final = validate_database_migrations(connection)

    assert initial.current_version == target
    assert intermediate.current_version == target
    assert [migration.version for migration in intermediate.pending] == pending
    assert upgraded.previous_version == target
    assert upgraded.applied_versions == applied
    assert final.current_version == 8
    assert final.detected_schema_version == 8


@pytest.mark.integration
def test_v008_adds_complete_execution_audit_schema(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection, target_version=7)
    upgraded = migrate_database(connection)

    assert upgraded.applied_versions == (8,)
    assert connection.execute(
        "SELECT to_regclass('audit.pipeline_run_events')"
    ).fetchone() == ("audit.pipeline_run_events",)
    assert connection.execute(
        "SELECT to_regclass('audit.pipeline_run_timeline')"
    ).fetchone() == ("audit.pipeline_run_timeline",)

    columns = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'audit'
          AND table_name = 'pipeline_runs'
          AND column_name IN (
              'current_stage',
              'attempt_count',
              'started_at',
              'validated_at',
              'loading_started_at',
              'completed_at',
              'failed_at',
              'failure_stage',
              'failure_type',
              'failure_message',
              'failure_code',
              'failure_details',
              'local_journal_event_count',
              'local_journal_head_sha256',
              'audit_event_count',
              'audit_head_sha256',
              'audit_gap_reason',
              'updated_at'
          )
        ORDER BY column_name
        """
    ).fetchall()
    assert len(columns) == 18
    assert validate_database_migrations(connection).current_version == 8


@pytest.mark.integration
def test_v008_marks_preexisting_runs_with_an_explicit_audit_gap(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection, target_version=7)
    connection.execute(
        """
        INSERT INTO audit.pipeline_runs (
            run_id,
            dataset_name,
            source_path,
            source_sha256,
            raw_receipt_id,
            raw_received_at,
            raw_storage_version,
            raw_manifest_path,
            raw_manifest_sha256,
            raw_object_path,
            raw_size_bytes,
            contract_path,
            contract_version,
            contract_sha256,
            reference_date,
            rows_received,
            rows_valid,
            rows_invalid,
            validation_errors,
            status,
            generated_at
        )
        VALUES (
            '00000000-0000-0000-0000-000000000008',
            'patients',
            'legacy.csv',
            repeat('a', 64),
            '00000000-0000-0000-0000-000000000108',
            CURRENT_TIMESTAMP,
            '1.0.0',
            'receipts/legacy.json',
            repeat('b', 64),
            'objects/legacy.csv',
            1,
            'patients/v1.0.0.toml',
            '1.0.0',
            repeat('c', 64),
            DATE '2026-07-29',
            0,
            0,
            0,
            0,
            'completed',
            CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()

    migrate_database(connection)
    row = connection.execute(
        """
        SELECT
            status,
            current_stage,
            attempt_count,
            audit_event_count,
            audit_head_sha256,
            audit_gap_reason
        FROM audit.pipeline_runs
        WHERE run_id = '00000000-0000-0000-0000-000000000008'
        """
    ).fetchone()

    assert row == (
        "completed",
        "completed",
        1,
        0,
        None,
        "pre_v008_execution_history_unavailable",
    )


@pytest.mark.integration
def test_recognized_legacy_schema_requires_explicit_baseline(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrations = discover_migrations()
    for migration in migrations:
        connection.execute(migration.sql, prepare=False)
    connection.commit()

    with pytest.raises(MigrationHistoryError, match="no migration history"):
        migrate_database(connection)

    summary = migrate_database(connection, baseline_existing=True)
    status = validate_database_migrations(connection)

    assert summary.baselined_versions == tuple(range(1, 9))
    assert summary.applied_versions == ()
    assert status.current_version == 8
    assert [record.execution_type for record in status.applied] == ["baseline"] * 8


@pytest.mark.integration
def test_changed_applied_migration_checksum_is_rejected(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    migrate_database(connection)
    connection.execute(
        """
        UPDATE public.schema_migrations
        SET checksum = %s
        WHERE version = 2
        """,
        ("0" * 64,),
    )
    connection.commit()

    with pytest.raises(MigrationChecksumError, match="checksum differs"):
        validate_database_migrations(connection)
