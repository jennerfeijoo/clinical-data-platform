# PostgreSQL persistence

## Purpose

The persistence layer stores validated records from every registered dataset together with metadata that traces each load to both its source file and the exact contract that validated it.

All datasets use:

```python
persist_dataset_validation_outputs(
    connection,
    dataset,
    output_directory,
)
```

There is no separate patient persistence function.

## Separation of responsibilities

`database.py` contains the invariant transaction workflow.

Dataset-specific persistence behavior is obtained from `DatasetDefinition`:

```text
row_builder
upsert_sql
```

Contract behavior is obtained from the versioned resource referenced by the quality report:

```text
contract_path
contract_version
contract_sha256
```

The row builder converts validated CSV strings into typed Python values. The upsert statement writes those values into the correct clinical table.

## Schemas

### `clinical`

Contains analysis-facing clinical entities:

- `clinical.patients`;
- `clinical.encounters`;
- `clinical.diagnoses`;
- `clinical.observations`.

### `audit`

Contains execution, data-quality, contract-lineage, and cohort metadata:

- `audit.pipeline_runs`;
- `audit.validation_errors`;
- `audit.cohort_runs`;
- `audit.cohort_source_runs`.

### `analytics`

Contains generated analytical snapshots:

- `analytics.hypertension_features`.

## Source and contract lineage

Each persisted clinical row records:

- `source_run_id`;
- `source_sha256`;
- `loaded_at`.

The corresponding `audit.pipeline_runs` row records:

- dataset name;
- source path;
- source SHA-256;
- contract resource path;
- contract semantic version;
- contract SHA-256;
- reference date;
- row counts;
- validation-error count;
- generation and load timestamps.

The lineage relationship is:

```text
clinical row
    │
    └── source_run_id
            │
            ▼
    audit.pipeline_runs
            ├── source_sha256
            ├── contract_path
            ├── contract_version
            └── contract_sha256
```

## Historical contract verification

The loader does not assume that the currently active manifest version produced an older output bundle.

Instead it:

1. reads `contract_path` from `quality_report.json`;
2. loads that retained historical resource;
3. verifies its dataset name;
4. verifies its semantic version;
5. recalculates SHA-256 over its bytes;
6. compares the result with `contract_sha256`.

This allows an execution produced by `patients/v1.0.0.toml` to remain verifiable after a future manifest activates `patients/v1.1.0.toml`.

## Output consistency checks

Before opening the write transaction, the loader verifies that:

- the quality-report dataset matches the requested dataset;
- received rows equal valid plus invalid rows;
- valid-row counts match `valid_<dataset>.csv`;
- invalid-row counts match `invalid_<dataset>.csv`;
- error counts match `validation_errors.csv`;
- the run UUID and dates are parseable;
- source and contract checksums have the expected length;
- the referenced contract exists;
- contract name, version, and SHA-256 agree with the report;
- the run status is `completed`.

These checks prevent incomplete or contract-inconsistent output bundles from being loaded silently.

## Transactional behavior

One validation run is loaded in one database transaction. The run metadata, valid clinical rows, and validation errors either commit together or roll back together.

## Idempotency

The quality report contains a UUID `run_id`. Loading the same output directory again does not duplicate the pipeline run or validation errors. The loader reports that the run was already loaded.

Clinical identifiers use an upsert strategy, so a later validated run can update the current record while retaining the new source run and checksum.

## Legacy local databases

`sql/schema.sql` adds contract-lineage columns when an older local database already contains `audit.pipeline_runs`. Existing rows receive explicit legacy placeholders:

```text
contract_path = legacy/unversioned
contract_version = 0.0.0
contract_sha256 = 64 zero characters
```

This compatibility block is transitional. Formal schema migration tooling is the next infrastructure milestone.

## Current design boundary

Contracts govern data acceptance. SQL remains controlled application code. This avoids allowing arbitrary persistence statements inside configuration files and keeps database writes reviewable and typed through row builders.
