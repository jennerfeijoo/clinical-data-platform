# PostgreSQL persistence

## Purpose

The persistence layer stores validated patient records together with the metadata required to trace each load back to a validation run and source file.

## Schemas

### `clinical`

Contains analysis-facing clinical entities.

- `clinical.patients`: one current row per patient identifier.

### `audit`

Contains execution and data-quality metadata.

- `audit.pipeline_runs`: one row per validation run;
- `audit.validation_errors`: structured errors linked to a validation run.

## Lineage fields

Each patient row records:

- `source_run_id`;
- `source_sha256`;
- `loaded_at`.

The corresponding pipeline-run row records:

- source path and checksum;
- reference date;
- row counts;
- validation-error count;
- validation and load timestamps.

## Transactional behavior

A validation run is loaded in one database transaction. The run metadata, valid patient rows, and validation errors either commit together or roll back together.

## Idempotency

The quality report contains a UUID `run_id`. Loading the same output directory again does not duplicate the pipeline run or validation errors. The loader reports that the run was already loaded.

Patient identifiers use an upsert strategy so that a later validated run can update the current patient record while preserving the new run identifier and source checksum.

## Scope

This schema is intentionally small. Encounters, diagnoses, observations, medications, cohort definitions, and feature tables will be added in later milestones.
