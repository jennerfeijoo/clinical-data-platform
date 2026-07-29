# PostgreSQL COPY bulk loading

## Scope

The persistence layer uses PostgreSQL `COPY FROM STDIN` for validated clinical rows and validation errors. The design improves the data-transfer path without bypassing the platform's clinical controls.

This milestone establishes a bulk-loading implementation. It does not claim a measured speedup. Reproducible performance measurements belong to the separate benchmark milestone.

## Previous persistence path

The earlier implementation converted every validated CSV row into a Python tuple, retained the complete batch in memory, and sent the tuples with `cursor.executemany()`.

```text
validated CSV
    → list[dict]
    → list[tuple]
    → repeated parameterized INSERT
    → clinical table
```

This was correct for small fixtures, but it created two scaling problems:

1. the persistence path retained all validated records and all converted tuples in memory;
2. PostgreSQL received a sequence of row-oriented statements instead of a bulk stream.

## Current persistence path

```text
validated CSV
    │
    ├── structural inspection and row count
    │
    ▼
streaming CSV iterator
    │
    ▼
Python type conversion, one row at a time
    │
    ▼
COPY FROM STDIN
    │
    ▼
temporary staging table
    │
    ▼
INSERT INTO clinical target
SELECT ... FROM staging
ON CONFLICT ...
    │
    ▼
target constraints, defaults, and triggers
```

The temporary table is created with:

```sql
CREATE TEMP TABLE <unique_name> ON COMMIT DROP AS
SELECT <load_columns>
FROM <clinical_target>
WITH NO DATA;
```

It inherits the selected PostgreSQL data types but does not copy target constraints, indexes, defaults, or triggers. This makes staging inexpensive while preserving typed input.

## Why COPY does not write directly to the clinical target

A direct command such as:

```sql
COPY clinical.patients (...) FROM STDIN;
```

would be fast for append-only input, but it cannot express the platform's required `ON CONFLICT` behavior. The current model needs two different policies:

- patients: current snapshot upsert plus SCD Type 2 history;
- encounters, diagnoses, observations, medications, and procedures: exact duplicate tolerance with conflicting identifier reuse rejected by immutable-event triggers.

The staging table separates transfer from reconciliation:

```text
COPY
→ fast transfer into staging

INSERT ... SELECT ... ON CONFLICT
→ governed merge into the clinical model
```

## Why target triggers remain enabled

The merge statement writes to the real clinical table. Therefore all target controls continue to execute:

```text
patients
→ record SHA-256 trigger
→ SCD Type 2 history trigger

coded events
→ terminology resolution trigger
→ record SHA-256 or immutability trigger

all entities
→ foreign keys
→ check constraints
→ source-run lineage
```

The implementation does not disable triggers, set `session_replication_role`, or copy directly into internal history tables.

## Declarative COPY plans

Each registered dataset has a `CopyMergePlan` containing:

```text
schema
table
ordered COPY columns
conflict columns
update columns
whether loaded_at is refreshed
```

The registry remains the only location that defines dataset-specific persistence shape. The generic COPY engine composes identifiers safely with `psycopg.sql.Identifier`.

The six targets are:

```text
clinical.patients
clinical.encounters
clinical.diagnoses
clinical.observations
clinical.medications
clinical.procedures
```

## Streaming and memory boundary

Persistence no longer calls `read_csv_records()` for validated outputs. It uses two passes with bounded record memory:

1. `inspect_csv_records()` validates the header, validates row structure, and counts rows;
2. `iter_csv_records()` reopens the CSV and yields one record at a time to the typed row builder and COPY writer.

The platform still materializes source records during contract validation. The bounded-memory improvement applies specifically to the database persistence phase.

## Validation-output preflight

Before any loading attempt begins, persistence verifies:

```text
quality report structure
exact valid-output header
exact invalid-output header
exact validation-error header
valid row count
invalid row count
validation-error count
contract path, version, and SHA-256
raw receipt and object lineage
execution journal identity and hash chain
UUID and date fields
```

