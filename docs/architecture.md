# Architecture

## System boundary

The repository is a portfolio-grade synthetic clinical data engineering platform under active development. It is not a clinical production system and must not receive identifiable patient data.

## End-to-end flow

```text
CLI command
    ├── stdout: requested command result
    └── stderr: structured operational logs
            │
            └── correlation_id propagated through nested operations

External CSV source
        │
        ▼
Immutable raw landing zone
        ├── content-addressed object
        └── append-only receipt
        │
        ▼
Versioned executable contract
        │
        ▼
Hash-chained local execution journal
        │
        ▼
Generic validation pipeline
        ├── valid rows
        ├── quarantine
        ├── normalized errors
        └── quality report: validated
        │
        ▼
Formal migrations V001–V008
        │
        ▼
Durable execution audit
        ├── current-state projection
        ├── ordered event timeline
        └── failure retained after clinical rollback
        │
        ▼
Terminology resolution
        │
        ▼
Hybrid PostgreSQL persistence
        ├── patient snapshot + SCD2 history
        └── immutable clinical events
        │
        ▼
Versioned cohort SQL and feature export
```

Structured logs observe operations throughout this flow. They do not replace raw, contract, run, record, terminology, or cohort lineage.

## Clinical relationship model

```text
patients
   └── encounters
          ├── diagnoses    → condition concept
          ├── observations → observation concept
          ├── medications  → medication concept
          └── procedures   → procedure concept
```

The six datasets use the same raw, contract, execution, persistence, audit, and logging algorithms. Dataset-specific behavior remains confined to contracts, row builders, SQL, migrations, terminology bindings, and explicit history policies.

## Execution state model

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

Active stages may transition to `failed`. A failed loading execution may retry through `failed → loading`; `completed` is terminal.

The architecture uses two audit representations:

```text
local JSONL journal
    → exists before PostgreSQL is required
    → covers initialization, raw capture, and validation

PostgreSQL event timeline
    → imports the verified local journal
    → adds loading, failure, retry, and completion events
```

Both are linked by SHA-256 event chains. The quality report records the local event count and head hash. `audit.pipeline_runs` stores the current durable head, while `audit.pipeline_run_events` stores the complete ordered timeline.

## Transaction topology

```text
Transaction A
    validated run registration
    + local journal import
    + loading acquisition
    → COMMIT

Transaction B
    clinical rows
    + validation errors
    + completed event
    → COMMIT or ROLLBACK together

Transaction C, only after B fails
    failed event
    + failure metadata
    → COMMIT
```

This topology prevents partial clinical data while preserving evidence of failed attempts.

## Observability model

The application produces three different kinds of evidence:

```text
clinical and analytical data
    → domain records and derived features

execution audit
    → authoritative state, attempts, timestamps, and durable failures

structured logs
    → operational telemetry, timing, component context, and diagnostics
```

The logging schema is versioned independently as `1.0.0`.

Every JSON record contains:

```text
schema_version
timestamp
level
event
component
message
```

Relevant operations add:

```text
correlation_id
run_id
dataset
cohort_run_id
operation
stage
outcome
duration_ms
attempt_number
error_type
error_code
error_message
aggregate counts
```

### Context topology

```text
correlation_id
    ├── run_id A
    │       └── attempt 1, attempt 2, ...
    ├── run_id B
    └── cohort_run_id
```

A `correlation_id` represents one invocation context. It is not a durable lineage key and may be absent if an external caller bypasses the instrumented boundary. Instrumented direct library operations create one when none exists.

Python `contextvars` propagates context through nested synchronous calls and restores the previous context when a scope exits. This avoids adding observability-only parameters to domain function signatures.

### Event pairs

Measured operations produce:

```text
<event>.started
<event>.completed
```

or:

```text
<event>.started
<event>.failed
```

The final event records a monotonic duration and outcome. Exceptions are re-raised after logging.

### Output boundary

```text
stdout
    → user-facing command result

stderr
    → structured telemetry
```

File rotation, retention, collection, transport, and access control are deployment concerns and are not implemented by the repository.

### Data minimization

Logs contain aggregate counts, hashes, versions, stages, and technical errors. They must not contain clinical rows.

The logging layer defensively redacts known clinical identifier fields, rejected values, records, credentials, database URLs, PostgreSQL key values, and `DETAIL:` lines. Redaction is a secondary defense; the primary rule is not to pass clinical values to logging calls.

## Terminology relationship model

```text
source system label
        │
        ▼
terminology.system_aliases
        │
        ▼
source concept
        │
        ├── direct normalized concept
        └── terminology.concept_mappings
                │
                ▼
            target concept
```

The source representation remains in the clinical table. `normalized_concept_id` records the resolved concept used by the local platform.

## Core modules

### `entrypoint.py`

Configures logging before CLI dispatch, creates command correlation context, and emits command started, completed, or failed events.

### `structured_logging.py`

Defines schema versioning, JSON and text formatters, environment configuration, context propagation, operation timing, exception normalization, and defensive redaction.

### `raw.py`

Preserves exact source bytes, derives SHA-256 content paths, creates receipt manifests, publishes atomically, and verifies integrity.

### `contract.py`

