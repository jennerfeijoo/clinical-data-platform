"""Structured application logging with context propagation and PHI-safe fields."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, TextIO
from uuid import UUID, uuid4

LOG_SCHEMA_VERSION: Final = "1.0.0"
APPLICATION_LOGGER_NAME: Final = "clinical_data_platform"
DEFAULT_LOG_LEVEL: Final = "INFO"
DEFAULT_LOG_FORMAT: Final = "json"
MAX_LOG_MESSAGE_LENGTH: Final = 2_000
SUPPORTED_LOG_LEVELS: Final = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
SUPPORTED_LOG_FORMATS: Final = ("json", "text")

_LOG_CONTEXT: ContextVar[dict[str, object] | None] = ContextVar(
    "clinical_data_platform_log_context",
    default=None,
)

_SENSITIVE_FIELD_NAMES: Final = frozenset(
    {
        "authorization",
        "cookie",
        "database_url",
        "diagnosis_id",
        "encounter_id",
        "entity_id",
        "medication_id",
        "observation_id",
        "password",
        "patient_id",
        "procedure_id",
        "record",
        "records",
        "rejected_value",
        "secret",
        "source_row",
        "token",
    }
)
_CREDENTIAL_URL_PATTERN: Final = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^:/@\s]+:[^@\s]+@"
)
_POSTGRES_KEY_PATTERN: Final = re.compile(
    r"Key\s+\([^)]+\)=\([^)]+\)",
    flags=re.IGNORECASE,
)
_DETAIL_LINE_PATTERN: Final = re.compile(
    r"(?im)^DETAIL:\s*.*$",
)


@dataclass(frozen=True, slots=True)
class LoggingConfiguration:
    """Resolved application logging configuration."""

    level: str
    output_format: str
    destination: str


def _utc_timestamp(created: float) -> str:
    return (
        datetime.fromtimestamp(created, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def sanitize_text(value: str) -> str:
    """Remove credentials and database values from free-form log text."""
    sanitized = _CREDENTIAL_URL_PATTERN.sub(
        r"\g<scheme><redacted>:<redacted>@",
        value,
    )
    sanitized = _POSTGRES_KEY_PATTERN.sub(
        "Key (<redacted>)=(<redacted>)",
        sanitized,
    )
    sanitized = _DETAIL_LINE_PATTERN.sub("DETAIL: <redacted>", sanitized)
    if len(sanitized) > MAX_LOG_MESSAGE_LENGTH:
        return sanitized[: MAX_LOG_MESSAGE_LENGTH - 3] + "..."
    return sanitized


def _normalize_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, (UUID, Path, datetime)):
        return str(value)
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_normalize_value(item) for item in value]
    return sanitize_text(str(value))


def _sanitize_mapping(fields: Mapping[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in fields.items():
        normalized_key = str(key)
        if normalized_key.lower() in _SENSITIVE_FIELD_NAMES:
            sanitized[normalized_key] = "<redacted>"
        else:
            sanitized[normalized_key] = _normalize_value(value)
    return sanitized


def safe_exception_fields(error: BaseException) -> dict[str, object]:
    """Return normalized exception metadata without a traceback or row values."""
    error_type = f"{type(error).__module__}.{type(error).__qualname__}"
    error_code = getattr(error, "sqlstate", None)
    message = str(error).strip() or type(error).__qualname__
    fields: dict[str, object] = {
        "error_type": error_type,
        "error_message": sanitize_text(message),
    }
    if isinstance(error_code, str) and error_code:
        fields["error_code"] = error_code
    return fields


def current_log_context() -> dict[str, object]:
    """Return a copy of the current structured context."""
    context = _LOG_CONTEXT.get()
    return dict(context) if context is not None else {}


@contextmanager
def bind_log_context(**fields: object) -> Iterator[None]:
    """Temporarily merge fields into the context propagated to child operations."""
    merged = current_log_context()
    merged.update(_sanitize_mapping(fields))
    token = _LOG_CONTEXT.set(merged)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


@contextmanager
def ensure_correlation_id() -> Iterator[str]:
    """Preserve an existing correlation identifier or create one for this operation."""
    existing = current_log_context().get("correlation_id")
    if isinstance(existing, str) and existing:
        yield existing
        return
    correlation_id = str(uuid4())
    with bind_log_context(correlation_id=correlation_id):
        yield correlation_id


class StructuredJsonFormatter(logging.Formatter):
    """Serialize one application log record as a stable JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        raw_fields = getattr(record, "structured_fields", {})
        fields = _sanitize_mapping(raw_fields) if isinstance(raw_fields, Mapping) else {}
        event = str(fields.pop("event", "application.message"))
        component = record.name.removeprefix(f"{APPLICATION_LOGGER_NAME}.")
        if component == APPLICATION_LOGGER_NAME:
            component = "application"
        document: dict[str, object] = {
            "schema_version": LOG_SCHEMA_VERSION,
            "timestamp": _utc_timestamp(record.created),
            "level": record.levelname.lower(),
            "event": event,
            "component": component,
            "message": sanitize_text(record.getMessage()),
        }
        document.update(fields)
        if record.exc_info is not None and record.exc_info[1] is not None:
            document.update(safe_exception_fields(record.exc_info[1]))
        return json.dumps(document, sort_keys=True, separators=(",", ":"))


