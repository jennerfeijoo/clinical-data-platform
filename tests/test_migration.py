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


def test_packaged_migrations_are_contiguous_and_versioned() -> None:
    migrations = discover_migrations()

    assert [migration.version for migration in migrations] == [1, 2, 3, 4, 5, 6, 7]
    assert [migration.resource_path for migration in migrations] == [
        "V001__create_core_clinical_schema.sql",
        "V002__add_longitudinal_entities_and_cohorts.sql",
        "V003__add_contract_lineage.sql",
        "V004__add_raw_landing_lineage.sql",
        "V005__add_clinical_history_policy.sql",
        "V006__add_medications_and_procedures.sql",
        "V007__add_minimal_clinical_terminologies.sql",
    ]
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
    assert first.applied_versions == (1, 2, 3, 4, 5, 6, 7)
    assert first.baselined_versions == ()
    assert status.current_version == 7
    assert status.is_current is True
    assert repeated.previous_version == 7
    assert repeated.applied_versions == ()

    rows = connection.execute(
        """
        SELECT version, execution_type
        FROM public.schema_migrations
        ORDER BY version
        """
    ).fetchall()
    assert rows == [
        (1, "migration"),
        (2, "migration"),
        (3, "migration"),
        (4, "migration"),
        (5, "migration"),
        (6, "migration"),
        (7, "migration"),
    ]


@pytest.mark.integration
def test_database_can_upgrade_from_an_earlier_managed_version(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection

    first = migrate_database(connection, target_version=1)
    intermediate = migration_status(connection)
    second = migrate_database(connection)
    final = validate_database_migrations(connection)

    assert first.applied_versions == (1,)
    assert intermediate.current_version == 1
    assert [migration.version for migration in intermediate.pending] == [
        2,
        3,
        4,
        5,
        6,
        7,
    ]
    assert second.previous_version == 1
    assert second.applied_versions == (2, 3, 4, 5, 6, 7)
    assert final.current_version == 7

    history_table = connection.execute(
        "SELECT to_regclass('clinical.patient_history')"
    ).fetchone()
    assert history_table == ("clinical.patient_history",)


@pytest.mark.integration
def test_database_can_upgrade_from_contract_lineage_to_latest(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    initial = migrate_database(connection, target_version=3)
    intermediate = migration_status(connection)
    upgraded = migrate_database(connection)

    assert initial.applied_versions == (1, 2, 3)
    assert intermediate.current_version == 3
    assert [migration.version for migration in intermediate.pending] == [4, 5, 6, 7]
    assert upgraded.previous_version == 3
    assert upgraded.applied_versions == (4, 5, 6, 7)
    assert validate_database_migrations(connection).current_version == 7


@pytest.mark.integration
def test_database_can_upgrade_from_raw_lineage_to_latest(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    initial = migrate_database(connection, target_version=4)
    intermediate = migration_status(connection)
    upgraded = migrate_database(connection)

    assert initial.applied_versions == (1, 2, 3, 4)
    assert intermediate.current_version == 4
    assert [migration.version for migration in intermediate.pending] == [5, 6, 7]
    assert upgraded.previous_version == 4
    assert upgraded.applied_versions == (5, 6, 7)

    record_hash_columns = connection.execute(
        """
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = 'clinical'
          AND column_name = 'record_sha256'
        ORDER BY table_name
        """
    ).fetchall()
    assert record_hash_columns == [
        ("diagnoses",),
        ("encounters",),
        ("medications",),
        ("observations",),
        ("patient_history",),
        ("patients",),
        ("procedures",),
    ]
    assert validate_database_migrations(connection).current_version == 7


@pytest.mark.integration
def test_database_can_upgrade_from_history_policy_to_latest(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    initial = migrate_database(connection, target_version=5)
    intermediate = migration_status(connection)
    upgraded = migrate_database(connection)

    assert initial.applied_versions == (1, 2, 3, 4, 5)
    assert intermediate.current_version == 5
    assert [migration.version for migration in intermediate.pending] == [6, 7]
    assert upgraded.previous_version == 5
    assert upgraded.applied_versions == (6, 7)
    assert connection.execute(
        "SELECT to_regclass('clinical.medications')"
    ).fetchone() == ("clinical.medications",)
    assert connection.execute(
        "SELECT to_regclass('clinical.procedures')"
    ).fetchone() == ("clinical.procedures",)
    assert validate_database_migrations(connection).current_version == 7


@pytest.mark.integration
def test_database_can_upgrade_from_six_entities_to_terminology_layer(
    clean_database_connection: psycopg.Connection[Any],
) -> None:
    connection = clean_database_connection
    initial = migrate_database(connection, target_version=6)
    intermediate = migration_status(connection)
    upgraded = migrate_database(connection)

    assert initial.applied_versions == (1, 2, 3, 4, 5, 6)
    assert intermediate.current_version == 6
    assert [migration.version for migration in intermediate.pending] == [7]
    assert upgraded.previous_version == 6
    assert upgraded.applied_versions == (7,)

    terminology_tables = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'terminology'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()
    assert terminology_tables == [
        ("code_systems",),
        ("concept_mappings",),
        ("concepts",),
        ("system_aliases",),
    ]

    normalized_columns = connection.execute(
        """
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = 'clinical'
          AND column_name = 'normalized_concept_id'
        ORDER BY table_name
        """
    ).fetchall()
    assert normalized_columns == [
        ("diagnoses",),
        ("medications",),
        ("observations",),
        ("procedures",),
    ]
    assert connection.execute(
        "SELECT to_regclass('terminology.normalized_clinical_codes')"
    ).fetchone() == ("terminology.normalized_clinical_codes",)
    assert validate_database_migrations(connection).current_version == 7


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

    assert summary.baselined_versions == (1, 2, 3, 4, 5, 6, 7)
    assert summary.applied_versions == ()
    assert status.current_version == 7
    assert [record.execution_type for record in status.applied] == [
        "baseline",
        "baseline",
        "baseline",
        "baseline",
        "baseline",
        "baseline",
        "baseline",
    ]


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
