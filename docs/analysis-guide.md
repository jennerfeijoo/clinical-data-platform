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

The workflow validates four registered datasets, loads PostgreSQL, builds the hypertension cohort, and exports analysis-ready features.

## 2. Inspect file-level quality outputs

Review each directory under `data/processed/`:

```text
data/processed/
├── patients/
├── encounters/
├── diagnoses/
└── observations/
```

Each directory contains valid rows, rejected rows, structured validation errors, and a JSON quality report. The output convention is identical because every dataset runs through the same `run_dataset_validation()` function.

Questions to evaluate:

- Are rejected records preserved?
- Can every error be linked to a row, entity, patient, field, rule, and rejected value?
- Do reported counts match the generated files?
- Does each report include a run UUID and source checksum?
- Does adding a dataset require modifying the pipeline, or only registering a definition?

## 3. Inspect the generic architecture

Read these files in order:

1. `src/clinical_data_platform/models.py`
2. `src/clinical_data_platform/registry.py`
3. `src/clinical_data_platform/pipeline.py`
4. `src/clinical_data_platform/database.py`
5. `src/clinical_data_platform/validation.py`
6. `src/clinical_data_platform/clinical_entities.py`

The separation is intentional:

- `models.py` defines normalized cross-dataset results;
- `registry.py` describes what changes between datasets;
- `pipeline.py` implements the invariant validation workflow;
- `database.py` implements the invariant persistence workflow;
- validation modules contain dataset-specific clinical rules.

The central review question is: **where should variation live, and where should behavior remain invariant?**

See `docs/learning/generic-dataset-architecture-es.md` for a detailed Spanish study guide and exercises.

## 4. Inspect PostgreSQL

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

## 5. Inspect the analytical cohort

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

## 6. Inspect exported analysis files

```text
data/analytics/
├── hypertension_features.csv
└── hypertension_cohort_metadata.json
```

The CSV is the analysis-ready table. The JSON file records its definition version, parameters, source runs, row count, and generation time.

## 7. Review engineering decisions

Recommended full review order:

1. `docs/architecture.md`
2. `docs/learning/generic-dataset-architecture-es.md`
3. `src/clinical_data_platform/models.py`
4. `src/clinical_data_platform/registry.py`
5. `src/clinical_data_platform/pipeline.py`
6. `src/clinical_data_platform/database.py`
7. `src/clinical_data_platform/validation.py`
8. `src/clinical_data_platform/clinical_entities.py`
9. `sql/schema.sql`
10. `sql/cohorts/hypertension.sql`
11. `tests/test_registry.py`
12. `tests/test_analysis_workflow.py`
13. `.github/workflows/ci.yml`

Key design questions:

- Why is the patient dataset no longer handled by a separate pipeline?
- What behavior belongs in `DatasetDefinition`?
- Why are validation errors normalized before the pipeline writes them?
- Which checks belong in Python and which belong in PostgreSQL?
- Is run-level idempotency sufficient, or should content-level deduplication also be implemented?
- Should cohort outputs be snapshots, views, or materialized views?
- How should schema migrations be handled once the model evolves?
- How would controlled vocabularies and unit conversion be introduced?
- What additional observability would be required in production?

## 8. Known limitations

- small synthetic dataset;
- only four clinical entities;
- registry definitions are executable Python rather than declarative contracts;
- limited terminology support;
- no authentication or authorization;
- no PHI handling;
- no orchestration engine;
- no migration framework;
- no production monitoring or alerting;
- one demonstrative cohort rather than a generic cohort-definition language.

These constraints remain explicit while the repository progresses toward a defensible version `1.0.0`.
