"""Versioned PostgreSQL migration discovery, validation, and execution."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from importlib.resources import files
from typing import Any, Final

import psycopg

from clinical_data_platform import __version__

MIGRATION_PACKAGE: Final = "clinical_data_platform.migrations"
MIGRATION_PATTERN: Final = re.compile(
    r"^V(?P<version>[1-9]\d{2})__(?P<name>[a-z0-9_]+)\.sql$"
)
MIGRATION_LOCK_ID: Final = 734_202_607_29
HISTORY_TABLE: Final = "public.schema_migrations"


class MigrationError(RuntimeError):
    """Base class for database migration failures."""


class MigrationDefinitionError(MigrationError):
    """Raised when packaged migration resources are malformed."""


class MigrationHistoryError(MigrationError):
    """Raised when database history is missing or inconsistent."""


class MigrationChecksumError(MigrationHistoryError):
    """Raised when an applied migration no longer matches its stored checksum."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One immutable packaged SQL migration."""

    version: int
    name: str
    resource_path: str
    checksum: str
    sql: str


@dataclass(frozen=True, slots=True)
class AppliedMigration:
    """One migration-history row stored in PostgreSQL."""

    version: int
    name: str
    checksum: str
    applied_at: datetime
    execution_ms: int
    execution_type: str
    application_version: str


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    """Current migration state for one database."""

    managed: bool
    detected_schema_version: int
    current_version: int
    latest_version: int
    applied: tuple[AppliedMigration, ...]
    pending: tuple[Migration, ...]

    @property
    def is_current(self) -> bool:
        """Return whether the database is managed and fully migrated."""
        return self.managed and not self.pending


@dataclass(frozen=True, slots=True)
class MigrationSummary:
    """Result of one migration execution."""

    previous_version: int
    current_version: int
    target_version: int
    baselined_versions: tuple[int, ...]
    applied_versions: tuple[int, ...]


@cache
def discover_migrations() -> tuple[Migration, ...]:
    """Discover packaged migrations and verify a contiguous version sequence."""
    discovered: list[Migration] = []
    for resource in files(MIGRATION_PACKAGE).iterdir():
        match = MIGRATION_PATTERN.fullmatch(resource.name)
        if not resource.is_file() or match is None:
            continue
        content = resource.read_bytes()
        discovered.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                resource_path=resource.name,
                checksum=hashlib.sha256(content).hexdigest(),
                sql=content.decode("utf-8"),
            )
        )

    discovered.sort(key=lambda migration: migration.version)
    if not discovered:
        raise MigrationDefinitionError("No packaged database migrations were found.")

    versions = [migration.version for migration in discovered]
    expected = list(range(1, len(discovered) + 1))
    if versions != expected:
        raise MigrationDefinitionError(
            f"Migration versions must be contiguous from V001; found {versions}."
        )
    if len({migration.name for migration in discovered}) != len(discovered):
        raise MigrationDefinitionError("Migration names must be unique.")
    return tuple(discovered)


def _table_exists(connection: psycopg.Connection[Any], qualified_name: str) -> bool:
    row = connection.execute("SELECT to_regclass(%s)", (qualified_name,)).fetchone()
    return row is not None and row[0] is not None


