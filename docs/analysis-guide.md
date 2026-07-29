# Repository analysis guide

This sequence is intended for reviewing the repository after running the bundled demonstration.

## 1. Run the complete workflow

```powershell
clinical-data run-demo --repository-root .
```

The workflow captures raw data, validates contracts, migrates PostgreSQL through V005, persists clinical data, and builds the hypertension cohort.

## 2. Inspect raw storage

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

Trace:

```text
source
→ initial hash
→ staging copy + second hash
→ atomic hard-link publication
→ read-only object
→ append-only receipt
```

## 3. Validate contracts

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract observations
```

Verify active versions, primary keys, referenced fields, measurement profiles, and 64-character hashes.

## 4. Inspect migration state

```powershell
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

A current database should report:

```text
detected=5
current=5
latest=5
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

V005 should be `add_clinical_history_policy`.

## 5. Test the V004 to V005 upgrade

On a disposable database:

```powershell
clinical-data database-migrate --target-version 4
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

At V004:

```text
clinical.patient_history does not exist
record_sha256 does not exist on clinical tables
```

At V005:

```text
clinical.patient_history exists
record_sha256 exists on patients, encounters, diagnoses, observations
history and immutable-event triggers exist
```

## 6. Inspect processed outputs

Each dataset directory contains:

```text
valid_<dataset>.csv
invalid_<dataset>.csv
validation_errors.csv
quality_report.json
```

The report must include raw and contract lineage:

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

Confirm that `input_sha256` equals the captured raw object SHA-256.

## 7. Inspect module responsibilities

Recommended order:

1. `src/clinical_data_platform/raw.py`
2. `src/clinical_data_platform/contracts/manifest.toml`
3. versioned contract resources
4. `src/clinical_data_platform/contract.py`
5. migration resources V001–V005
6. `src/clinical_data_platform/migration.py`
7. `src/clinical_data_platform/history.py`
8. `src/clinical_data_platform/pipeline.py`
9. `src/clinical_data_platform/registry.py`
10. `src/clinical_data_platform/database.py`
11. `src/clinical_data_platform/cohort.py`

Responsibility map:

```text
raw.py        → exact source bytes and receipt events
contracts     → accepted source interface
contract.py   → contract execution
migrations    → ordered database DDL
migration.py  → schema history, locking, execution
history.py    → declared snapshot/event semantics
pipeline.py   → raw capture + validation orchestration
registry.py   → typed persistence adapters
database.py   → lineage verification + transaction
PostgreSQL    → hashes, SCD2, immutable-event enforcement
cohort.py     → analytical derivation
```

## 8. Inspect PostgreSQL run lineage

```sql
SELECT
    dataset_name,
    run_id,
    source_path,
    source_sha256,
    raw_receipt_id,
    raw_received_at,
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

Normal v0.7 runs should not use `legacy/unmanaged` raw fields.

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

## 9. Inspect current patient snapshots

```sql
SELECT
    patient_id,
    sex_at_birth,
    birth_date,
    death_date,
    source_run_id,
    source_sha256,
    record_sha256,
    loaded_at
FROM clinical.patients
ORDER BY patient_id;
```

Check that each `record_sha256` has 64 hexadecimal characters.

## 10. Inspect patient history

```sql
SELECT
    patient_version_id,
    patient_id,
    sex_at_birth,
    birth_date,
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

After one clean demo, every accepted patient should have one current version.

Validate the invariant:

```sql
SELECT patient_id, COUNT(*) AS current_versions
FROM clinical.patient_history
WHERE is_current
GROUP BY patient_id
HAVING COUNT(*) <> 1;
```

Expected result: zero rows.

## 11. Demonstrate SCD Type 2 behavior

Create a valid modified copy of `patients.csv`, changing one accepted P001 business field. Validate and load it into a new output directory.

Then inspect P001:

```sql
SELECT
    patient_id,
    sex_at_birth,
    valid_from_run_id,
    valid_to_run_id,
    valid_from,
    valid_to,
    is_current,
    record_sha256
FROM clinical.patient_history
WHERE patient_id = 'P001'
ORDER BY patient_version_id;
```

