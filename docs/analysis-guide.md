# Repository analysis guide

This sequence is intended for reviewing the repository after running the bundled demonstration.

## 1. Inspect raw storage first

Run:

```powershell
clinical-data run-demo --repository-root .
```

Then inspect:

```text
data/raw/
├── objects/sha256/
└── receipts/
```

Questions:

- Does every receipt reference a content-addressed object?
- Does the object path contain the same SHA-256 recorded in the receipt?
- Are repeated identical source files deduplicated?
- Does every receipt still have a distinct UUID?
- Are raw artifacts excluded from Git?

Verify one receipt:

```powershell
clinical-data raw-verify `
  receipts/patients/<YYYY>/<MM>/<DD>/<uuid>.json `
  --raw-root data/raw
```

Read `src/clinical_data_platform/raw.py` and trace:

```text
source
→ initial hash
→ staging copy + second hash
→ atomic hard-link publication
→ read-only object
→ append-only receipt
```

## 2. Validate contracts

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract observations
```

Verify active versions, primary keys, referenced fields, measurement profiles, and 64-character hashes.

## 3. Inspect migration state

```powershell
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

A current database should report:

```text
detected=4
current=4
latest=4
pending=[]
```

Inspect:

```sql
SELECT
    version,
    name,
    checksum,
    execution_type,
    application_version,
    applied_at,
    execution_ms
FROM public.schema_migrations
ORDER BY version;
```

V004 should be `add_raw_landing_lineage`.

## 4. Test the V003 to V004 upgrade

On a disposable database:

```powershell
clinical-data database-migrate --target-version 3
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

At V003, `audit.pipeline_runs.raw_receipt_id` should not exist. At V004, all seven raw-lineage columns should exist.

## 5. Inspect processed outputs

Each dataset directory contains:

```text
valid_<dataset>.csv
invalid_<dataset>.csv
validation_errors.csv
quality_report.json
```

The report must include:

```text
input_sha256
raw_storage_version
raw_receipt_id
raw_received_at
raw_manifest_path
raw_manifest_sha256
raw_object_path
raw_size_bytes
contract_path
contract_version
contract_sha256
```

Confirm that the report’s `input_sha256` equals the raw object SHA-256, not merely a hash recalculated from the external source after validation.

## 6. Inspect module responsibilities

Recommended order:

1. `src/clinical_data_platform/raw.py`
2. `src/clinical_data_platform/contracts/manifest.toml`
3. versioned contract resources
4. `src/clinical_data_platform/contract.py`
5. migration resources V001–V004
6. `src/clinical_data_platform/migration.py`
7. `src/clinical_data_platform/pipeline.py`
8. `src/clinical_data_platform/registry.py`
9. `src/clinical_data_platform/database.py`
10. `src/clinical_data_platform/cohort.py`

Responsibility map:

```text
raw.py        → exact source bytes and receipt events
contracts     → accepted source interface
contract.py   → contract execution
migrations    → ordered database DDL
migration.py  → schema history, locking, execution
pipeline.py   → raw capture + validation orchestration
registry.py   → dataset persistence adapters
database.py   → lineage verification + transaction
cohort.py     → analytical derivation
```

## 7. Inspect PostgreSQL lineage

```sql
SELECT
    dataset_name,
    run_id,
    source_path,
    source_sha256,
    raw_receipt_id,
    raw_received_at,
    raw_storage_version,
    raw_manifest_path,
    raw_manifest_sha256,
    raw_object_path,
    raw_size_bytes,
    contract_path,
    contract_version,
    contract_sha256,
    rows_received,
    rows_valid,
    rows_invalid,
    validation_errors
FROM audit.pipeline_runs
ORDER BY loaded_at;
```

Normal v0.6 runs should not use `legacy/unmanaged` raw fields.

Clinical row counts after a clean demo:

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL
SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL
SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL
SELECT 'observations', COUNT(*) FROM clinical.observations;
```

Expected: 5, 7, 6, and 13.

## 8. Demonstrate raw deduplication

Capture the same source twice:

```powershell
clinical-data raw-capture patients data/sample/patients.csv --raw-root data/raw
clinical-data raw-capture patients data/sample/patients.csv --raw-root data/raw
```

Expected:

```text
same SHA-256
same object path
different receipt UUIDs
different receipt paths
```

This distinguishes content deduplication from event idempotency.

## 9. Test tamper detection

### Raw object

On a disposable copy of `data/raw`, modify one byte of an object and run `raw-verify`. Verification must fail with a checksum mismatch.

### Raw report lineage

Change `raw_manifest_sha256` in a copied `quality_report.json` and run `load-dataset`. Persistence must fail before opening the database write transaction.

### Contract lineage

Change `contract_sha256` and repeat. The historical contract verification must fail.

### Migration history

Change a checksum in `public.schema_migrations` and run `database-validate`. The database history must be rejected.

## 10. Inspect quality errors

```sql
SELECT
    p.dataset_name,
    p.contract_version,
    e.rule_name,
    COUNT(*) AS error_count
FROM audit.validation_errors AS e
JOIN audit.pipeline_runs AS p USING (run_id)
GROUP BY p.dataset_name, p.contract_version, e.rule_name
ORDER BY p.dataset_name, e.rule_name;
```

Rejected rows must remain in processed quarantine outputs, while the complete original file remains in raw storage.

## 11. Inspect cohort results

```sql
SELECT *
FROM analytics.hypertension_features
ORDER BY patient_id;
```

Expected patients: `P001` and `P002`.

Trace cohort sources back through:

```text
cohort_run_id
→ audit.cohort_source_runs
→ audit.pipeline_runs
→ raw receipt
→ raw object
```

## 12. Review tests

Read:

1. `tests/test_raw.py`
2. `tests/test_contracts.py`
3. `tests/test_migration.py`
4. `tests/test_pipeline.py`
5. `tests/test_database.py`
6. `tests/test_analysis_workflow.py`
7. `.github/workflows/ci.yml`

For every test, identify the failure mode it detects and the important failure it still does not cover.

## 13. Key design questions

- Why validate from the captured object rather than the external source?
- Why separate content objects from receipt manifests?
- Why is read-only not equivalent to WORM?
- Why does identical content produce one object but multiple receipts?
- Why verify raw lineage again before PostgreSQL?
- Why are raw, quarantine, and processed distinct layers?
- Why does V004 backfill `legacy/unmanaged` rather than invent receipts?
- What would change when moving from local filesystem to cloud object storage?
- Why are contracts, raw storage, migrations, and clinical snapshot history separate concerns?

## 14. Learning guides

- `docs/learning/generic-dataset-architecture-es.md`
- `docs/learning/versioned-executable-contracts-es.md`
- `docs/learning/database-migrations-es.md`
- `docs/learning/immutable-raw-landing-zone-es.md`

## 15. Known limitations

- local filesystem rather than durable object storage;
- no certified WORM retention;
- small synthetic dataset;
- four clinical entities;
- snapshot rather than historical clinical tables;
- limited terminology support;
- no PHI controls, authentication, or production monitoring;
- one demonstrative cohort.

These limitations remain explicit while the repository progresses toward version `1.0.0`.
