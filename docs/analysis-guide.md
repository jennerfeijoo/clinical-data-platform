# Repository analysis guide

This guide is intended for reviewing the repository after running the bundled demonstration.

## 1. Validate the contract layer

Before processing data, inspect the active contract set:

```powershell
clinical-data list-contracts
clinical-data validate-contracts
clinical-data show-contract observations
```

Verify that:

- every registered dataset has one active manifest entry;
- every active version follows semantic versioning;
- every contract has a 64-character SHA-256;
- the primary key is declared, required, and unique;
- referenced temporal and measurement fields exist;
- observation profile codes match the allowed observation codes.

## 2. Run the complete workflow

PowerShell:

```powershell
.\scripts\run_demo.ps1
```

POSIX shell:

```bash
sh scripts/run_demo.sh
```

The workflow validates four contract-governed datasets, loads PostgreSQL, builds the hypertension cohort, and exports analysis-ready features.

## 3. Inspect file-level quality outputs

Review each directory under `data/processed/`:

```text
data/processed/
├── patients/
├── encounters/
├── diagnoses/
└── observations/
```

Each directory contains valid rows, rejected rows, structured validation errors, and a JSON quality report.

Questions to evaluate:

- Are rejected records preserved?
- Can every error be linked to a row, entity, patient, field, rule, and rejected value?
- Do reported counts match the generated files?
- Does each report include source and contract checksums?
- Does `contract_path` identify a retained versioned resource?
- Does the reported contract hash match `show-contract`?

## 4. Inspect the contract architecture

Read these files in order:

1. `src/clinical_data_platform/contracts/manifest.toml`
2. `src/clinical_data_platform/contracts/patients/v1.0.0.toml`
3. `src/clinical_data_platform/contracts/observations/v1.0.0.toml`
4. `src/clinical_data_platform/contract.py`
5. `src/clinical_data_platform/models.py`
6. `src/clinical_data_platform/registry.py`
7. `src/clinical_data_platform/pipeline.py`
8. `src/clinical_data_platform/database.py`

The separation is intentional:

- contracts describe accepted data and executable rules;
- `contract.py` parses and executes those rules;
- `models.py` defines normalized results;
- `registry.py` retains persistence adapters;
- `pipeline.py` performs invariant orchestration;
- `database.py` verifies contract lineage and writes atomically.

The central review questions are:

```text
What belongs in a contract?
What remains controlled code?
How is a historical run reproduced after the active contract changes?
```

See `docs/learning/versioned-executable-contracts-es.md` for the detailed Spanish study guide and exercises.

## 5. Inspect PostgreSQL

Open a database shell:

```bash
docker compose exec postgres psql -U clinical_user -d clinical_data
```

### Row counts

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL
SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL
SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL
SELECT 'observations', COUNT(*) FROM clinical.observations;
```

Expected counts after a clean demo:

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

Expected active contract version:

```text
1.0.0
```

Each normal run should contain a non-legacy contract path and a nonzero contract hash.

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

## 6. Test contract tamper detection

Copy a generated `quality_report.json` and alter one character in `contract_sha256`.

Then run:

```powershell
clinical-data load-dataset patients `
  --output-dir data/processed/patients `
  --schema sql/schema.sql
```

The loader should reject the bundle because the reported hash no longer matches the bytes of the referenced contract.

Restore the original report before continuing.

## 7. Inspect the analytical cohort

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

## 8. Inspect exported analysis files

```text
data/analytics/
├── hypertension_features.csv
└── hypertension_cohort_metadata.json
```

The CSV is the analysis-ready table. The JSON file records the cohort definition version, parameters, source runs, row count, and generation time.

## 9. Review engineering decisions

Recommended full review order:

1. `docs/architecture.md`
2. `docs/learning/generic-dataset-architecture-es.md`
3. `docs/learning/versioned-executable-contracts-es.md`
4. contract resources under `src/clinical_data_platform/contracts/`
5. `src/clinical_data_platform/contract.py`
6. `src/clinical_data_platform/models.py`
7. `src/clinical_data_platform/registry.py`
8. `src/clinical_data_platform/pipeline.py`
9. `src/clinical_data_platform/database.py`
10. `sql/schema.sql`
11. `sql/cohorts/hypertension.sql`
12. `tests/test_contracts.py`
13. `tests/test_pipeline.py`
14. `tests/test_database.py`
15. `tests/test_analysis_workflow.py`
16. `.github/workflows/ci.yml`

Key design questions:

- Why is the active version selected by a manifest?
- Why are published contract files retained?
- Why store both semantic version and SHA-256?
- Why does SQL remain in Python rather than TOML?
- Which validation rules are general enough for the contract engine?
- Which checks still belong in PostgreSQL?
- What would make a contract change backward-incompatible?
- How should database migrations align with contract versions?
- Is run-level idempotency sufficient, or should content-level deduplication also be implemented?
- What additional observability would be required in production?

## 10. Known limitations

- small synthetic dataset;
- only four clinical entities;
- purpose-built contract rule language rather than a general schema standard;
- no formal database migration framework;
- limited terminology support;
- no authentication or authorization;
- no PHI handling;
- no orchestration engine;
- no production monitoring or alerting;
- one demonstrative cohort rather than a generic cohort-definition language.

These constraints remain explicit while the repository progresses toward a defensible version `1.0.0`.
