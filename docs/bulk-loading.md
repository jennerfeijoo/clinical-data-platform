# PostgreSQL COPY bulk loading

## Scope

The persistence layer uses PostgreSQL `COPY FROM STDIN` for validated clinical rows and validation errors. The design improves data transfer without bypassing clinical controls.

The separate governed loading benchmark now measures this implementation against the previous psycopg `executemany` path. Reference evidence is documented in [`loading-benchmark.md`](loading-benchmark.md).

## Previous persistence path

The earlier implementation converted every validated CSV row into a Python tuple, retained the complete batch in memory, and sent tuples with `cursor.executemany()`.

```text
validated CSV
→ list[dict]
→ list[tuple]
→ repeated parameterized INSERT
→ clinical table
```

This was correct for small fixtures, but it retained both input records and converted tuples and used a row-oriented transfer path.

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

It inherits selected PostgreSQL data types but does not copy target constraints, indexes, defaults, or triggers. This keeps staging temporary and lightweight while retaining typed input.

## Why COPY does not write directly to the clinical target

A direct operation such as:

```sql
COPY clinical.patients (...) FROM STDIN;
```

cannot express the required `ON CONFLICT` policies.

The model needs:

- patients: current snapshot upsert plus SCD Type 2 history;
- events: exact duplicate tolerance with conflicting identifier reuse rejected.

Staging separates transfer from reconciliation:

```text
COPY
→ bulk transfer into staging

INSERT ... SELECT ... ON CONFLICT
→ governed merge into the clinical model
```

## Why target triggers remain enabled

The merge writes to the real clinical table. Therefore target controls execute normally:

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

The implementation does not disable triggers, change `session_replication_role`, or copy directly into history tables.

## Declarative COPY plans

Each dataset has a `CopyMergePlan` containing:

```text
schema
table
ordered COPY columns
conflict columns
update columns
whether loaded_at is refreshed
```

The registry defines dataset-specific persistence shape. The generic engine composes identifiers with `psycopg.sql.Identifier`.

Targets:

```text
clinical.patients
clinical.encounters
clinical.diagnoses
clinical.observations
clinical.medications
clinical.procedures
```

## Streaming and memory boundary

Persistence no longer calls `read_csv_records()` for validated outputs. It uses two bounded-record-memory passes:

1. `inspect_csv_records()` validates headers and row structure and counts rows.
2. `iter_csv_records()` reopens the CSV and yields one record at a time to the row builder and COPY writer.

Contract validation still materializes the complete source dataset. The bounded-memory improvement applies to persistence, not the complete pipeline.

## Preflight

Before loading begins, persistence verifies:

```text
quality report structure
exact valid-output header
exact invalid-output header
exact validation-error header
valid, invalid, and error counts
contract path, version, and SHA-256
raw receipt and object lineage
execution journal identity and hash chain
UUID and date fields
```

Copied counts are checked again inside the transaction. A file changed between preflight and COPY causes failure.

## Clinical transaction

For a non-idempotent attempt:

```text
Transaction B
    create temporary staging table
    COPY clinical rows to staging
    merge into governed target
    COPY validation errors
    append completed event
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

A durable failed event is then recorded in a separate transaction.

## Validation-error COPY

Validation errors are copied directly into:

```text
audit.validation_errors
```

Columns:

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

They remain in the same transaction as the clinical merge and completion event.

## Idempotency and retries

### Completed run

A repeated request for a completed run returns before staging or row writes.

### Failed run

A validated run may retry:

```text
failed
→ loading attempt N+1
→ completed or failed
```

Staging names include random suffixes, avoiding collisions between attempts or sessions.

### Exact duplicate event

An event with the same identifier and business content is accepted. Immutable-event triggers preserve the existing row and original lineage.

### Conflicting event

Reusing an identifier with different business content raises an error. The clinical transaction rolls back and the failed attempt remains auditable.

## Structured logging

Operational event families:

```text
persistence.copy.started
persistence.copy.completed
persistence.copy.failed

persistence.validation_error_copy.started
persistence.validation_error_copy.completed
persistence.validation_error_copy.failed
```

Aggregate fields include:

```text
loading_method = postgresql_copy
rows_copied
rows_merged
validation_errors_copied
staging_table
duration_ms
attempt_number
```

Clinical rows and identifiers are not intentionally logged.

## Rows copied versus rows merged

`rows_copied` is the number transmitted into staging.

`rows_merged` is the PostgreSQL row count from target reconciliation, including inserted rows and rows handled by conflict actions.

```text
rows_copied
→ did the complete validated batch reach staging?

rows_merged
→ how many target rows were processed by reconciliation?
```

## Migration boundary

No V009 migration is required because:

- staging tables are temporary;
- no permanent table, function, trigger, index, view, or constraint is added;
- V001–V008 already contain the required controls.

Expected state:

```text
detected=8
current=8
latest=8
pending=[]
```

## Measured reference

The documented benchmark uses actual governed targets and compares COPY with the former `executemany` path.

Reference GitHub Actions results:

| Clinical rows | COPY median | `executemany` median | Speedup | Time reduction |
|---:|---:|---:|---:|---:|
| 3,750 | 671.737 ms | 928.806 ms | 1.383× | 27.68% |
| 15,000 | 2,615.950 ms | 3,693.506 ms | 1.412× | 29.17% |
| 37,500 | 6,465.960 ms | 9,176.855 ms | 1.419× | 29.54% |

These values apply to the recorded environment and initial single-writer workload. They are not universal PostgreSQL constants or end-to-end pipeline results.

See:

- [`loading-benchmark.md`](loading-benchmark.md);
- [`../benchmarks/loading/github-actions-run-30466706538/benchmark-summary.md`](../benchmarks/loading/github-actions-run-30466706538/benchmark-summary.md);
- [`learning/benchmark-carga-postgresql-es.md`](learning/benchmark-carga-postgresql-es.md).

## Testing

The suite covers:

```text
COPY plan validation
streaming CSV inspection
temporary staging
set-based reconciliation
direct validation-error COPY
all six entities
patient SCD Type 2 history
immutable conflicts
terminology assignment
foreign-key rollback
loading retries
completed-run idempotency
durable failure audit
benchmark method equivalence
benchmark artifacts
Docker and package smoke tests
```

## Limitations

- COPY uses psycopg row adaptation with `write_row()`, not binary COPY.
- Contract validation still loads a complete input dataset into Python memory.
- Temporary staging is not analyzed because each table exists for one short transaction.
- Parallel multi-dataset orchestration is not implemented.
- The benchmark covers initial single-writer loads up to 37,500 rows.
- Updates, concurrency, remote PostgreSQL, WAL volume, and peak memory are not measured.
- The repository remains synthetic-data engineering software, not a PHI-ready or production clinical platform.

## Relevant files

```text
src/clinical_data_platform/bulk.py
src/clinical_data_platform/ingestion.py
src/clinical_data_platform/registry.py
src/clinical_data_platform/database.py
src/clinical_data_platform/benchmark.py
src/clinical_data_platform/benchmark_cli.py
tests/test_bulk_loading.py
tests/test_benchmark.py
.github/workflows/benchmark.yml
```
