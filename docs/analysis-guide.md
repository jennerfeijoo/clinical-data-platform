# Repository analysis guide

This guide is intended for reviewing the repository after running the bundled demonstration.

## 1. Validate contracts

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract observations
```

Verify that:

- every registered dataset has one active manifest entry;
- versions follow semantic versioning;
- each contract has a 64-character SHA-256;
- primary keys are declared, required, and unique;
- temporal and measurement references resolve to declared columns.

## 2. Inspect database migration state

Before loading data:

```powershell
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

A current fresh database should report:

```text
managed=True
detected=3
current=3
latest=3
pending=[]
```

Inspect history:

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

Questions:

- Are versions contiguous from V001?
- Do names correspond to packaged filenames?
- Are checksums 64 characters?
- Were versions executed as `migration` or adopted as `baseline`?
- Does `application_version` identify the package that recorded them?

## 3. Test a managed upgrade

On a disposable database:

```powershell
clinical-data database-migrate --target-version 1
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

At V001, verify that `clinical.patients` exists but `clinical.encounters` does not. After the final migration, verify that all clinical and cohort tables exist and `audit.pipeline_runs` includes contract-lineage columns.

This distinguishes fresh-install testing from upgrade testing.

## 4. Understand baseline behavior

A database created before migration history is not adopted automatically.

After reviewing a recognized legacy development database:

```powershell
clinical-data database-migrate --baseline-existing
```

Then inspect:

```sql
SELECT version, execution_type
FROM public.schema_migrations
ORDER BY version;
```

Baseline records indicate recognition of existing structure, not replay of historical SQL. Partial structures must be rejected.

## 5. Run the complete workflow

PowerShell:

```powershell
.\scripts\run_demo.ps1
```

POSIX shell:

```bash
sh scripts/run_demo.sh
```

The workflow migrates PostgreSQL, validates four contract-governed datasets, loads valid rows and errors, builds the hypertension cohort, and exports analysis-ready features.

## 6. Inspect file-level quality outputs

```text
data/processed/
├── patients/
├── encounters/
├── diagnoses/
└── observations/
```

Each directory contains:

```text
valid_<dataset>.csv
invalid_<dataset>.csv
validation_errors.csv
quality_report.json
```

Review:

- preservation of rejected rows;
- linkage from each error to row, entity, patient, field, rule, and value;
- consistency between report counts and CSV files;
- source and contract SHA-256 values;
- retained contract resource path;
- reported contract version.

## 7. Inspect architecture in order

Read:

1. `src/clinical_data_platform/contracts/manifest.toml`
2. contract resources under `src/clinical_data_platform/contracts/`
3. `src/clinical_data_platform/contract.py`
4. migration resources under `src/clinical_data_platform/migrations/`
5. `src/clinical_data_platform/migration.py`
6. `src/clinical_data_platform/models.py`
7. `src/clinical_data_platform/registry.py`
8. `src/clinical_data_platform/pipeline.py`
9. `src/clinical_data_platform/database.py`
10. `src/clinical_data_platform/cohort.py`

Responsibility map:

```text
contracts     → accepted source data
contract.py   → contract parsing and execution
migrations    → ordered database DDL history
migration.py  → discovery, locking, history, baseline, execution
pipeline.py   → validation orchestration and file outputs
registry.py   → typed persistence adapters
database.py   → transactional dataset persistence
cohort.py     → analytical derivation
```

## 8. Inspect PostgreSQL content

Open a shell:

```bash
docker compose exec postgres psql -U clinical_user -d clinical_data
```

### Clinical row counts

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL
SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL
SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL
SELECT 'observations', COUNT(*) FROM clinical.observations;
```

Expected after a clean demo:

| Dataset | Rows |
|---|---:|
| patients | 5 |
| encounters | 7 |
| diagnoses | 6 |
| observations | 13 |

### Source and contract lineage

```sql
SELECT
    dataset_name,
    run_id,
    source_sha256,
    contract_path,
    contract_version,
    contract_sha256,
    rows_received,
    rows_valid,
    rows_invalid,
    validation_errors,
    loaded_at
FROM audit.pipeline_runs
ORDER BY loaded_at;
```

Normal runs should contain a retained contract path, contract version `1.0.0`, and nonzero source and contract hashes.

### Rejected-data profile

```sql
SELECT
    p.dataset_name,
    p.contract_version,
    e.rule_name,
    COUNT(*) AS error_count
FROM audit.validation_errors AS e
JOIN audit.pipeline_runs AS p USING (run_id)
GROUP BY p.dataset_name, p.contract_version, e.rule_name
ORDER BY p.dataset_name, p.contract_version, e.rule_name;
```

## 9. Test tamper detection

### Contract lineage tampering

Alter one character of `contract_sha256` in a copied `quality_report.json`, then run:

```powershell
clinical-data load-dataset patients `
  --output-dir data/processed/patients
```

The loader should reject the bundle before clinical persistence.

### Migration checksum tampering

On a disposable database, modify a checksum in `public.schema_migrations` and execute:

```powershell
clinical-data database-validate
```

The migrator should reject the history because packaged SQL no longer matches the recorded checksum.

Restore or reset the database after the exercise.

## 10. Inspect the analytical cohort

```sql
SELECT *
FROM analytics.hypertension_features
ORDER BY patient_id;
```

Expected patients are `P001` and `P002`.

Inspect cohort lineage:

```sql
SELECT
    c.cohort_run_id,
    c.cohort_name,
    c.definition_version,
    c.parameters,
    c.row_count,
    p.dataset_name,
    p.contract_version,
    s.source_run_id
FROM audit.cohort_runs AS c
JOIN audit.cohort_source_runs AS s USING (cohort_run_id)
JOIN audit.pipeline_runs AS p ON p.run_id = s.source_run_id
ORDER BY c.generated_at, p.dataset_name;
```

## 11. Inspect exported files

```text
data/analytics/
├── hypertension_features.csv
└── hypertension_cohort_metadata.json
```

The CSV is analysis-ready. The JSON records cohort definition version, parameters, source runs, row count, and generation time.

## 12. Review tests

Recommended order:

1. `tests/test_contracts.py`
2. `tests/test_migration.py`
3. `tests/test_pipeline.py`
4. `tests/test_database.py`
5. `tests/test_analysis_workflow.py`
6. `.github/workflows/ci.yml`

For each test ask:

```text
What failure is this test designed to detect?
What database state does it assume?
Does it test fresh install, upgrade, baseline, or steady state?
What important failure is still untested?
```

## 13. Key design questions

- Why is active contract selection explicit rather than automatic?
- Why store semantic version and SHA-256 for contracts?
- Why are contract SQL and migration SQL separate?
- Why does migration history use checksums?
- Why are applied migrations immutable?
- Why is baseline explicit?
- Why are downgrades not automated?
- What does the advisory lock protect?
- Why is `public.schema_migrations` outside `audit`?
- When would Alembic, Flyway, or Liquibase be preferable?
- Is snapshot upsert sufficient, or is historical row versioning required?

## 14. Learning guides

- `docs/learning/generic-dataset-architecture-es.md`
- `docs/learning/versioned-executable-contracts-es.md`
- `docs/learning/database-migrations-es.md`

## 15. Known limitations

- small synthetic dataset;
- four clinical entities;
- purpose-built contract rule language;
- purpose-built migration engine;
- snapshot rather than historical clinical storage;
- limited terminology support;
- no immutable raw layer;
- no authentication or PHI handling;
- no production monitoring or alerting;
- one demonstrative cohort.

These limitations remain explicit while the repository progresses toward version `1.0.0`.