Expected:

```text
old version: is_current=false, valid_to populated
new version: is_current=true, valid_to NULL
record hashes differ
transition run closes and opens the versions
```

Reloading an identical snapshot should not add a version.

## 12. Demonstrate immutable events

Inspect an event:

```sql
SELECT
    encounter_id,
    encounter_type,
    source_run_id,
    record_sha256,
    loaded_at
FROM clinical.encounters
WHERE encounter_id = 'E001';
```

Load the identical encounter file again. The original event lineage should remain unchanged.

Next, change `encounter_type` while keeping `encounter_id = E001`. Contract validation may pass, but persistence must fail with an immutable-event conflict.

After failure verify:

```text
E001 is unchanged
the conflicting audit.pipeline_runs row was rolled back
raw receipt and processed outputs still exist
```

This separates source capture from accepted clinical state.

## 13. Compare the four hashes

For one patient run, identify:

```text
source_sha256       → raw CSV bytes
raw_manifest_sha256 → receipt JSON bytes
contract_sha256     → contract bytes
record_sha256       → normalized row business content
```

Explain why a new receipt can change run lineage without changing a patient business hash.

## 14. Test tamper detection

### Raw object

Modify one byte of an object in a disposable raw copy and run `raw-verify`. Verification must fail.

### Quality-report raw lineage

Change `raw_manifest_sha256` in a copied `quality_report.json` and run `load-dataset`. Persistence must fail before the database transaction.

### Contract lineage

Change `contract_sha256`; historical contract verification must fail.

### Migration history

Change a checksum in `public.schema_migrations` and run `database-validate`; migration history must be rejected.

## 15. Inspect quality errors

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

Rejected rows remain in processed quarantine outputs, while the complete source remains in raw storage.

## 16. Inspect cohort results

```sql
SELECT *
FROM analytics.hypertension_features
ORDER BY patient_id;
```

Expected patients: `P001` and `P002`.

Trace cohort sources:

```text
cohort_run_id
→ audit.cohort_source_runs
→ audit.pipeline_runs
→ raw receipt
→ raw object
```

The cohort currently uses the latest patient snapshot and immutable accepted events.

## 17. Review tests

Read:

1. `tests/test_raw.py`
2. `tests/test_contracts.py`
3. `tests/test_migration.py`
4. `tests/test_pipeline.py`
5. `tests/test_database.py`
6. `tests/test_history.py`
7. `tests/test_analysis_workflow.py`
8. `.github/workflows/ci.yml`

For every test identify:

```text
What failure is detected?
What database state is assumed?
Is this testing raw, contract, migration, snapshot, or event semantics?
What important failure remains untested?
```

## 18. Key design questions

- Why validate from the captured object rather than the external source?
- Why separate content objects from receipt manifests?
- Why is read-only not equivalent to WORM?
- Why store both source and record hashes?
- Why does patient data use SCD2?
- Why are encounters, diagnoses, and observations immutable events?
- Why does an exact event duplicate preserve original lineage?
- Why is a conflicting event rejected rather than overwritten?
- Why is this not full bitemporal modelling?
- How should medications and procedures declare their history policy?

## 19. Learning guides

- `docs/learning/generic-dataset-architecture-es.md`
- `docs/learning/versioned-executable-contracts-es.md`
- `docs/learning/database-migrations-es.md`
- `docs/learning/immutable-raw-landing-zone-es.md`
- `docs/learning/clinical-history-policy-es.md`

## 20. Known limitations

- local filesystem rather than durable object storage;
- no certified WORM retention;
- small synthetic dataset;
- four clinical entities;
- patient SCD2 but no bitemporal valid-time model;
- no tombstones, supersession, or identity merge semantics;
- limited terminology support;
- no PHI controls, authentication, or production monitoring;
- one demonstrative cohort.

These limitations remain explicit while the repository progresses toward version `1.0.0`.
