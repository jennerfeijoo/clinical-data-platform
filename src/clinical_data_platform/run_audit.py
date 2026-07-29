"""Durable PostgreSQL audit records for pipeline execution lifecycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from clinical_data_platform.execution import (
    ExecutionAuditError,
    ExecutionEvent,
    ExecutionJournalSummary,
    build_execution_event,
    calculate_execution_event_sha256,
)


class RunAuditError(RuntimeError):
    """Raised when durable run audit state is missing or inconsistent."""


class RunAlreadyLoadingError(RunAuditError):
    """Raised when another loader already owns the run's loading state."""


@dataclass(frozen=True, slots=True)
class RunRegistration:
    """Verified metadata required to register a validated pipeline run."""

    run_id: UUID
    dataset: str
    source_path: str
    source_sha256: str
    raw_receipt_id: UUID
    raw_received_at: datetime
    raw_storage_version: str
    raw_manifest_path: str
    raw_manifest_sha256: str
    raw_object_path: str
    raw_size_bytes: int
    contract_path: str
    contract_version: str
    contract_sha256: str
    reference_date: date
    rows_received: int
    rows_valid: int
    rows_invalid: int
    validation_errors: int
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class PipelineRunSnapshot:
    """Current durable execution state for one run."""

    run_id: UUID
    dataset: str
    status: str
    current_stage: str
    attempt_count: int
    started_at: datetime
    validated_at: datetime | None
    loading_started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    failure_stage: str | None
    failure_type: str | None
    failure_message: str | None
    failure_code: str | None
    failure_details: dict[str, object] | None
    local_journal_event_count: int
    local_journal_head_sha256: str | None
    audit_event_count: int
    audit_head_sha256: str | None
    audit_gap_reason: str | None


@dataclass(frozen=True, slots=True)
class LoadingAttempt:
    """One acquired loading attempt or an already-completed result."""

    already_completed: bool
    attempt_number: int


@dataclass(frozen=True, slots=True)
class RunAuditValidation:
    """Result of validating a durable execution audit chain."""

    run_id: UUID
    current_status: str
    event_count: int
    attempt_count: int
    audit_gap_reason: str | None


