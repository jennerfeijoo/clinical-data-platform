# Repository analysis guide

This sequence is intended for reviewing the repository after running the bundled demonstration.

## 1. Run the complete workflow

```powershell
clinical-data run-demo --repository-root .
```

The workflow captures six raw datasets, executes their contracts, migrates PostgreSQL through V006, persists accepted rows, and builds the hypertension cohort.

## 2. Verify migration state

```powershell
clinical-data database-status
clinical-data database-validate
```

Expected:

```text
detected=6
current=6
latest=6
pending=[]
```

Inspect:

```sql
SELECT version, name, checksum, execution_type, application_version, applied_at
FROM public.schema_migrations
ORDER BY version;
```

V006 should be `add_medications_and_procedures`.

## 3. Inspect active contracts

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract medications
clinical-data show-contract procedures
```

Confirm that all six active contracts use version `1.0.0`, have 64-character hashes, and match the registry order.

## 4. Inspect raw and processed layers

```text
data/raw/
├── objects/sha256/
└── receipts/

data/processed/<dataset>/
├── valid_<dataset>.csv
├── invalid_<dataset>.csv
├── validation_errors.csv
└── quality_report.json
```

For one medication receipt, verify:

```powershell
clinical-data raw-verify `
  receipts/medications/<YYYY>/<MM>/<DD>/<uuid>.json `
  --raw-root data/raw
```

The quality report must link the source hash, receipt, object, contract, run, reference date, and row counts.

## 5. Inspect six entity counts

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL SELECT 'observations', COUNT(*) FROM clinical.observations
UNION ALL SELECT 'medications', COUNT(*) FROM clinical.medications
UNION ALL SELECT 'procedures', COUNT(*) FROM clinical.procedures
ORDER BY dataset;
```

Expected counts:

```text
patients      5
encounters    7
diagnoses     6
observations 13
medications   6
procedures    6
```

## 6. Inspect medication conversion

```sql
SELECT
    medication_id,
    patient_id,
    encounter_id,
    code_system,
    medication_code,
    status,
    start_datetime,
    end_datetime,
    dose_value,
    dose_unit,
    route,
    record_sha256
FROM clinical.medications
ORDER BY medication_id;
```

For `M002`, confirm:

```text
end_datetime = NULL
dose_value = 500
dose_unit = mg
route = ORAL
```

This demonstrates conversion of optional CSV strings into typed PostgreSQL values.

## 7. Inspect procedure events

```sql
SELECT
    procedure_id,
    patient_id,
    encounter_id,
    code_system,
    procedure_code,
    procedure_datetime,
    status,
    record_sha256
FROM clinical.procedures
ORDER BY procedure_id;
```

Each record must reference an existing patient and encounter.

## 8. Review contract versus database enforcement

Medication contract rules include:

- expected columns;
- required values;
- data types;
- categorical status, route, and code-system names;
- start/end temporal order.

Database rules add:

- foreign keys;
- positive dose;
- paired dose value and unit;
- immutable identity/content behavior.

Create a contract-valid medication with a missing encounter and explain why validation succeeds but persistence fails.

## 9. Demonstrate immutable duplicates

Load the same medications file twice.

Verify:

```sql
SELECT medication_id, source_run_id, record_sha256
FROM clinical.medications
WHERE medication_id = 'M001';
```

The second receipt and pipeline run exist, but the original event and original `source_run_id` remain unchanged.

## 10. Demonstrate conflict rollback

Create a copy of `medications.csv` that changes `M001.status` from `COMPLETED` to `STOPPED` while retaining `medication_id = M001`.

The contract can accept the row, but loading must fail with:

```text
Immutable medication conflict
```

After failure verify:

- `M001` is unchanged;
- the conflicting `audit.pipeline_runs` row was rolled back;
- the raw receipt remains available;
- processed outputs remain available for investigation.

Repeat the same exercise for `PR001`, changing status to `IN_PROGRESS`.

## 11. Inspect patient history

```sql
SELECT
    patient_version_id,
    patient_id,
    record_sha256,
    valid_from_run_id,
    valid_to_run_id,
    valid_from,
    valid_to,
    is_current
FROM clinical.patient_history
ORDER BY patient_id, patient_version_id;
```

Confirm that exactly one current version exists per accepted patient.

## 12. Compare identities

For one medication load identify:

```text
source_sha256       → raw CSV bytes
raw_manifest_sha256 → receipt JSON bytes
contract_sha256     → executable contract bytes
run_id              → one pipeline execution
record_sha256       → normalized medication content
```

Explain why a new receipt can create a new run without changing `record_sha256`.

## 13. Inspect cohort stability

```sql
SELECT *
FROM analytics.hypertension_features
ORDER BY patient_id;
```

Expected patients remain `P001` and `P002`. Adding medications and procedures must not silently alter the existing cohort definition.

## 14. Review code in this order

1. `contracts/manifest.toml`;
2. medication and procedure contracts;
3. `registry.py` row builders and SQL;
4. V006 migration;
5. `history.py`;
6. `tests/test_additional_entities.py`;
7. `tests/test_migration.py`;
8. `tests/test_analysis_workflow.py`.

For each component identify its responsibility and what it deliberately does not do.

## 15. Key design questions

- Why did adding two entities not require changes to `pipeline.py`?
- Why are medication and procedure corrections rejected rather than overwritten?
- Why is dose pairing enforced in PostgreSQL rather than only in the source contract?
- Why does `code_system` not prove terminology correctness?
- Why do medications and procedures require both patient and encounter foreign keys?
- What would be required to add allergies as a seventh entity?

## 16. Known limitations

- local filesystem rather than durable object storage;
- small synthetic fixtures;
- code-system labels without terminology reference tables;
- no complete execution-state audit or structured logging;
- no Synthea generation;
- no bulk `COPY` or performance benchmark;
- one demonstrative cohort;
- no PHI controls or production deployment claims.
