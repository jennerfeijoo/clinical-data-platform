# Patients data contract

## Purpose

The `patients` dataset contains synthetic demographic records used to exercise the ingestion and validation workflow.

## Fields

| Field | Type | Required | Rules |
|---|---|---:|---|
| `patient_id` | string | yes | Non-empty and unique |
| `sex_at_birth` | category | yes | `F`, `M`, `OTHER`, or `UNKNOWN` |
| `birth_date` | ISO date | yes | Must not be in the future |
| `death_date` | ISO date | no | Must be equal to or later than `birth_date` |
| `source_system` | string | yes | Non-empty |

## Date format

Dates must use ISO 8601 calendar-date format:

```text
YYYY-MM-DD
```

## Validation behavior

A row is considered invalid when at least one rule fails. Invalid rows remain available for quarantine output together with structured validation errors; they are not silently discarded.

## Privacy

All records in the sample dataset are synthetic and do not represent real patients.

## Intentional invalid examples

The sample file contains invalid records for testing:

- a future birth date;
- an unsupported `sex_at_birth` category;
- a death date preceding the birth date.
