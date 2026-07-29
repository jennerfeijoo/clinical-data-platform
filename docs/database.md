# PostgreSQL migrations and persistence

## Responsibility split

```text
raw.py
    → preserves and verifies exact source bytes

migration.py
    → creates and upgrades database structure

history.py
    → declares clinical history semantics

database.py
    → verifies lineage and persists validated outputs

PostgreSQL triggers
    → enforce SCD2 and immutable-event rules
```

Dataset loading code does not create tables, and raw storage code does not write clinical rows.

## Formal migration history

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
├── V004__add_raw_landing_lineage.sql
└── V005__add_clinical_history_policy.sql
```

`public.schema_migrations` records version, name, checksum, timestamp, execution time, execution type, and application version.

Applied migrations are immutable. Schema corrections are introduced through a new migration.

## V004 raw lineage

V004 adds receipt and content-object fields to `audit.pipeline_runs`. `source_sha256` remains the hash of the captured raw object. Older rows receive explicit `legacy/unmanaged` markers rather than fabricated receipts.

## V005 clinical history

V005 introduces an explicit hybrid policy.

### Patient snapshots

```text
clinical.patients
    → current accepted snapshot

clinical.patient_history
    → SCD Type 2 history
```

`clinical.patient_history` stores:

```text
patient_version_id
patient_id
demographic attributes
record_sha256
valid_from_run_id
valid_to_run_id
source_sha256
valid_from
valid_to
is_current
```

A partial unique index guarantees at most one `is_current = true` version per patient.

### Immutable events

These tables are append-only by identity:

```text
clinical.encounters
clinical.diagnoses
clinical.observations
```

An exact duplicate preserves the original row and original `source_run_id`. Reusing the same event identifier with different normalized content raises an integrity error and rolls back the complete load transaction.

### Record hashes

Every clinical current table has `record_sha256`. PostgreSQL calculates the hash from normalized business content through functions installed by V005.

The hash excludes:

```text
source_run_id
source_sha256
loaded_at
```

Those fields describe lineage, not clinical meaning. Event timestamps are converted to UTC before hashing.

## Fresh install and upgrade

Fresh installation:

```text
0 → V001 → V002 → V003 → V004 → V005
```

Upgrade from the previous milestone:

```powershell
clinical-data database-migrate --target-version 4
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

At V004, `clinical.patient_history` and clinical `record_sha256` columns do not exist. V005 backfills hashes for existing rows, creates one current history row per existing patient, and installs enforcement triggers.

Recognized complete unmanaged schemas may be adopted only through explicit baseline. Partial V005 structures are rejected.

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
- transactionally coupled DDL and history rows;
- complete V005 table and hash-column signatures.

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

Before opening the database write transaction, `database.py` validates:

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

## Transaction behavior

One validated run writes in one transaction:

```text
pipeline run metadata
+
valid clinical rows
+
validation errors
+
history transitions or immutable-event checks
```

All commit or all roll back.

The raw object and receipt exist before this transaction. A database rollback does not delete them; source capture is an earlier durable stage.

## Patient transaction examples

### New patient

```text
insert current snapshot
→ calculate record hash
→ insert current history version
→ commit
```

### Identical snapshot

```text
upsert patient
→ same business hash
→ refresh current snapshot lineage
→ no new history version
```

The current history version identifies the run that established that business state. The current table may identify a later run that reconfirmed it.

### Changed snapshot

```text
upsert patient
→ new business hash
→ close old history version
→ insert new current version
→ update current snapshot
```

`valid_to_run_id` and the new `valid_from_run_id` both identify the transition-producing run.

## Immutable-event transaction examples

### Exact duplicate

```text
same event ID
+ same record hash
→ trigger returns OLD
→ original event and lineage remain unchanged
```

The new pipeline run is still auditable as a receipt and validation event, even though the clinical event is not rewritten.

### Conflicting identity

```text
same event ID
+ different record hash
→ PostgreSQL integrity error
→ audit.pipeline_runs insertion rolls back
→ event remains unchanged
```

## Idempotency layers

```text
raw object deduplication
    keyed by source SHA-256

receipt append-only behavior
    one UUID per reception

run-level database idempotency
    keyed by run_id

patient history idempotency
    keyed by business record hash transition

immutable-event idempotency
    keyed by event identity + matching content hash
```

## Query examples

Migration history:

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

Current patients:

```sql
SELECT
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    record_sha256,
    source_run_id
FROM clinical.patients
ORDER BY patient_id;
```

Patient versions:

```sql
SELECT
    patient_id,
    sex_at_birth,
    death_date,
    record_sha256,
    valid_from_run_id,
    valid_to_run_id,
    valid_from,
    valid_to,
    is_current
FROM clinical.patient_history
ORDER BY patient_id, patient_version_id;
```

Current-version invariant:

```sql
SELECT patient_id, COUNT(*)
FROM clinical.patient_history
WHERE is_current
GROUP BY patient_id
HAVING COUNT(*) <> 1;
```

Expected result: zero rows.

Event lineage:

```sql
SELECT
    encounter_id,
    patient_id,
    record_sha256,
    source_run_id,
    loaded_at
FROM clinical.encounters
ORDER BY encounter_id;
```

## Operational commands

```powershell
clinical-data raw-capture
clinical-data raw-verify
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
clinical-data load-dataset
```

## Limits

The current policy is not a complete clinical correction model. It does not implement tombstones, event supersession, patient identity merge/split, or separate clinical valid time and system time. Those semantics must be designed explicitly rather than inferred from generic updates.