The copied row counts are checked again inside the transaction. A file changed between preflight and COPY causes the transaction to fail.

## Clinical transaction

For a non-idempotent loading attempt:

```text
Transaction B
    create temporary staging table
    COPY clinical rows to staging
    set-based merge into governed target
    COPY validation errors into audit.validation_errors
    append completed execution event
    update current run projection
    COMMIT
```

If any step fails:

```text
clinical target changes
staging contents
validation-error inserts
completed event
→ ROLLBACK together
```

The already-committed loading state is then followed by a durable failed event in a separate transaction, preserving the existing audit topology.

## Validation-error COPY

Validation errors do not need conflict reconciliation because one validated run is loaded only once after successful completion. They are copied directly into:

```text
audit.validation_errors
```

The copied columns are:

```text
run_id
row_number
entity_id
patient_id
field_name
rule_name
message
rejected_value
```

They remain in the same clinical transaction as the target merge and completion event.

## Idempotency and retries

### Completed run

A repeated request for a run already marked `completed` returns without creating staging tables or writing rows.

### Failed run

The same validated run can retry:

```text
failed
→ loading attempt N+1
→ completed or failed
```

Temporary staging table names include a random suffix, preventing collisions between attempts or concurrent sessions.

### Duplicate clinical event

An event with the same identifier and identical business content is accepted by the target upsert path. Existing immutable-event triggers return the stored record rather than replacing its original lineage.

### Conflicting clinical event

An event reusing an identifier with different business content causes the target trigger to raise an error. The full clinical transaction rolls back and the loading failure remains auditable.

## Structured logging

New operational event families include:

```text
persistence.copy.started
persistence.copy.completed
persistence.copy.failed

persistence.validation_error_copy.started
persistence.validation_error_copy.completed
persistence.validation_error_copy.failed
```

Completion fields include aggregate technical metadata:

```text
loading_method = postgresql_copy
rows_copied
rows_merged
validation_errors_copied
staging_table
duration_ms
attempt_number
```

No clinical rows or identifiers are intentionally logged.

## Rows copied versus rows merged

`rows_copied` is the number of records transmitted into the temporary table.

`rows_merged` is the PostgreSQL row count reported by the set-based target statement. It includes inserted rows and rows handled by the conflict action.

These values answer different questions:

```text
rows_copied
→ Did the complete validated batch reach PostgreSQL staging?

rows_merged
→ How many target rows were processed by reconciliation?
```

The authoritative run completion count continues to use the validated records transferred for that run.

## Database migration boundary

No V009 migration is required because:

- staging tables are session-local and temporary;
- no permanent table, function, trigger, index, view, or constraint is added;
- the existing V001–V008 schema already contains the required clinical and audit controls.

After loading, the migration state remains:

```text
detected=8
current=8
latest=8
pending=[]
```

## Testing

The test suite covers:

```text
COPY plan validation
streaming CSV inspection
COPY into a temporary target
set-based insert and update reconciliation
direct validation-error COPY
all six clinical entities
patient SCD Type 2 history
immutable event conflicts
terminology assignment
foreign-key rollback
loading retries
completed-run idempotency
durable failure audit
Docker and package smoke tests
```

## Limitations

- COPY currently uses psycopg row adaptation with `write_row()`, not PostgreSQL binary COPY.
- Contract validation still loads a complete input dataset into Python memory.
- The temporary staging table is not analyzed because each table exists only for one short transaction.
- Parallel multi-dataset orchestration is not implemented.
- Performance, peak memory, rows per second, and scaling behavior have not yet been benchmarked.
- This repository remains synthetic-data engineering software, not a PHI-ready or production clinical platform.

## Relevant files

```text
src/clinical_data_platform/bulk.py
src/clinical_data_platform/ingestion.py
src/clinical_data_platform/registry.py
src/clinical_data_platform/database.py
tests/test_bulk_loading.py
```
