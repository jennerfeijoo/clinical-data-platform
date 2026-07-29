# PostgreSQL persistence

## Purpose

The persistence layer stores validated records from every registered dataset together with the metadata required to trace each load back to a validation run and source file.

All datasets use:

```python
persist_dataset_validation_outputs(
    connection,
    dataset,
    output_directory,
)
```

There is no separate patient persistence function.

## Registry-driven behavior

`database.py` contains the invariant transaction workflow. Dataset-specific behavior is obtained from `DatasetDefinition`:

```text
row_builder
upsert_sql
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

Contains execution, data-quality, and cohort metadata:

- `audit.pipeline_runs`;
- `audit.validation_errors`;
- `audit.cohort_runs`;
- `audit.cohort_source_runs`.

### `analytics`

Contains generated analytical snapshots:

- `analytics.hypertension_features`.

## Lineage fields

Each persisted clinical row records:

- `source_run_id`;
- `source_sha256`;
- `loaded_at`.

The corresponding pipeline-run row records:

- dataset name;
- source path and checksum;
- reference date;
- row counts;
- validation-error count;
- validation and load timestamps.

## Output consistency checks

Before opening the write transaction, the loader verifies that:

- the quality-report dataset matches the requested dataset;
- received rows equal valid plus invalid rows;
- valid-row counts match `valid_<dataset>.csv`;
- invalid-row counts match `invalid_<dataset>.csv`;
- error counts match `validation_errors.csv`;
- the run UUID and dates are parseable;
- the source checksum has the expected length;
- the run status is `completed`.

These checks prevent incomplete or manually altered output bundles from being loaded silently.

## Transactional behavior

One validation run is loaded in one database transaction. The run metadata, valid clinical rows, and validation errors either commit together or roll back together.

## Idempotency

The quality report contains a UUID `run_id`. Loading the same output directory again does not duplicate the pipeline run or validation errors. The loader reports that the run was already loaded.

Clinical identifiers use an upsert strategy, so a later validated run can update the current record while retaining the new source run and checksum.

## Current design trade-off

The registry currently stores both validation dispatch and persistence details. This centralizes dataset behavior and removes distributed `if dataset == ...` branches, but it also couples definitions to SQL. A later refactor may separate the registry into contracts, validators, and persistence adapters.
