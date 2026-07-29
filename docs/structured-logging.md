# Structured application logging

## Purpose

The structured logging layer records operational telemetry emitted while the application is running. It answers questions such as:

- which component performed an operation;
- which command, dataset, run, or cohort it belonged to;
- when the operation started and finished;
- whether it succeeded or failed;
- how long it took;
- which technical error type or SQLSTATE was raised.

It is separate from the durable execution audit.

```text
structured logs
    → operational diagnostics and observability

audit.pipeline_runs + audit.pipeline_run_events
    → authoritative run state, attempts, and durable failure history
```

Logs can be lost if stderr is not collected. The PostgreSQL audit remains the source of truth for execution state.

## Configuration

The console entrypoint configures logging before CLI dispatch.

```text
CLINICAL_DATA_LOG_LEVEL
    DEBUG | INFO | WARNING | ERROR | CRITICAL

CLINICAL_DATA_LOG_FORMAT
    json | text
```

Defaults:

```text
level  = INFO
format = json
output = stderr
```

CLI result messages continue to use stdout. This allows a scheduler or container runtime to collect telemetry independently from command output.

PowerShell:

```powershell
$env:CLINICAL_DATA_LOG_LEVEL = "INFO"
$env:CLINICAL_DATA_LOG_FORMAT = "json"
clinical-data run-demo --repository-root . 2> data/clinical-data.jsonl
```

POSIX shell:

```bash
CLINICAL_DATA_LOG_LEVEL=INFO \
CLINICAL_DATA_LOG_FORMAT=json \
clinical-data run-demo --repository-root . \
2> data/clinical-data.jsonl
```

The application does not create or rotate log files. Redirection, rotation, retention, shipping, and access control belong to the execution environment.

## JSON schema

Every JSON record contains these required fields:

| Field | Meaning |
|---|---|
| `schema_version` | log document schema, currently `1.0.0` |
| `timestamp` | UTC RFC 3339 timestamp |
| `level` | lowercase severity |
| `event` | stable machine-readable event name |
| `component` | emitting application component |
| `message` | concise human-readable description |

Contextual fields are added when relevant:

| Field | Meaning |
|---|---|
| `correlation_id` | one command or externally bound workflow |
| `command` | CLI subcommand without its arguments |
| `run_id` | one dataset validation and persistence execution |
| `dataset` | registered dataset name |
| `cohort_run_id` | one analytical cohort build |
| `cohort_name` | analytical cohort name |
| `operation` | measured function or logical operation |
| `stage` | raw capture, validation, persistence, export, and similar |
| `outcome` | `started`, `success`, or `failure` |
| `duration_ms` | wall-clock operation duration in milliseconds |
| `attempt_number` | durable loading attempt for one run |
| `error_type` | fully qualified exception class |
| `error_code` | PostgreSQL SQLSTATE when available |
| `error_message` | sanitized and truncated technical message |

Aggregate counts such as `rows_valid`, `records_persisted`, and `validation_errors` may be included. Clinical row contents are not logged.

Example:

```json
{
  "schema_version": "1.0.0",
  "timestamp": "2026-07-29T12:45:01.123Z",
  "level": "info",
  "event": "pipeline.validation.completed",
  "component": "pipeline",
  "message": "Completed validate_records_against_contract.",
  "correlation_id": "3b86c4bd-9e79-4fa9-a31a-59b31a4bb5ef",
  "run_id": "6aa89516-f724-4dc9-b259-510abc11075a",
  "dataset": "patients",
  "operation": "validate_records_against_contract",
  "stage": "validation",
  "outcome": "success",
  "duration_ms": 4,
  "rows_received": 8,
  "rows_valid": 5,
  "rows_invalid": 3,
  "validation_errors": 3
}
```

## Event naming

Events use dotted lowercase names:

```text
<component>.<operation>.<state>
```

Examples:

```text
cli.command.started
cli.command.completed
cli.command.failed

pipeline.run.started
pipeline.raw_capture.completed
pipeline.validation.completed
pipeline.run.validated
pipeline.run.failed

persistence.preflight.completed
persistence.audit_registration.completed
persistence.transaction.completed
persistence.transaction.failed
persistence.failure_audited
persistence.failure_audit_failed
persistence.run.completed
persistence.run.idempotent

cohort.source_runs.completed
cohort.database_build.completed
cohort.export.completed
cohort.run.completed

demo.validation.completed
demo.migration.completed
demo.persistence.completed
demo.run.completed
```

