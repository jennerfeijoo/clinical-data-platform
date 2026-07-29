# Execution lifecycle and failure audit

## Scope

Every dataset run now has an explicit lifecycle rather than a single terminal label. Validation starts before PostgreSQL is required, while loading state and failures are persisted durably in PostgreSQL.

This design separates two atomicity requirements:

1. clinical rows must never be partially committed;
2. evidence that a loading attempt failed must survive the clinical rollback.

## State machine

The normal path is:

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

Failures may terminate an active stage:

```text
created | raw_captured | validating | validated | loading
→ failed
```

A failed loading run may be retried:

```text
failed
→ loading
→ completed | failed
```

`completed` is terminal. PostgreSQL rejects unsupported state transitions.

## Local execution journal

Validation can fail before a trustworthy database run record exists. The validation pipeline therefore writes an append-only JSONL journal at:

```text
data/processed/<dataset>/execution/<run-id>.jsonl
```

Each event records:

- run and dataset identity;
- sequence and loading-attempt numbers;
- previous and next status;
- execution stage;
- timezone-aware timestamp;
- previous-event SHA-256;
- event SHA-256;
- optional exception type, message, SQLSTATE, and details.

The event hash is calculated from canonical JSON excluding the `event_sha256` field itself. Every event after the first references the previous event hash. Before persistence, the platform verifies identity, contiguous sequence, permitted transitions, error-field consistency, every event hash, and the complete hash chain.

The quality report links to the local journal through:

```text
execution_journal_version
execution_journal_path
execution_event_count
execution_journal_head_sha256
```

A successful validation report has status `validated`, not `completed`, because database loading has not occurred yet.

## Durable PostgreSQL audit

Migration V008 extends `audit.pipeline_runs` with:

```text
current_stage
attempt_count
started_at
validated_at
loading_started_at
completed_at
failed_at
failure_stage
failure_type
failure_message
failure_code
failure_details
local_journal_event_count
local_journal_head_sha256
audit_event_count
audit_head_sha256
audit_gap_reason
updated_at
```

It also creates:

```text
audit.pipeline_run_events
audit.pipeline_run_timeline
```

`pipeline_runs` is the current state projection. `pipeline_run_events` is the ordered historical timeline.

## Transaction boundary

Loading is deliberately split into three transactions.

### Transaction 1: register and acquire

The platform:

1. verifies raw, contract, output, and local-journal lineage;
2. registers the validated run;
3. imports the local journal into `audit.pipeline_run_events`;
4. appends `validated → loading`;
5. commits.

The run is now durably known before clinical writes begin.

### Transaction 2: clinical persistence

The platform writes:

```text
accepted clinical rows
+ normalized validation errors
+ loading → completed event
+ completed current-state projection
```

These changes commit or roll back together. A completed run therefore cannot point to partially committed clinical rows.

### Transaction 3: failure preservation

When transaction 2 fails:

1. all clinical writes are rolled back;
2. the connection returns to a usable state;
3. a new transaction appends `loading → failed`;
4. failure metadata and the audit head are committed;
5. the original exception is re-raised.

This is why the failed run remains queryable even though no partial clinical data remains.

## Failure metadata

A failed loading attempt stores:

```text
failure_stage
failure_type
failure_message
failure_code
failure_details
failed_at
attempt_count
```

`failure_code` stores the PostgreSQL SQLSTATE when available. Examples include:

```text
23503 → foreign-key violation
23514 → check-constraint or domain validation failure
```

Messages are length-limited. The platform stores no Python traceback in the database because tracebacks can expose machine paths or sensitive runtime context. Structured logging remains a separate milestone.

## Retry semantics

A retry uses the same `run_id` and the same verified validation outputs.

First failed attempt:

```text
validated
→ loading       attempt 1
→ failed        attempt 1
```

Successful retry:

```text
failed
→ loading       attempt 2
→ completed     attempt 2
```

The failure event remains in the timeline. Current failure fields are cleared when the retry acquires loading, but historical error metadata remains in `audit.pipeline_run_events`.

A second call after completion is idempotent: it returns `already_loaded=True` and does not append another event.

## Pre-V008 runs

V008 does not fabricate historical events for runs created under earlier versions. Existing rows receive:

```text
audit_gap_reason = pre_v008_execution_history_unavailable
```

Their known current state and available timestamps are backfilled, but `audit_event_count` remains zero. This is an explicit evidence gap rather than invented history.

## Review queries

Current run state:

```sql
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
    failure_type,
    failure_code,
    failure_message,
    audit_event_count,
    audit_gap_reason
FROM audit.pipeline_runs
ORDER BY updated_at DESC;
```

Complete timeline:

```sql
SELECT
    sequence_number,
    attempt_number,
    from_status,
    to_status,
    stage,
    occurred_at,
    error_type,
    error_code,
    error_message,
    event_source,
    previous_event_sha256,
    event_sha256
FROM audit.pipeline_run_timeline
WHERE run_id = '<run-uuid>'
ORDER BY sequence_number;
```

Recent failures:

```sql
SELECT
    run_id,
    dataset_name,
    attempt_count,
    failure_stage,
    failure_type,
    failure_code,
    failure_message,
    failed_at
FROM audit.pipeline_runs
WHERE status = 'failed'
ORDER BY failed_at DESC;
```

Failure rates by dataset:

```sql
SELECT
    dataset_name,
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_runs,
    COUNT(*) FILTER (WHERE attempt_count > 1) AS retried_runs
FROM audit.pipeline_runs
GROUP BY dataset_name
ORDER BY dataset_name;
```

## Python inspection API

```python
from clinical_data_platform.run_audit import (
    get_pipeline_run,
    list_pipeline_run_events,
    validate_pipeline_run_audit,
)

snapshot = get_pipeline_run(connection, run_id)
events = list_pipeline_run_events(connection, run_id)
validation = validate_pipeline_run_audit(connection, run_id)
```

`validate_pipeline_run_audit` checks event count, current head, local-journal boundary, event identities, transitions, hashes, chain continuity, and agreement between the final event and current state.

## Boundaries

This milestone does not yet provide:

- structured JSON application logs;
- external log shipping;
- distributed tracing;
- metrics and alerting;
- scheduler heartbeats or stale-run recovery;
- cross-service correlation IDs;
- administrator-resistant database audit storage.

The local JSONL journal is append-only by application behavior and tamper-evident through hashes, but it is not certified WORM storage.
