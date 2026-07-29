# PostgreSQL migrations and persistence

## Responsibility split

```text
raw.py
    → exact source bytes and receipt integrity

contract.py
    → source-row acceptance rules

execution.py
    → state machine, event hashing, local journal

migration.py
    → ordered database structure

run_audit.py
    → durable execution state, events, failures, retries

terminology.py
    → terminology inspection and binding validation

history.py
    → snapshot and immutable-event semantics

registry.py
    → typed row conversion and dataset SQL

database.py
    → lineage verification and transaction coordination

PostgreSQL
    → audit state, foreign keys, concepts, hashes, history, rollback
```

## Migration history

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and immutable-event enforcement
V006 medications and procedures
V007 minimal clinical terminologies
V008 complete execution lifecycle and failure audit
```

`public.schema_migrations` stores version, name, checksum, application version, execution type, timestamp, and duration. Applied files are immutable.

## V008 execution schema

V008 extends `audit.pipeline_runs` with current execution state:

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

It creates:

```text
audit.pipeline_run_events
audit.pipeline_run_timeline
```

`pipeline_runs` is the current-state projection. `pipeline_run_events` is the append-oriented historical timeline.

## State constraints

Supported states:

```text
created
raw_captured
validating
validated
loading
completed
failed
```

Normal transitions:

```text
created → raw_captured → validating → validated → loading → completed
```

Failure and retry transitions:

```text
active state → failed
failed → loading
```

A trigger rejects unsupported updates such as `completed → loading`. Constraints also require timestamps and failure fields to agree with the current state.

## Local journal import

Before registering a validated run, `database.py` verifies:

1. dataset and output counts;
2. contract path, version, and SHA-256;
3. raw receipt and object lineage;
4. journal version and path containment;
5. run and dataset identity;
6. event count and head SHA-256;
7. state transitions and hash-chain continuity;
8. final local status `validated`.

The verified local events are imported with `event_source = local_journal`.

## Three-transaction loading model

### Transaction A: durable acquisition

```text
insert or verify audit.pipeline_runs
+ import local journal events
+ append validated|failed → loading
+ increment attempt_count
→ COMMIT
```

The run is durably visible before clinical writes begin.

### Transaction B: atomic clinical load

```text
valid clinical rows
+ audit.validation_errors
+ terminology bindings
+ SCD2 or immutable-event enforcement
+ loading → completed event
+ current status completed
→ COMMIT or ROLLBACK together
```

A completed run cannot coexist with partially committed rows from that attempt.

### Transaction C: durable failure

When transaction B fails:

```text
ROLLBACK transaction B
→ append loading → failed
→ store exception metadata
→ COMMIT transaction C
→ re-raise original exception
```

Clinical data remains unchanged, but the failed attempt remains queryable.

## Failure fields

A failed run contains:

```text
failure_stage
failure_type
failure_message
failure_code
failure_details
failed_at
attempt_count
```

`failure_code` stores SQLSTATE when available. `failure_details` contains bounded operational context such as dataset and attempted row counts. Tracebacks are not stored in PostgreSQL.

## Retry behavior

A retry reuses the same validated run and appends events:

```text
loading attempt 1
→ failed attempt 1
→ loading attempt 2
→ completed attempt 2
```

Current failure fields are cleared when attempt 2 acquires loading. The attempt-1 failure remains in `pipeline_run_events`.

Calling load again after `completed` is idempotent: no new event or clinical write is created.

## Pre-V008 history

V008 cannot reconstruct states that were never recorded. Existing rows receive:

```text
audit_gap_reason = pre_v008_execution_history_unavailable
```

Their known state is retained, but `audit_event_count` remains zero. The system reports the evidence gap instead of fabricating a timeline.

## V007 terminology schema

V007 creates:

```text
terminology.code_systems
terminology.system_aliases
terminology.concepts
terminology.concept_mappings
terminology.normalized_clinical_codes
```

It adds mandatory `normalized_concept_id` values to diagnoses, observations, medications, and procedures. Terminology triggers run before immutable-event guards.

Unknown or wrong-domain concepts fail transaction B. V008 then records the terminology error durably in transaction C.

## Migration detection

Version 8 is recognized only when all of these are present:

- complete V007 structure;
- all execution-state columns in `audit.pipeline_runs`;
- `audit.pipeline_run_events`;
- `audit.pipeline_run_timeline`.

A partial execution-audit schema is rejected rather than baselined.

## Upgrade commands

```powershell
clinical-data database-migrate --target-version 7
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

After the final command:

```text
detected=8
current=8
latest=8
pending=[]
```

## Review queries

Migration history:

```sql
SELECT version, name, checksum, execution_type, application_version, applied_at
FROM public.schema_migrations
ORDER BY version;
```

Current executions:

```sql
SELECT
    run_id,
    dataset_name,
    status,
    current_stage,
    attempt_count,
    failure_code,
    failure_message,
    audit_event_count,
    audit_gap_reason
FROM audit.pipeline_runs
ORDER BY updated_at DESC;
```

One timeline:

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

Failed runs:

```sql
SELECT
    dataset_name,
    failure_stage,
    failure_code,
    COUNT(*)
FROM audit.pipeline_runs
WHERE status = 'failed'
GROUP BY dataset_name, failure_stage, failure_code
ORDER BY COUNT(*) DESC;
```

Retried runs:

```sql
SELECT run_id, dataset_name, status, attempt_count
FROM audit.pipeline_runs
WHERE attempt_count > 1
ORDER BY updated_at DESC;
```

## Limits

The database layer does not yet provide structured application logging, external log transport, distributed tracing, scheduler heartbeats, stale-loading recovery, terminology release importers, event supersession, bitemporal modelling, bulk staging/`COPY`, production access controls, or PHI-ready governance.