The event name is intended for filtering and aggregation. The message may change for clarity without changing the event contract.

## Correlation model

The CLI creates one `correlation_id` per command. Context propagation uses Python `contextvars`, so nested operations inherit the identifier without passing it through every function signature.

```text
CLI command correlation_id
    ├── demo operations
    ├── dataset run A: run_id
    ├── dataset run B: run_id
    └── cohort build: cohort_run_id
```

A direct library call without an existing correlation identifier creates one at the outer instrumented operation. Nested calls preserve it.

`run_id` and `correlation_id` are not interchangeable:

- one correlation can contain several dataset runs;
- one dataset run keeps its `run_id` across loading retries;
- the correlation identifies an invocation context, not durable clinical lineage.

## Measured operations

`log_operation` emits paired records:

```text
<event>.started
<event>.completed
```

or:

```text
<event>.started
<event>.failed
```

The final record contains `duration_ms` and `outcome`. Exceptions are re-raised after logging; telemetry does not convert failures into successes.

## Redaction and data minimization

The logger applies field-level and text-level sanitization.

Explicitly redacted field names include:

```text
patient_id
encounter_id
diagnosis_id
observation_id
medication_id
procedure_id
entity_id
rejected_value
record
records
source_row
password
secret
token
authorization
cookie
database_url
```

Free-form text removes:

- credentials embedded in URLs;
- PostgreSQL `Key (...)=(...)` values;
- PostgreSQL `DETAIL:` lines;
- content beyond the configured maximum message length.

The design rule is stricter than redaction alone:

> Do not pass clinical row values to logging functions.

Redaction is a defensive layer, not permission to log sensitive data first and clean it later.

## Error handling

Failure logs contain:

```text
error_type
error_message
error_code, when available
```

They deliberately omit full tracebacks from the default structured record. Tracebacks can expose local paths, SQL parameters, secrets, or record values.

For a PostgreSQL foreign-key failure, a safe log can retain:

```text
error_type = psycopg.errors.ForeignKeyViolation
error_code = 23503
```

while redacting the rejected key value.

The durable execution audit separately retains the run failure required for retry and investigation.

## Query examples

All failed events:

```bash
jq 'select(.outcome == "failure")' data/clinical-data.jsonl
```

One correlation:

```bash
jq 'select(.correlation_id == "<correlation-uuid>")' data/clinical-data.jsonl
```

One run:

```bash
jq 'select(.run_id == "<run-uuid>")' data/clinical-data.jsonl
```

Slow operations over 500 ms:

```bash
jq 'select((.duration_ms // 0) > 500)' data/clinical-data.jsonl
```

Persistence failures by SQLSTATE:

```bash
jq 'select(.component == "database" and .error_code != null) |
    {timestamp, dataset, run_id, attempt_number, error_code, error_type}' \
    data/clinical-data.jsonl
```

## Programmatic use

```python
import logging

from clinical_data_platform.structured_logging import (
    bind_log_context,
    configure_logging,
    emit_log,
    get_logger,
    log_operation,
)

configure_logging(level="INFO", output_format="json")
logger = get_logger("example")

with bind_log_context(correlation_id="example-correlation", dataset="patients"):
    with log_operation(
        logger,
        "example.validation",
        operation="validate_example",
        stage="validation",
    ) as completed:
        completed["rows_processed"] = 10

    emit_log(
        logger,
        logging.INFO,
        "example.finished",
        "Example operation finished.",
    )
```

## Verification

The test suite verifies:

- required schema fields;
- UTC timestamps;
- context propagation and restoration;
- success and failure operation pairs;
- duration fields;
- SQLSTATE extraction;
- credential and clinical-identifier redaction;
- pipeline correlation without patient values;
- CLI command lifecycle logs.

CI also exercises the installed console entrypoint and validates that its stderr output is parseable JSON.

## Operational limits

This milestone does not implement:

- centralized log transport;
- OpenTelemetry traces;
- metrics or dashboards;
- alerting;
- scheduler heartbeats;
- distributed trace propagation across processes;
- cryptographic signing or hash chaining of logs;
- automatic file rotation or retention;
- production PHI governance.

These capabilities require deployment-specific infrastructure and remain outside the current repository boundary.