class StructuredTextFormatter(logging.Formatter):
    """Render the same structured fields as a compact human-readable line."""

    def format(self, record: logging.LogRecord) -> str:
        raw_fields = getattr(record, "structured_fields", {})
        fields = _sanitize_mapping(raw_fields) if isinstance(raw_fields, Mapping) else {}
        event = str(fields.pop("event", "application.message"))
        component = record.name.removeprefix(f"{APPLICATION_LOGGER_NAME}.")
        if component == APPLICATION_LOGGER_NAME:
            component = "application"
        suffix = " ".join(
            f"{key}={json.dumps(value, sort_keys=True)}"
            for key, value in sorted(fields.items())
        )
        base = (
            f"{_utc_timestamp(record.created)} {record.levelname} "
            f"{component} {event} {sanitize_text(record.getMessage())}"
        )
        return f"{base} {suffix}".rstrip()


def _resolve_level(value: str | None) -> str:
    resolved = (value or os.getenv("CLINICAL_DATA_LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()
    if resolved not in SUPPORTED_LOG_LEVELS:
        expected = ", ".join(SUPPORTED_LOG_LEVELS)
        raise ValueError(f"Unsupported log level {resolved!r}; expected one of {expected}.")
    return resolved


def _resolve_format(value: str | None) -> str:
    resolved = (value or os.getenv("CLINICAL_DATA_LOG_FORMAT") or DEFAULT_LOG_FORMAT).lower()
    if resolved not in SUPPORTED_LOG_FORMATS:
        expected = ", ".join(SUPPORTED_LOG_FORMATS)
        raise ValueError(f"Unsupported log format {resolved!r}; expected one of {expected}.")
    return resolved


def configure_logging(
    *,
    level: str | None = None,
    output_format: str | None = None,
    stream: TextIO | None = None,
) -> LoggingConfiguration:
    """Configure the application logger without modifying the process root logger."""
    resolved_level = _resolve_level(level)
    resolved_format = _resolve_format(output_format)
    destination = "stderr" if stream is None else "provided_stream"

    application_logger = logging.getLogger(APPLICATION_LOGGER_NAME)
    application_logger.handlers.clear()
    application_logger.setLevel(resolved_level)
    application_logger.propagate = False
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(resolved_level)
    handler.setFormatter(
        StructuredJsonFormatter()
        if resolved_format == "json"
        else StructuredTextFormatter()
    )
    application_logger.addHandler(handler)

    return LoggingConfiguration(
        level=resolved_level,
        output_format=resolved_format,
        destination=destination,
    )


def get_logger(component: str) -> logging.Logger:
    """Return a namespaced application logger for one component."""
    normalized = component.strip().replace(" ", "_")
    if not normalized:
        raise ValueError("Logging component cannot be empty.")
    return logging.getLogger(f"{APPLICATION_LOGGER_NAME}.{normalized}")


def emit_log(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **fields: object,
) -> None:
    """Emit one structured event with current context and sanitized fields."""
    payload = current_log_context()
    payload.update(fields)
    payload["event"] = event
    logger.log(
        level,
        sanitize_text(message),
        extra={"structured_fields": _sanitize_mapping(payload)},
    )


@contextmanager
def log_operation(
    logger: logging.Logger,
    event: str,
    *,
    operation: str,
    stage: str | None = None,
    **fields: object,
) -> Iterator[dict[str, object]]:
    """Log started, completed, and failed records around one measured operation."""
    started = time.perf_counter()
    base_fields = dict(fields)
    base_fields["operation"] = operation
    if stage is not None:
        base_fields["stage"] = stage
    emit_log(
        logger,
        logging.INFO,
        f"{event}.started",
        f"Started {operation}.",
        outcome="started",
        **base_fields,
    )
    completion_fields: dict[str, object] = {}
    try:
        yield completion_fields
    except BaseException as error:
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        emit_log(
            logger,
            logging.ERROR,
            f"{event}.failed",
            f"Failed {operation}.",
            outcome="failure",
            duration_ms=duration_ms,
            **base_fields,
            **safe_exception_fields(error),
        )
        raise
    else:
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        emit_log(
            logger,
            logging.INFO,
            f"{event}.completed",
            f"Completed {operation}.",
            outcome="success",
            duration_ms=duration_ms,
            **base_fields,
            **completion_fields,
        )