def _column_exists(
    connection: psycopg.Connection[Any],
    schema_name: str,
    table_name: str,
    column_name: str,
) -> bool:
    row = connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND column_name = %s
        )
        """,
        (schema_name, table_name, column_name),
    ).fetchone()
    return row is not None and bool(row[0])


def _detect_existing_schema_version(connection: psycopg.Connection[Any]) -> int:
    """Identify the highest complete pre-migration schema represented in the database."""
    core_tables = (
        "audit.pipeline_runs",
        "audit.validation_errors",
        "clinical.patients",
    )
    core_presence = tuple(_table_exists(connection, table) for table in core_tables)
    if not any(core_presence):
        return 0
    if not all(core_presence):
        raise MigrationHistoryError(
            "The database contains a partial core schema and cannot be baselined safely."
        )

    version = 1
    longitudinal_tables = (
        "clinical.encounters",
        "clinical.diagnoses",
        "clinical.observations",
        "audit.cohort_runs",
        "audit.cohort_source_runs",
        "analytics.hypertension_features",
    )
    longitudinal_presence = tuple(
        _table_exists(connection, table) for table in longitudinal_tables
    )
    has_entity_id = _column_exists(
        connection,
        "audit",
        "validation_errors",
        "entity_id",
    )
    if any(longitudinal_presence) or has_entity_id:
        if not all(longitudinal_presence) or not has_entity_id:
            raise MigrationHistoryError(
                "The database contains a partial longitudinal schema and cannot be baselined."
            )
        version = 2

    contract_columns = (
        "contract_path",
        "contract_version",
        "contract_sha256",
    )
    contract_presence = tuple(
        _column_exists(connection, "audit", "pipeline_runs", column)
        for column in contract_columns
    )
    if any(contract_presence):
        if not all(contract_presence) or version < 2:
            raise MigrationHistoryError(
                "The database contains partial contract-lineage columns and cannot be baselined."
            )
        version = 3
    return version


def _ensure_history_table(connection: psycopg.Connection[Any]) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            name TEXT NOT NULL,
            checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            execution_ms INTEGER NOT NULL CHECK (execution_ms >= 0),
            execution_type TEXT NOT NULL
                CHECK (execution_type IN ('migration', 'baseline')),
            application_version TEXT NOT NULL
        )
        """,
        prepare=False,
    )


def _read_history(connection: psycopg.Connection[Any]) -> tuple[AppliedMigration, ...]:
    if not _table_exists(connection, HISTORY_TABLE):
        return ()
    rows = connection.execute(
        """
        SELECT
            version,
            name,
            checksum,
            applied_at,
            execution_ms,
            execution_type,
            application_version
        FROM public.schema_migrations
        ORDER BY version
        """
    ).fetchall()
    return tuple(
        AppliedMigration(
            version=int(row[0]),
            name=str(row[1]),
            checksum=str(row[2]).strip(),
            applied_at=row[3],
            execution_ms=int(row[4]),
            execution_type=str(row[5]),
            application_version=str(row[6]),
        )
        for row in rows
    )


def _validate_history(
    available: tuple[Migration, ...],
    applied: tuple[AppliedMigration, ...],
) -> None:
    migration_by_version = {migration.version: migration for migration in available}
    applied_versions = [migration.version for migration in applied]
    expected_prefix = list(range(1, len(applied) + 1))
    if applied_versions != expected_prefix:
        raise MigrationHistoryError(
            "Applied migrations must form a contiguous prefix beginning at V001."
        )

    for record in applied:
        migration = migration_by_version.get(record.version)
        if migration is None:
            raise MigrationHistoryError(
                f"Database contains unknown migration V{record.version:03d}."
            )
        if record.name != migration.name:
            raise MigrationHistoryError(
                f"Migration V{record.version:03d} name differs from packaged history."
            )
        if record.checksum != migration.checksum:
            raise MigrationChecksumError(
                f"Migration V{record.version:03d} checksum differs from applied history."
            )


def migration_status(connection: psycopg.Connection[Any]) -> MigrationStatus:
    """Inspect migration history without modifying the database."""
    available = discover_migrations()
    detected_version = _detect_existing_schema_version(connection)
    history_exists = _table_exists(connection, HISTORY_TABLE)
    applied = _read_history(connection)
    managed = history_exists and (bool(applied) or detected_version == 0)

    if applied:
        _validate_history(available, applied)
        current_version = applied[-1].version
        if detected_version < current_version:
            raise MigrationHistoryError(
                "Migration history is ahead of the detected database structure."
            )
        if detected_version > current_version:
            raise MigrationHistoryError(
                "Database structure is ahead of migration history; baseline or repair is required."
            )
    else:
        current_version = 0

    pending = tuple(
        migration for migration in available if migration.version > current_version
    )
    return MigrationStatus(
        managed=managed,
        detected_schema_version=detected_version,
        current_version=current_version,
        latest_version=available[-1].version,
        applied=applied,
        pending=pending,
    )


