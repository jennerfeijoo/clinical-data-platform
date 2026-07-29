"""Execution lifecycle state machine and hash-chained local audit journals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Mapping
from uuid import UUID

EXECUTION_JOURNAL_VERSION: Final = "1.0.0"
EXECUTION_JOURNAL_FILENAME: Final = "execution_journal.jsonl"
MAX_ERROR_MESSAGE_LENGTH: Final = 2_000

EXECUTION_STATUSES: Final = (
    "created",
    "raw_captured",
    "validating",
    "validated",
    "loading",
    "completed",
    "failed",
)

_ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "created": frozenset({"raw_captured", "failed"}),
    "raw_captured": frozenset({"validating", "failed"}),
    "validating": frozenset({"validated", "failed"}),
    "validated": frozenset({"loading", "failed"}),
    "loading": frozenset({"completed", "failed"}),
    "failed": frozenset({"loading"}),
    "completed": frozenset(),
}


class ExecutionAuditError(RuntimeError):
    """Raised when an execution journal is malformed or inconsistent."""


class ExecutionTransitionError(ExecutionAuditError):
    """Raised when a lifecycle transition is not permitted."""


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    """One immutable execution-state transition."""

    journal_version: str
    run_id: UUID
    dataset: str
    sequence_number: int
    attempt_number: int
    from_status: str | None
    to_status: str
    stage: str
    occurred_at: datetime
    previous_event_sha256: str | None
    event_sha256: str
    error_type: str | None
    error_message: str | None
    error_code: str | None
    details: dict[str, object]


@dataclass(frozen=True, slots=True)
class ExecutionJournalSummary:
    """Verified identity and head information for one journal."""

    run_id: UUID
    dataset: str
    status: str
    event_count: int
    head_sha256: str
    started_at: datetime
    validated_at: datetime | None
    failed_at: datetime | None
    events: tuple[ExecutionEvent, ...]


class _RecordedFailure(RuntimeError):
    """Internal wrapper used only to reproduce stored failed-event hashes."""

    def __init__(self, message: str, error_type: str | None, error_code: str | None) -> None:
        super().__init__(message)
        self.recorded_error_type = error_type
        self.sqlstate = error_code


def _exception_fields(exc: BaseException) -> tuple[str, str, str | None]:
    if isinstance(exc, _RecordedFailure):
        error_type = exc.recorded_error_type or "recorded.failure"
    else:
        error_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    message = str(exc).strip() or type(exc).__qualname__
    message = message[:MAX_ERROR_MESSAGE_LENGTH]
    raw_code = getattr(exc, "sqlstate", None)
    error_code = str(raw_code).strip() if raw_code else None
    return error_type, message, error_code


def _canonical_event_payload(
    *,
    run_id: UUID,
    dataset: str,
    sequence_number: int,
    attempt_number: int,
    from_status: str | None,
    to_status: str,
    stage: str,
    occurred_at: datetime,
    previous_event_sha256: str | None,
    error_type: str | None,
    error_message: str | None,
    error_code: str | None,
    details: Mapping[str, object],
) -> dict[str, object]:
    return {
        "journal_version": EXECUTION_JOURNAL_VERSION,
        "run_id": str(run_id),
        "dataset": dataset,
        "sequence_number": sequence_number,
        "attempt_number": attempt_number,
        "from_status": from_status,
        "to_status": to_status,
        "stage": stage,
        "occurred_at": occurred_at.isoformat(),
        "previous_event_sha256": previous_event_sha256,
        "error_type": error_type,
        "error_message": error_message,
        "error_code": error_code,
        "details": dict(details),
    }


def _event_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_execution_event(
    *,
    run_id: UUID,
    dataset: str,
    sequence_number: int,
    attempt_number: int,
    from_status: str | None,
    to_status: str,
    stage: str,
    previous_event_sha256: str | None,
    occurred_at: datetime | None = None,
    error: BaseException | None = None,
    details: Mapping[str, object] | None = None,
) -> ExecutionEvent:
    """Build and hash one validated lifecycle transition."""
    if not dataset.strip():
        raise ExecutionAuditError("Execution dataset must not be empty.")
    if sequence_number < 1:
        raise ExecutionAuditError("Execution sequence_number must be positive.")
    if attempt_number < 0:
        raise ExecutionAuditError("Execution attempt_number must be non-negative.")
    if to_status not in EXECUTION_STATUSES:
        raise ExecutionTransitionError(f"Unsupported execution status: {to_status}")
    if from_status is None:
        if sequence_number != 1 or to_status != "created":
            raise ExecutionTransitionError(
                "Only the first created event may have no previous status."
            )
    else:
        allowed = _ALLOWED_TRANSITIONS.get(from_status)
        if allowed is None or to_status not in allowed:
            raise ExecutionTransitionError(
                f"Unsupported execution transition: {from_status} -> {to_status}"
            )
    if not stage.strip():
        raise ExecutionAuditError("Execution stage must not be empty.")
    if sequence_number == 1 and previous_event_sha256 is not None:
        raise ExecutionAuditError("The first event cannot reference a previous hash.")
    if sequence_number > 1 and (
        previous_event_sha256 is None or len(previous_event_sha256) != 64
    ):
        raise ExecutionAuditError("Later events require a 64-character previous hash.")

    timestamp = occurred_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ExecutionAuditError("Execution timestamps must be timezone-aware.")

    error_type: str | None = None
    error_message: str | None = None
    error_code: str | None = None
    if error is not None:
        error_type, error_message, error_code = _exception_fields(error)
    if to_status == "failed" and error is None:
        raise ExecutionAuditError("Failed execution events require an exception.")
    if to_status != "failed" and error is not None:
        raise ExecutionAuditError("Only failed execution events may contain an exception.")

    event_details = dict(details or {})
    payload = _canonical_event_payload(
        run_id=run_id,
        dataset=dataset,
        sequence_number=sequence_number,
        attempt_number=attempt_number,
        from_status=from_status,
        to_status=to_status,
        stage=stage,
        occurred_at=timestamp,
        previous_event_sha256=previous_event_sha256,
        error_type=error_type,
        error_message=error_message,
        error_code=error_code,
        details=event_details,
    )
    return ExecutionEvent(
        journal_version=EXECUTION_JOURNAL_VERSION,
        run_id=run_id,
        dataset=dataset,
        sequence_number=sequence_number,
        attempt_number=attempt_number,
        from_status=from_status,
        to_status=to_status,
        stage=stage,
        occurred_at=timestamp,
        previous_event_sha256=previous_event_sha256,
        event_sha256=_event_hash(payload),
        error_type=error_type,
        error_message=error_message,
        error_code=error_code,
        details=event_details,
    )


def event_document(event: ExecutionEvent) -> dict[str, object]:
    """Return the complete JSON-serializable representation of an event."""
    payload = _canonical_event_payload(
        run_id=event.run_id,
        dataset=event.dataset,
        sequence_number=event.sequence_number,
        attempt_number=event.attempt_number,
        from_status=event.from_status,
        to_status=event.to_status,
        stage=event.stage,
        occurred_at=event.occurred_at,
        previous_event_sha256=event.previous_event_sha256,
        error_type=event.error_type,
        error_message=event.error_message,
        error_code=event.error_code,
        details=event.details,
    )
    payload["event_sha256"] = event.event_sha256
    return payload


class ExecutionJournal:
    """Append-only local journal used before PostgreSQL persistence is available."""

    def __init__(self, path: Path, run_id: UUID, dataset: str) -> None:
        self.path = path
        self.run_id = run_id
        self.dataset = dataset
        self._events: list[ExecutionEvent] = []

    @classmethod
    def create(
        cls,
        path: Path,
        run_id: UUID,
        dataset: str,
        *,
        source_path: Path,
    ) -> ExecutionJournal:
        path.parent.mkdir(parents=True, exist_ok=True)
        journal = cls(path, run_id, dataset)
        first = build_execution_event(
            run_id=run_id,
            dataset=dataset,
            sequence_number=1,
            attempt_number=0,
            from_status=None,
            to_status="created",
            stage="initialization",
            previous_event_sha256=None,
            details={"source_path": str(source_path)},
        )
        journal._write(first, exclusive=True)
        return journal

    @property
    def events(self) -> tuple[ExecutionEvent, ...]:
        return tuple(self._events)

    @property
    def current_status(self) -> str:
        if not self._events:
            raise ExecutionAuditError("Execution journal has no events.")
        return self._events[-1].to_status

    @property
    def head_sha256(self) -> str:
        if not self._events:
            raise ExecutionAuditError("Execution journal has no events.")
        return self._events[-1].event_sha256

    def transition(
        self,
        to_status: str,
        stage: str,
        *,
        details: Mapping[str, object] | None = None,
        error: BaseException | None = None,
        attempt_number: int = 0,
    ) -> ExecutionEvent:
        previous = self._events[-1]
        event = build_execution_event(
            run_id=self.run_id,
            dataset=self.dataset,
            sequence_number=previous.sequence_number + 1,
            attempt_number=attempt_number,
            from_status=previous.to_status,
            to_status=to_status,
            stage=stage,
            previous_event_sha256=previous.event_sha256,
            details=details,
            error=error,
        )
        self._write(event, exclusive=False)
        return event

    def fail(
        self,
        stage: str,
        error: BaseException,
        *,
        details: Mapping[str, object] | None = None,
    ) -> ExecutionEvent:
        return self.transition("failed", stage, details=details, error=error)

    def _write(self, event: ExecutionEvent, *, exclusive: bool) -> None:
        mode = "x" if exclusive else "a"
        with self.path.open(mode, encoding="utf-8") as file:
            json.dump(event_document(event), file, sort_keys=True, ensure_ascii=False)
            file.write("\n")
        self._events.append(event)


def _required_string(document: Mapping[str, object], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value:
        raise ExecutionAuditError(f"Journal field must be a non-empty string: {field}")
    return value


def _optional_string(document: Mapping[str, object], field: str) -> str | None:
    value = document.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ExecutionAuditError(f"Journal field must be null or a non-empty string: {field}")
    return value


def _required_integer(document: Mapping[str, object], field: str) -> int:
    value = document.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ExecutionAuditError(f"Journal field must be an integer: {field}")
    return value


def _event_from_document(document: Mapping[str, object]) -> ExecutionEvent:
    details_raw = document.get("details")
    if not isinstance(details_raw, dict) or not all(
        isinstance(key, str) for key in details_raw
    ):
        raise ExecutionAuditError("Journal details must be a JSON object.")
    details = {str(key): value for key, value in details_raw.items()}
    try:
        run_id = UUID(_required_string(document, "run_id"))
        occurred_at = datetime.fromisoformat(_required_string(document, "occurred_at"))
    except ValueError as exc:
        raise ExecutionAuditError("Journal contains an invalid UUID or timestamp.") from exc

    return ExecutionEvent(
        journal_version=_required_string(document, "journal_version"),
        run_id=run_id,
        dataset=_required_string(document, "dataset"),
        sequence_number=_required_integer(document, "sequence_number"),
        attempt_number=_required_integer(document, "attempt_number"),
        from_status=_optional_string(document, "from_status"),
        to_status=_required_string(document, "to_status"),
        stage=_required_string(document, "stage"),
        occurred_at=occurred_at,
        previous_event_sha256=_optional_string(document, "previous_event_sha256"),
        event_sha256=_required_string(document, "event_sha256"),
        error_type=_optional_string(document, "error_type"),
        error_message=_optional_string(document, "error_message"),
        error_code=_optional_string(document, "error_code"),
        details=details,
    )


def read_execution_journal(path: Path) -> ExecutionJournalSummary:
    """Read and cryptographically verify an append-only execution journal."""
    if not path.exists():
        raise FileNotFoundError(f"Execution journal not found: {path}")

    events: list[ExecutionEvent] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExecutionAuditError(
                    f"Execution journal line {line_number} is not valid JSON."
                ) from exc
            if not isinstance(raw, dict):
                raise ExecutionAuditError(
                    f"Execution journal line {line_number} must be a JSON object."
                )
            event = _event_from_document(raw)
            if event.journal_version != EXECUTION_JOURNAL_VERSION:
                raise ExecutionAuditError("Unsupported execution journal version.")
            expected = build_execution_event(
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
                    _RecordedFailure(
                        event.error_message or "Recorded failure",
                        event.error_type,
                        event.error_code,
                    )
                    if event.to_status == "failed"
                    else None
                ),
                details=event.details,
            )
            if expected.event_sha256 != event.event_sha256:
                raise ExecutionAuditError(
                    f"Execution journal hash mismatch at sequence {event.sequence_number}."
                )
            if events:
                previous = events[-1]
                if event.run_id != previous.run_id or event.dataset != previous.dataset:
                    raise ExecutionAuditError("Execution journal identity changed between events.")
                if event.sequence_number != previous.sequence_number + 1:
                    raise ExecutionAuditError("Execution journal sequence is not contiguous.")
                if event.previous_event_sha256 != previous.event_sha256:
                    raise ExecutionAuditError("Execution journal hash chain is broken.")
            events.append(event)

    if not events:
        raise ExecutionAuditError("Execution journal is empty.")
    first = events[0]
    validated_at = next(
        (event.occurred_at for event in events if event.to_status == "validated"),
        None,
    )
    failed_at = next(
        (event.occurred_at for event in reversed(events) if event.to_status == "failed"),
        None,
    )
    return ExecutionJournalSummary(
        run_id=first.run_id,
        dataset=first.dataset,
        status=events[-1].to_status,
        event_count=len(events),
        head_sha256=events[-1].event_sha256,
        started_at=first.occurred_at,
        validated_at=validated_at,
        failed_at=failed_at,
        events=tuple(events),
    )
