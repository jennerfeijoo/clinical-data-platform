# Repository analysis guide

This guide is intended for reviewing the repository after running the bundled demonstration.

## 1. Run the complete workflow

PowerShell:

```powershell
.\scripts\run_demo.ps1
```

POSIX shell:

```bash
sh scripts/run_demo.sh
```

The workflow validates four datasets, loads PostgreSQL, builds the hypertension cohort, and exports analysis-ready features.

## 2. Inspect file-level quality outputs

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
- Can every error be linked to a row, field, rule, and rejected value?
- Do reported counts match the generated files?
- Does each report include a run UUID and source checksum?

## 3. Inspect PostgreSQL

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

### Pipeline lineage

```sql
SELECT
    dataset_name,
    run_id,
    source_sha256,
    rows_received,
    rows_valid,
    rows_invalid,
    validation_errors,
    loaded_at
FROM audit.pipeline_runs
ORDER BY loaded_at;
```

### Rejected-data profile

```sql
SELECT
    p.dataset_name,
    e.rule_name,
    COUNT(*) AS error_count
FROM audit.validation_errors AS e
JOIN audit.pipeline_runs AS p USING (run_id)
GROUP BY p.dataset_name, e.rule_name
ORDER BY p.dataset_name, e.rule_name;
```

## 4. Inspect the analytical cohort

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
    s.source_run_id
FROM audit.cohort_runs AS c
JOIN audit.cohort_source_runs AS s USING (cohort_run_id)
JOIN audit.pipeline_runs AS p ON p.run_id = s.source_run_id
ORDER BY c.generated_at, p.dataset_name;
```

## 5. Inspect exported analysis files

```text
data/analytics/
├── hypertension_features.csv
└── hypertension_cohort_metadata.json
```

The CSV is the analysis-ready table. The JSON file records its definition version, parameters, source runs, row count, and generation time.

## 6. Review engineering decisions

Recommended review order:

1. `docs/architecture.md`
2. `docs/data-contracts/`
3. `src/clinical_data_platform/clinical_entities.py`
4. `src/clinical_data_platform/entity_pipeline.py`
5. `src/clinical_data_platform/entity_database.py`
6. `sql/schema.sql`
7. `sql/cohorts/hypertension.sql`
8. `src/clinical_data_platform/cohort.py`
9. `tests/test_analysis_workflow.py`
10. `.github/workflows/ci.yml`

Key design questions:

- Which checks belong in Python and which belong in PostgreSQL?
- Is run-level idempotency sufficient, or should content-level deduplication also be implemented?
- Should cohort outputs be snapshots, views, or materialized views?
- How should schema migrations be handled once the model evolves?
- How would controlled vocabularies and unit conversion be introduced?
- What additional observability would be required in production?

## 7. Known limitations

- tiny synthetic dataset;
- only four clinical entities;
- limited terminology support;
- no authentication or authorization;
- no PHI handling;
- no orchestration engine;
- no migration framework;
- no production monitoring or alerting;
- one demonstrative cohort rather than a generic cohort-definition language.

These constraints are explicit so the repository demonstrates a complete, reviewable MVP without claiming production clinical readiness.