Loads TOML contracts, validates contract definitions, calculates contract hashes, and executes structural, categorical, temporal, type, unit, and range rules.

### `execution.py`

Defines lifecycle states, permitted transitions, execution events, canonical event hashing, local JSONL journals, and chain validation.

### `pipeline.py`

Orchestrates raw capture, contract validation, quality outputs, local execution events, and stage-level structured logs. A successful pipeline result is `validated`, not yet `completed`.

### `run_audit.py`

Registers validated runs, imports local events, acquires loading attempts, records completion or failure, supports retries, and validates durable event chains.

### `registry.py`

Maps each dataset to typed row conversion and PostgreSQL persistence SQL. It does not resolve terminology or manage execution state.

### `migration.py`

Discovers V001–V008, checks immutable migration hashes, detects complete schema signatures, serializes execution with an advisory lock, and applies pending versions transactionally.

### `terminology.py`

Provides typed inspection, source-code resolution, and whole-database terminology-binding validation.

### `history.py`

Declares patient SCD Type 2 and immutable-event policies.

### `database.py`

Verifies outputs, contract lineage, raw lineage, and the local execution journal. It coordinates the separate audit and clinical transactions and emits preflight, attempt, transaction, idempotency, and failure-audit logs.

### `cohort.py`

Builds versioned analytical cohorts, records source-run lineage, and logs source resolution, database build, and export durations without row values.

### `demo.py`

Correlates the six validation runs, migration, persistence operations, and cohort build under one demonstration invocation.

## Enforcement boundaries

### Raw boundary

Controls exact bytes and receipt integrity.

### Contract boundary

Controls intrinsic row validity: columns, required values, types, declared vocabularies, temporal order, units, and ranges.

### Execution boundary

Controls lifecycle transitions, attempt ownership, timestamps, failure metadata, event hashes, and agreement between event history and current state.

### Observability boundary

Controls log schema, contextual fields, severity, operation timing, sanitization, and separation between stderr telemetry and stdout results. It does not establish durability.

### Terminology boundary

Controls registered source aliases, installed concepts, active normalized targets, and clinical domain.

### PostgreSQL boundary

Controls foreign keys, constraints, terminology references, record hashes, SCD2 transitions, immutable-event conflicts, and transaction rollback.

A contract-valid row may still fail PostgreSQL because a parent is missing, a code is unknown, a domain is wrong, or an immutable identity conflicts. That failure rolls back clinical changes, remains in the execution audit, and emits sanitized operational telemetry.

## Identity and lineage model

```text
correlation UUID
    → one observable invocation context

raw object SHA-256
    → exact source bytes

raw receipt UUID + SHA-256
    → one reception event

contract path + version + SHA-256
    → exact validation rules

run UUID
    → one logical execution across retries

local journal head SHA-256
    → validated pre-database event prefix

audit head SHA-256
    → complete durable event timeline

attempt number
    → one loading try within the run

normalized_concept_id
    → installed normalized concept

record_sha256
    → normalized clinical business content

cohort run UUID
    → one analytical derivation
```

These identifiers remain deliberately separate. Only the audit and lineage identifiers are persisted as authoritative evidence; the correlation identifier belongs to observability.

## Migration sequence

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and immutable-event policy
V006 medications and procedures
V007 minimal clinical terminology integration
V008 complete execution lifecycle and failure audit
```

Applied migrations are not edited. Corrections require a new forward migration. Structured logging does not require V009 because it does not alter persistent database state.

## Design trade-offs

### Failure evidence outside the clinical transaction

The run must exist before clinical inserts begin. Otherwise the same rollback that protects clinical atomicity would erase the failure record.

### Local journal before database registration

Validation-stage failures need evidence even when PostgreSQL is unavailable or the run has not yet been trusted for registration.

### Logging is not auditing

Logs favor diagnostic detail and external aggregation. Audit records favor durable state consistency. Combining them would either make logs too rigid or make the audit dependent on an optional transport.

### Context propagation without domain parameters

`contextvars` avoids passing correlation metadata through every function. The trade-off is that context must be established at instrumented boundaries and tested for correct restoration.

### Data minimization before redaction

Known fields and text patterns are sanitized, but arbitrary secrets cannot be identified perfectly. Therefore logging calls use aggregates and technical metadata rather than clinical values.

### JSON by default

JSON integrates directly with container and log-processing systems. A text formatter remains available for local reading, while stdout stays reserved for command results.

### Hash chains are tamper-evident, not tamper-proof

They expose unauthorized changes unless an actor rewrites the complete chain and all references. They do not replace restricted access or WORM storage.

### One run, multiple attempts

Retrying does not create a new logical validation identity. The attempt counter and event timeline preserve every loading try under the same verified outputs.

### Honest legacy gaps

V008 labels pre-existing runs with `audit_gap_reason` rather than inventing historical events.

## Current limitations

The platform does not yet implement centralized log transport, OpenTelemetry traces, metrics, dashboards, alerting, automatic log rotation, scheduler heartbeats, stale-run recovery, terminology release importers, UCUM normalization, Synthea generation, bulk `COPY`, performance benchmarks, a second cohort, production security controls, or PHI handling.
