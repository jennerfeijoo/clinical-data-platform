# PostgreSQL COPY bulk loading

## Scope

The persistence layer uses PostgreSQL `COPY FROM STDIN` for validated clinical rows and validation errors. It improves transfer efficiency without bypassing clinical controls.

The governed loading benchmark compares this implementation with the former psycopg `executemany` path. Balanced reference evidence is documented in [`loading-benchmark.md`](loading-benchmark.md).

## Previous path

```text
validated CSV
→ list[dict]
→ list[tuple]
→ cursor.executemany()
→ repeated parameterized INSERT
→ clinical target
```

This was correct for small fixtures, but it retained both source records and converted tuples and used a row-oriented transfer route.

## Current path

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
temporary typed staging table
    │
    ▼
INSERT INTO clinical target
SELECT ... FROM staging
ON CONFLICT ...
    │
    ▼
target constraints, defaults, indexes, and triggers
```

The temporary table is created with:

```sql
CREATE TEMP TABLE <unique_name> ON COMMIT DROP AS
SELECT <load_columns>
FROM <clinical_target>
WITH NO DATA;
```

It inherits selected PostgreSQL data types but does not copy target constraints, indexes, defaults, or triggers.

## Why COPY does not write directly to the target

Direct COPY cannot express the required conflict policies.

The model needs:

```text
patients
→ current snapshot upsert
→ SCD Type 2 history

events
→ accept exact duplicate identity/content
→ reject same identity with different content
```

Staging separates efficient transfer from governed reconciliation:

```text
COPY
→ bulk transfer into staging

INSERT ... SELECT ... ON CONFLICT
→ target merge under clinical rules
```

## Target controls remain active

The merge writes to the real clinical tables. Therefore these controls execute normally:

```text
patients
→ record SHA-256 trigger
→ SCD Type 2 history trigger

coded entities
→ terminology resolution
→ normalized concept assignment

events
→ record hash
→ immutable conflict guard

all entities
→ foreign keys
→ check constraints
→ indexes
→ source-run lineage
```

The implementation does not disable triggers, alter `session_replication_role`, or copy directly into history tables.

## Declarative COPY plans

Each dataset has a `CopyMergePlan` defining:

```text
schema
table
ordered load columns
conflict columns
update columns
whether loaded_at is refreshed
```

The generic engine composes identifiers with `psycopg.sql.Identifier`.

Targets:

```text
clinical.patients
clinical.encounters
clinical.diagnoses
clinical.observations
clinical.medications
clinical.procedures
```

## Streaming boundary

Persistence uses two bounded-record-memory passes:

1. `inspect_csv_records()` validates headers and row structure and counts records.
2. `iter_csv_records()` reopens the file and yields one record at a time to the row builder and COPY writer.

Contract validation still materializes the complete source dataset. The streaming improvement applies to persistence, not yet to the whole pipeline.

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
    create temporary staging
    COPY clinical rows
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

Errors are copied directly into:

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

A repeated request returns before staging or row writes.

### Failed run

```text
failed
→ loading attempt N+1
→ completed or failed
```

Staging names include unique suffixes, avoiding session and attempt collisions.

### Exact duplicate event

The target trigger preserves the existing row and original lineage.

### Conflicting event

Reusing an identifier with different business content raises an error. The clinical transaction rolls back and the failure remains auditable.

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

Clinical rows are not intentionally logged.

## Rows copied versus rows merged

```text
rows_copied
→ rows transmitted into staging

rows_merged
→ target rows handled by INSERT ... SELECT ... ON CONFLICT
```

These values answer different questions and are retained separately.

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

## Balanced measured reference

The benchmark compares COPY with the former `executemany` path on actual governed targets.

| Clinical rows | COPY median | `executemany` median | Speedup | Time reduction |
|---:|---:|---:|---:|---:|
| 3,750 | 825.694 ms | 1,083.028 ms | 1.312× | 23.76% |
| 15,000 | 3,183.671 ms | 4,341.867 ms | 1.364× | 26.68% |
| 37,500 | 7,936.444 ms | 10,955.541 ms | 1.380× | 27.56% |

The protocol uses six measured repetitions, with each method starting first three times. These values apply only to the recorded environment and initial single-writer workload.

Evidence:

- [`loading-benchmark.md`](loading-benchmark.md);
- [`../benchmarks/loading/github-actions-run-30470147850/benchmark-summary.md`](../benchmarks/loading/github-actions-run-30470147850/benchmark-summary.md);
- [`learning/benchmark-carga-postgresql-es.md`](learning/benchmark-carga-postgresql-es.md).

## Benchmark safety

The benchmark truncates platform state between trials. Its CLI requires explicit destructive confirmation and refuses to begin when any table in `audit`, `clinical`, or `analytics` contains rows.

This safety gate belongs to benchmark execution, not ordinary dataset loading.

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
balanced method ordering
empty-database benchmark guard
committed benchmark evidence
Docker and package smoke tests
```

## Limitations

- COPY uses psycopg row adaptation with `write_row()`, not binary COPY.
- Contract validation still loads the complete input dataset into Python memory.
- Temporary staging is not analyzed because it exists for one short transaction.
- Parallel multi-dataset orchestration is not implemented.
- The benchmark covers initial single-writer loads up to 37,500 rows.
- Updates, concurrency, remote PostgreSQL, WAL volume, and peak memory are not measured.
- The repository remains synthetic-data engineering software, not a PHI-ready production clinical platform.

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
