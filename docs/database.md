# PostgreSQL migrations and persistence

## Responsibility split

```text
raw.py
    → preserves and verifies exact source bytes

migration.py
    → creates and upgrades database structure

database.py
    → verifies lineage and persists validated outputs
```

Dataset loading code does not create tables, and raw storage code does not write clinical rows.

## Formal migration history

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
└── V004__add_raw_landing_lineage.sql
```

`public.schema_migrations` records version, name, checksum, timestamp, execution time, execution type, and application version.

Applied migrations are immutable. Schema corrections are introduced through a new migration.

## V004 raw lineage

V004 adds these fields to `audit.pipeline_runs`:

```text
raw_receipt_id
raw_received_at
raw_storage_version
raw_manifest_path
raw_manifest_sha256
raw_object_path
raw_size_bytes
```

`source_sha256` remains the hash of the captured raw object. The new fields identify the receipt event and physical content address.

Rows created before V004 receive explicit legacy values:

```text
raw_receipt_id = zero UUID
raw_storage_version = legacy/unmanaged
raw_manifest_path = legacy/unmanaged
raw_manifest_sha256 = 64 zeros
raw_object_path = legacy/unmanaged
raw_size_bytes = 0
```

The migration does not fabricate a historical receipt that never existed.

## Fresh install and upgrade

Fresh installation:

```text
0 → V001 → V002 → V003 → V004
```

Upgrade test:

```powershell
clinical-data database-migrate --target-version 3
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

The expected pending version at the intermediate state is V004.

Recognized complete unmanaged schemas may be adopted only through explicit baseline. Partial structures are rejected.

## Migration guarantees

The engine checks:

- `VNNN__name.sql` filenames;
- contiguous versions from V001;
- unique names;
- immutable SHA-256 checksums;
- applied-history continuity;
- detected structure versus recorded version;
- no downgrade;
- advisory-lock serialization;
- transactionally coupled DDL and history rows.

## Dataset persistence API

```python
persist_dataset_validation_outputs(
    connection,
    dataset,
    output_directory,
    raw_root=raw_root,
)
```

`raw_root` is required because persistence reopens and verifies the immutable receipt and object referenced by `quality_report.json`.

## Pre-transaction verification

Before opening the database write transaction, `database.py` validates four groups.

### Output bundle

- dataset identity;
- valid, invalid, and error counts;
- completed status;
- parseable UUIDs and dates.

### Contract lineage

- retained contract exists;
- dataset matches;
- semantic version matches;
- contract SHA-256 matches.

### Raw receipt lineage

- storage version is supported;
- receipt path is safe and deterministic;
- receipt JSON is valid;
- receipt UUID and timestamp match;
- receipt manifest SHA-256 matches the report.

### Raw object lineage

- object path is derived from SHA-256;
- object exists under `raw_root`;
- byte size matches;
- recalculated SHA-256 equals `input_sha256`.

Any inconsistency prevents the database transaction from starting.

## Persisted lineage

A normal `audit.pipeline_runs` row links:

```text
run_id
├── external source_path
├── raw receipt UUID and timestamp
├── raw receipt path and SHA-256
├── raw object path, SHA-256, and size
├── contract path, version, and SHA-256
├── reference date
├── quality counts
└── execution timestamps
```

Each clinical row retains:

```text
source_run_id
source_sha256
loaded_at
```

The join through `source_run_id` exposes the complete raw and contract lineage.

## Query examples

Inspect current migration history:

```sql
SELECT
    version,
    name,
    checksum,
    execution_type,
    application_version,
    applied_at
FROM public.schema_migrations
ORDER BY version;
```

Inspect raw lineage:

```sql
SELECT
    dataset_name,
    run_id,
    raw_receipt_id,
    raw_received_at,
    raw_storage_version,
    raw_manifest_path,
    raw_manifest_sha256,
    raw_object_path,
    raw_size_bytes,
    source_sha256
FROM audit.pipeline_runs
ORDER BY loaded_at;
```

Find repeated content receipts:

```sql
SELECT
    dataset_name,
    source_sha256,
    COUNT(*) AS run_count,
    COUNT(DISTINCT raw_receipt_id) AS receipt_count
FROM audit.pipeline_runs
GROUP BY dataset_name, source_sha256
HAVING COUNT(*) > 1;
```

## Transaction behavior

One validated run writes in one transaction:

```text
pipeline run metadata
+
valid clinical rows
+
validation errors
```

All commit or all roll back.

The raw object and receipt exist before this transaction. A database rollback does not delete them; source capture is an earlier durable stage.

## Idempotency and deduplication

These are distinct:

```text
raw object deduplication
    keyed by source SHA-256

receipt append-only behavior
    one UUID per reception

run-level database idempotency
    keyed by run_id

clinical snapshot upsert
    keyed by clinical entity identifier
```

Identical bytes may produce several receipts and several validation runs while still occupying one raw object.

## Current snapshot boundary

Clinical entity tables still represent the latest snapshot through upserts. Raw storage preserves every source receipt, but it does not yet provide SCD Type 2 history for transformed clinical records. Historical record versioning is the next separate milestone.

## Operational commands

```powershell
clinical-data raw-capture
clinical-data raw-verify
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
clinical-data load-dataset
```

## Limitations

The local filesystem implementation does not provide certified WORM retention, replication, cloud IAM, encryption policy, or administrator-resistant immutability. Those controls belong to a production object-storage deployment, not to PostgreSQL lineage alone.