def _details(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RunAuditError("Run failure_details must be a JSON object.")
    return {str(key): item for key, item in value.items()}


def _snapshot_from_row(row: tuple[object, ...]) -> PipelineRunSnapshot:
    return PipelineRunSnapshot(
        run_id=row[0],
        dataset=str(row[1]),
        status=str(row[2]),
        current_stage=str(row[3]),
        attempt_count=int(row[4]),
        started_at=row[5],
        validated_at=row[6],
        loading_started_at=row[7],
        completed_at=row[8],
        failed_at=row[9],
        failure_stage=str(row[10]) if row[10] is not None else None,
        failure_type=str(row[11]) if row[11] is not None else None,
        failure_message=str(row[12]) if row[12] is not None else None,
        failure_code=str(row[13]) if row[13] is not None else None,
        failure_details=_details(row[14]),
        local_journal_event_count=int(row[15]),
        local_journal_head_sha256=(
            str(row[16]).strip() if row[16] is not None else None
        ),
        audit_event_count=int(row[17]),
        audit_head_sha256=str(row[18]).strip() if row[18] is not None else None,
        audit_gap_reason=str(row[19]) if row[19] is not None else None,
    )


def _select_run(
    connection: psycopg.Connection[Any],
    run_id: UUID,
    *,
    for_update: bool = False,
) -> PipelineRunSnapshot | None:
    lock_clause = " FOR UPDATE" if for_update else ""
    row = connection.execute(
        f"""
        SELECT
            run_id,
            dataset_name,
            status,
            current_stage,
            attempt_count,
            started_at,
            validated_at,
            loading_started_at,
            completed_at,
            failed_at,
            failure_stage,
            failure_type,
            failure_message,
            failure_code,
            failure_details,
            local_journal_event_count,
            local_journal_head_sha256,
            audit_event_count,
            audit_head_sha256,
            audit_gap_reason
        FROM audit.pipeline_runs
        WHERE run_id = %s{lock_clause}
        """,
        (run_id,),
    ).fetchone()
    return _snapshot_from_row(row) if row is not None else None


def _insert_event(
    connection: psycopg.Connection[Any],
    event: ExecutionEvent,
    *,
    source: str,
) -> None:
    inserted = connection.execute(
        """
        INSERT INTO audit.pipeline_run_events (
            run_id,
            sequence_number,
            attempt_number,
            from_status,
            to_status,
            stage,
            occurred_at,
            previous_event_sha256,
            event_sha256,
            error_type,
            error_message,
            error_code,
            details,
            event_source
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (run_id, sequence_number) DO NOTHING
        """,
        (
            event.run_id,
            event.sequence_number,
            event.attempt_number,
            event.from_status,
            event.to_status,
            event.stage,
            event.occurred_at,
            event.previous_event_sha256,
            event.event_sha256,
            event.error_type,
            event.error_message,
            event.error_code,
            Jsonb(event.details),
            source,
        ),
    )
    if inserted.rowcount == 1:
        return
    existing = connection.execute(
        """
        SELECT event_sha256
        FROM audit.pipeline_run_events
        WHERE run_id = %s AND sequence_number = %s
        """,
        (event.run_id, event.sequence_number),
    ).fetchone()
    if existing is None or str(existing[0]).strip() != event.event_sha256:
        raise RunAuditError(
            f"Execution event conflict at sequence {event.sequence_number}."
        )


def register_validated_run(
    connection: psycopg.Connection[Any],
    registration: RunRegistration,
    journal: ExecutionJournalSummary,
) -> PipelineRunSnapshot:
    """Durably register validated metadata and import the local journal."""
    if journal.run_id != registration.run_id or journal.dataset != registration.dataset:
        raise RunAuditError("Execution journal identity does not match run registration.")
    if journal.status != "validated" or journal.validated_at is None:
        raise RunAuditError("Only a validated local journal can be registered for loading.")

    with connection.transaction():
        inserted = connection.execute(
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
                generated_at,
                current_stage,
                attempt_count,
                started_at,
                validated_at,
                local_journal_event_count,
                local_journal_head_sha256,
                audit_event_count,
                audit_head_sha256,
                audit_gap_reason
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, 'validated',
                %s, 'validation', 0, %s, %s, %s, %s, %s, %s, NULL
            )
            ON CONFLICT (run_id) DO NOTHING
            """,
            (
                registration.run_id,
                registration.dataset,
                registration.source_path,
                registration.source_sha256,
                registration.raw_receipt_id,
                registration.raw_received_at,
                registration.raw_storage_version,
                registration.raw_manifest_path,
                registration.raw_manifest_sha256,
                registration.raw_object_path,
                registration.raw_size_bytes,
                registration.contract_path,
                registration.contract_version,
                registration.contract_sha256,
                registration.reference_date,
                registration.rows_received,
                registration.rows_valid,
                registration.rows_invalid,
                registration.validation_errors,
                registration.generated_at,
                journal.started_at,
                journal.validated_at,
                journal.event_count,
                journal.head_sha256,
                journal.event_count,
                journal.head_sha256,
            ),
        )
        snapshot = _select_run(connection, registration.run_id, for_update=True)
        if snapshot is None:
            raise RunAuditError("Validated run registration was not persisted.")

        identity = connection.execute(
            """
            SELECT
                dataset_name,
                source_sha256,
                contract_sha256,
                local_journal_event_count,
                local_journal_head_sha256
            FROM audit.pipeline_runs
            WHERE run_id = %s
            """,
            (registration.run_id,),
        ).fetchone()
        expected_identity = (
            registration.dataset,
            registration.source_sha256,
            registration.contract_sha256,
            journal.event_count,
            journal.head_sha256,
        )
        actual_identity = (
            str(identity[0]),
            str(identity[1]).strip(),
            str(identity[2]).strip(),
            int(identity[3]),
            str(identity[4]).strip(),
        ) if identity is not None else None
        if actual_identity != expected_identity:
            raise RunAuditError("Existing run_id refers to different validated content.")

        for event in journal.events:
            _insert_event(connection, event, source="local_journal")

        if inserted.rowcount == 1:
            snapshot = _select_run(connection, registration.run_id, for_update=True)
            if snapshot is None:
                raise RunAuditError("Newly registered run cannot be read back.")
        return snapshot


def begin_loading_attempt(
    connection: psycopg.Connection[Any],
    run_id: UUID,
) -> LoadingAttempt:
    """Acquire a durable loading attempt and append its transition event."""
    with connection.transaction():
        snapshot = _select_run(connection, run_id, for_update=True)
        if snapshot is None:
            raise RunAuditError(f"Pipeline run is not registered: {run_id}")
        if snapshot.status == "completed":
            return LoadingAttempt(True, snapshot.attempt_count)
        if snapshot.status == "loading":
            raise RunAlreadyLoadingError(f"Pipeline run is already loading: {run_id}")
        if snapshot.status not in {"validated", "failed"}:
            raise RunAuditError(
                f"Pipeline run cannot begin loading from status {snapshot.status!r}."
            )
        if snapshot.audit_head_sha256 is None:
            raise RunAuditError("Pipeline run has no audit head for loading transition.")

        attempt = snapshot.attempt_count + 1
        event = build_execution_event(
            run_id=run_id,
            dataset=snapshot.dataset,
            sequence_number=snapshot.audit_event_count + 1,
            attempt_number=attempt,
            from_status=snapshot.status,
            to_status="loading",
            stage="persistence",
            previous_event_sha256=snapshot.audit_head_sha256,
            details={"retry": snapshot.status == "failed"},
        )
        _insert_event(connection, event, source="database")
        connection.execute(
            """
            UPDATE audit.pipeline_runs
            SET
                status = 'loading',
                current_stage = 'persistence',
                attempt_count = %s,
                loading_started_at = %s,
                completed_at = NULL,
                failed_at = NULL,
                failure_stage = NULL,
                failure_type = NULL,
                failure_message = NULL,
                failure_code = NULL,
                failure_details = NULL,
                audit_event_count = %s,
                audit_head_sha256 = %s
            WHERE run_id = %s
            """,
            (
                attempt,
                event.occurred_at,
                event.sequence_number,
                event.event_sha256,
                run_id,
            ),
        )
        return LoadingAttempt(False, attempt)


def complete_loading_attempt(
    connection: psycopg.Connection[Any],
    run_id: UUID,
    attempt_number: int,
    *,
    records_persisted: int,
    validation_errors_persisted: int,
) -> None:
    """Append completion inside the same transaction as clinical persistence."""
    snapshot = _select_run(connection, run_id, for_update=True)
    if snapshot is None:
        raise RunAuditError(f"Pipeline run is not registered: {run_id}")
    if snapshot.status != "loading" or snapshot.attempt_count != attempt_number:
        raise RunAuditError("Loading completion does not own the current run attempt.")
    if snapshot.audit_head_sha256 is None:
        raise RunAuditError("Loading run has no audit head.")

    event = build_execution_event(
        run_id=run_id,
        dataset=snapshot.dataset,
        sequence_number=snapshot.audit_event_count + 1,
        attempt_number=attempt_number,
        from_status="loading",
        to_status="completed",
        stage="persistence",
        previous_event_sha256=snapshot.audit_head_sha256,
        details={
            "records_persisted": records_persisted,
            "validation_errors_persisted": validation_errors_persisted,
        },
    )
    _insert_event(connection, event, source="database")
    connection.execute(
        """
        UPDATE audit.pipeline_runs
        SET
            status = 'completed',
            current_stage = 'completed',
            completed_at = %s,
            audit_event_count = %s,
            audit_head_sha256 = %s
        WHERE run_id = %s
        """,
        (event.occurred_at, event.sequence_number, event.event_sha256, run_id),
    )


def fail_loading_attempt(
    connection: psycopg.Connection[Any],
    run_id: UUID,
    attempt_number: int,
    error: BaseException,
    *,
    stage: str = "persistence",
    details: Mapping[str, object] | None = None,
) -> None:
    """Persist a failed attempt in a new transaction after clinical rollback."""
    with connection.transaction():
        snapshot = _select_run(connection, run_id, for_update=True)
        if snapshot is None:
            raise RunAuditError(f"Pipeline run is not registered: {run_id}")
        if snapshot.status != "loading" or snapshot.attempt_count != attempt_number:
            raise RunAuditError("Failure does not own the current loading attempt.")
        if snapshot.audit_head_sha256 is None:
            raise RunAuditError("Loading run has no audit head.")

        event = build_execution_event(
            run_id=run_id,
            dataset=snapshot.dataset,
            sequence_number=snapshot.audit_event_count + 1,
            attempt_number=attempt_number,
            from_status="loading",
            to_status="failed",
            stage=stage,
            previous_event_sha256=snapshot.audit_head_sha256,
            error=error,
            details=details,
        )
        _insert_event(connection, event, source="database")
        connection.execute(
            """
            UPDATE audit.pipeline_runs
            SET
                status = 'failed',
                current_stage = %s,
                failed_at = %s,
                failure_stage = %s,
                failure_type = %s,
                failure_message = %s,
                failure_code = %s,
                failure_details = %s,
                audit_event_count = %s,
                audit_head_sha256 = %s
            WHERE run_id = %s
            """,
            (
                stage,
                event.occurred_at,
                stage,
                event.error_type,
                event.error_message,
                event.error_code,
                Jsonb(event.details),
                event.sequence_number,
                event.event_sha256,
                run_id,
            ),
        )


def get_pipeline_run(
    connection: psycopg.Connection[Any],
    run_id: UUID,
) -> PipelineRunSnapshot:
    """Return the current durable state of one run."""
    snapshot = _select_run(connection, run_id)
    if snapshot is None:
        raise RunAuditError(f"Pipeline run is not registered: {run_id}")
    return snapshot


def list_pipeline_run_events(
    connection: psycopg.Connection[Any],
    run_id: UUID,
) -> tuple[ExecutionEvent, ...]:
    """Return one run's ordered execution events."""
    rows = connection.execute(
        """
        SELECT
            run_id,
            sequence_number,
            attempt_number,
            from_status,
            to_status,
            stage,
            occurred_at,
            previous_event_sha256,
            event_sha256,
            error_type,
            error_message,
            error_code,
            details
        FROM audit.pipeline_run_events
        WHERE run_id = %s
        ORDER BY sequence_number
        """,
        (run_id,),
    ).fetchall()
    events: list[ExecutionEvent] = []
    for row in rows:
        event_details = _details(row[12]) or {}
        events.append(
            ExecutionEvent(
                journal_version="1.0.0",
                run_id=row[0],
                dataset=get_pipeline_run(connection, run_id).dataset,
                sequence_number=int(row[1]),
                attempt_number=int(row[2]),
                from_status=str(row[3]) if row[3] is not None else None,
                to_status=str(row[4]),
                stage=str(row[5]),
                occurred_at=row[6],
                previous_event_sha256=(
                    str(row[7]).strip() if row[7] is not None else None
                ),
                event_sha256=str(row[8]).strip(),
                error_type=str(row[9]) if row[9] is not None else None,
                error_message=str(row[10]) if row[10] is not None else None,
                error_code=str(row[11]) if row[11] is not None else None,
                details=event_details,
            )
        )
    return tuple(events)


def validate_pipeline_run_audit(
    connection: psycopg.Connection[Any],
    run_id: UUID,
) -> RunAuditValidation:
    """Verify event counts, hashes, transitions, identities, and current state."""
    snapshot = get_pipeline_run(connection, run_id)
    events = list_pipeline_run_events(connection, run_id)
    if snapshot.audit_gap_reason is not None and not events:
        return RunAuditValidation(
            run_id=run_id,
            current_status=snapshot.status,
            event_count=0,
            attempt_count=snapshot.attempt_count,
            audit_gap_reason=snapshot.audit_gap_reason,
        )
    if len(events) != snapshot.audit_event_count:
        raise RunAuditError("Run audit event count does not match pipeline_runs.")
    if not events:
        raise RunAuditError("Run has no execution events and no declared audit gap.")
    if snapshot.audit_head_sha256 != events[-1].event_sha256:
        raise RunAuditError("Run audit head does not match the last event.")
    if snapshot.local_journal_event_count > len(events):
        raise RunAuditError("Local journal count exceeds the durable event count.")
    local_head = events[snapshot.local_journal_event_count - 1].event_sha256
    if snapshot.local_journal_head_sha256 != local_head:
        raise RunAuditError("Local journal head does not match imported events.")

    previous: ExecutionEvent | None = None
    for event in events:
        if event.run_id != run_id or event.dataset != snapshot.dataset:
            raise RunAuditError("Execution event identity does not match its run.")
        if event.event_sha256 != calculate_execution_event_sha256(event):
            raise RunAuditError(
                f"Execution event hash mismatch at sequence {event.sequence_number}."
            )
        if previous is None:
            if event.sequence_number != 1 or event.from_status is not None:
                raise RunAuditError("Execution audit does not begin with sequence one.")
        else:
            if event.sequence_number != previous.sequence_number + 1:
                raise RunAuditError("Execution event sequence is not contiguous.")
            if event.previous_event_sha256 != previous.event_sha256:
                raise RunAuditError("Execution event hash chain is broken.")
            try:
                build_execution_event(
                    run_id=event.run_id,
                    dataset=event.dataset,
                    sequence_number=event.sequence_number,
                    attempt_number=event.attempt_number,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    stage=event.stage,
                    previous_event_sha256=event.previous_event_sha256,
                    occurred_at=event.occurred_at,
                    error=(
                        _AuditFailure(
                            event.error_message or "Recorded failure",
                            event.error_type,
                            event.error_code,
                        )
                        if event.to_status == "failed"
                        else None
                    ),
                    details=event.details,
                )
            except ExecutionAuditError as exc:
                raise RunAuditError("Execution event transition is invalid.") from exc
        previous = event

    if events[-1].to_status != snapshot.status:
        raise RunAuditError("Current run status does not match its final event.")
    return RunAuditValidation(
        run_id=run_id,
        current_status=snapshot.status,
        event_count=len(events),
        attempt_count=snapshot.attempt_count,
        audit_gap_reason=snapshot.audit_gap_reason,
    )


class _AuditFailure(RuntimeError):
    """Failure wrapper that preserves stored error metadata during verification."""

    def __init__(self, message: str, error_type: str | None, error_code: str | None) -> None:
        super().__init__(message)
        self.recorded_error_type = error_type
        self.sqlstate = error_code