def validate_database_migrations(
    connection: psycopg.Connection[Any],
    *,
    require_current: bool = True,
) -> MigrationStatus:
    """Verify migration history, checksums, and optionally currentness."""
    status = migration_status(connection)
    if status.detected_schema_version > 0 and not status.managed:
        raise MigrationHistoryError(
            "Existing platform tables have no migration history. Run with --baseline-existing."
        )
    if require_current and status.pending:
        pending = ", ".join(f"V{item.version:03d}" for item in status.pending)
        raise MigrationHistoryError(f"Database has pending migrations: {pending}.")
    return status


def _insert_history(
    connection: psycopg.Connection[Any],
    migration: Migration,
    *,
    execution_ms: int,
    execution_type: str,
) -> None:
    connection.execute(
        """
        INSERT INTO public.schema_migrations (
            version,
            name,
            checksum,
            execution_ms,
            execution_type,
            application_version
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            migration.version,
            migration.name,
            migration.checksum,
            execution_ms,
            execution_type,
            __version__,
        ),
    )


def migrate_database(
    connection: psycopg.Connection[Any],
    *,
    target_version: int | None = None,
    baseline_existing: bool = False,
) -> MigrationSummary:
    """Apply pending migrations transactionally and optionally adopt a legacy schema."""
    available = discover_migrations()
    latest_version = available[-1].version
    effective_target = latest_version if target_version is None else target_version
    if effective_target < 0 or effective_target > latest_version:
        raise MigrationDefinitionError(
            f"target_version must be between 0 and {latest_version}."
        )

    baselined_versions: list[int] = []
    applied_versions: list[int] = []

    with connection.transaction():
        connection.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (MIGRATION_LOCK_ID,),
        )
        detected_version = _detect_existing_schema_version(connection)
        _ensure_history_table(connection)
        applied = _read_history(connection)

        if detected_version > 0 and not applied:
            if not baseline_existing:
                raise MigrationHistoryError(
                    "Existing platform tables have no migration history. "
                    "Re-run with baseline_existing=True after reviewing the schema."
                )
            if detected_version > latest_version:
                raise MigrationHistoryError(
                    "Detected schema is newer than the packaged migration set."
                )
            for migration in available[:detected_version]:
                _insert_history(
                    connection,
                    migration,
                    execution_ms=0,
                    execution_type="baseline",
                )
                baselined_versions.append(migration.version)
            applied = _read_history(connection)

        _validate_history(available, applied)
        previous_version = applied[-1].version if applied else 0
        if effective_target < previous_version:
            raise MigrationHistoryError(
                "Downgrade migrations are not supported; target is below current version."
            )
        if detected_version > previous_version and previous_version > 0:
            raise MigrationHistoryError(
                "Database structure is ahead of recorded history and cannot migrate safely."
            )

        for migration in available:
            if previous_version < migration.version <= effective_target:
                started = time.perf_counter()
                connection.execute(migration.sql, prepare=False)
                execution_ms = max(0, round((time.perf_counter() - started) * 1000))
                _insert_history(
                    connection,
                    migration,
                    execution_ms=execution_ms,
                    execution_type="migration",
                )
                applied_versions.append(migration.version)

    current_version = effective_target if applied_versions else max(
        previous_version,
        baselined_versions[-1] if baselined_versions else 0,
    )
    return MigrationSummary(
        previous_version=previous_version,
        current_version=current_version,
        target_version=effective_target,
        baselined_versions=tuple(baselined_versions),
        applied_versions=tuple(applied_versions),
    )
