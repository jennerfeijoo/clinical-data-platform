# PostgreSQL migrations and persistence

## Purpose

The database layer has two separate responsibilities:

```text
migration.py
    → creates and upgrades database structure

database.py
    → persists validated dataset outputs
```

This separation prevents dataset loading code from silently redefining the schema.

## Formal migration model

The canonical schema history is stored as packaged SQL resources:

```text
src/clinical_data_platform/migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
└── V003__add_contract_lineage.sql
```

`sql/schema.sql` no longer exists.

A fresh database and an upgraded database reach the same latest version through the same ordered migration set.

## Migration history table

The migrator records state in:

```text
public.schema_migrations
```

Columns:

- `version`: ordered integer version;
- `name`: filename-derived migration name;
- `checksum`: SHA-256 of the exact SQL bytes;
- `applied_at`: PostgreSQL application timestamp;
- `execution_ms`: measured SQL execution time;
- `execution_type`: `migration` or `baseline`;
- `application_version`: package version that registered the change.

The table is in `public` because V001 is responsible for creating the `audit` schema. This avoids requiring the migration runner to pre-create part of the domain schema before V001 executes.

## Migration guarantees

Before applying SQL, the engine verifies:

- filenames match `VNNN__name.sql`;
- versions are contiguous beginning with V001;
- names are unique;
- every applied version still exists in the package;
- stored and packaged names match;
- stored and packaged checksums match;
- applied versions form a contiguous prefix;
- detected structure is not behind or ahead of recorded history;
- the requested target is not below the current version.

Applied migrations are immutable. Changes are introduced through a new version.

## Transaction and concurrency behavior

Migration execution uses one PostgreSQL transaction and an advisory transaction lock.

```text
acquire advisory lock
→ inspect existing structure
→ validate history
→ execute pending SQL
→ insert history records
→ commit
```

If any migration fails, both its DDL and its history insertion roll back.

The advisory lock prevents two cooperating application instances from applying the same pending migration concurrently.

## Fresh installation

```powershell
clinical-data database-migrate
clinical-data database-validate
```

Expected progression:

```text
0 → V001 → V002 → V003
```

A second migration run applies nothing.

## Managed upgrade

A target version can be used to reproduce an earlier state:

```powershell
clinical-data database-migrate --target-version 1
clinical-data database-status
clinical-data database-migrate
```

This supports explicit upgrade testing rather than testing only the latest fresh schema.

## Existing databases and baseline

A database created before the migration engine may contain complete platform tables without `public.schema_migrations`.

The engine refuses to adopt it automatically. After review:

```powershell
clinical-data database-migrate --baseline-existing
```

Only complete recognized structures equivalent to V001, V002, or V003 can be baselined. Partial schemas are rejected.

Baseline records use:

```text
execution_type = baseline
```

This means the SQL was not replayed; the existing structure was explicitly recognized as equivalent to the recorded versions.

## Schemas

### `clinical`

- `clinical.patients`;
- `clinical.encounters`;
- `clinical.diagnoses`;
- `clinical.observations`.

### `audit`

- `audit.pipeline_runs`;
- `audit.validation_errors`;
- `audit.cohort_runs`;
- `audit.cohort_source_runs`.

### `analytics`

- `analytics.hypertension_features`.

### `public`

- `public.schema_migrations`.

## Dataset persistence

All registered datasets use:

```python
persist_dataset_validation_outputs(
    connection,
    dataset,
    output_directory,
)
```

`database.py` contains the invariant transaction workflow. Dataset-specific conversion and SQL are obtained from the registry:

```text
row_builder
upsert_sql
```

Before a dataset is loaded, the CLI and demo workflow call `migrate_database()`.

## Source and contract lineage

Each clinical row records:

- `source_run_id`;
- `source_sha256`;
- `loaded_at`.

The corresponding `audit.pipeline_runs` row records:

- dataset name;
- source path and SHA-256;
- contract path, version, and SHA-256;
- reference date;
- row counts;
- validation-error count;
- generation and load timestamps.

## Historical contract verification

The loader reads `contract_path` from `quality_report.json`, loads that retained contract resource, recalculates its SHA-256, and verifies dataset name and semantic version before persistence.

The active manifest is not assumed to be the contract that produced an older output bundle.

## Output consistency checks

Before the write transaction, the loader verifies:

- dataset identity;
- valid, invalid, and error counts;
- parseable UUID and dates;
- source and contract checksum lengths;
- existence of the referenced contract;
- contract name, version, and hash;
- completed run status.

## Dataset transaction behavior

One validation run is persisted in one transaction:

```text
pipeline run
+
valid clinical rows
+
validation errors
```

Either all commit or all roll back.

## Dataset idempotency

The validation output contains a UUID `run_id`. Loading the same output bundle again does not duplicate the run or its errors.

Clinical identifiers use upserts, so a later validated source run can update the current snapshot while preserving its new source lineage.

This remains a snapshot strategy. Historical record retention is a later milestone.

## Operational commands

```powershell
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

Inspect history directly:

```sql
SELECT *
FROM public.schema_migrations
ORDER BY version;
```

## Design boundary

The current migrator is intentionally small and SQL-first because the repository uses psycopg without an ORM. It provides ordering, locking, transactions, baselining, checksum validation, and status reporting.

A larger multi-service environment may justify Alembic, Flyway, or Liquibase. The current implementation is appropriate only while its scope remains reviewable and its limitations remain explicit.
