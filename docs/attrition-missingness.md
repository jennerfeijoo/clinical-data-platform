# Reproducible attrition and missingness reports

## Purpose

This workflow produces auditable descriptive quality evidence for the two matched-design Synthea cohorts. It measures:

- row attrition between the six upstream Synthea CSV files and the six contract-ready datasets;
- the explicit adaptation reasons responsible for omitted rows;
- field-level blank-value missingness in the upstream CSV files;
- contract-aware missingness in adapted datasets;
- row completeness and required-field integrity;
- descriptive differences between cohort A and cohort B.

The report does not measure participant dropout, loss to clinical follow-up, treatment discontinuation, or CONSORT-style study attrition.

## Processing boundary

```text
Synthea source CSV
→ verified adaptation manifest
→ source row count
→ adapted row count
→ omission reasons
→ source missingness
→ adapted contract-aware missingness
→ paired descriptive comparison
→ stable quality fingerprint
```

Every report first runs the existing identifier-disjoint cohort comparison. Therefore the quality evidence is bound to a verified pair of matched-design, independently seeded populations.

## Attrition definition

For every entity:

```text
source rows = adapted rows + omitted rows
```

The report refuses to continue when this identity does not reconcile.

| Internal dataset | Synthea source file | Omission prefix |
|---|---|---|
| `patients` | `patients.csv` | `patient_` |
| `encounters` | `encounters.csv` | `encounter_` |
| `diagnoses` | `conditions.csv` | `condition_` |
| `observations` | `observations.csv` | `observation_` |
| `medications` | `medications.csv` | `medication_` |
| `procedures` | `procedures.csv` | `procedure_` |

Retention and attrition rates use the upstream row count as denominator. When an upstream file has zero rows, rates are represented as `null` in JSON and blank in CSV rather than inventing a `0%` or `100%` value.

## Missing-value definition

A value is missing only when it is empty after whitespace trimming.

The following are not automatically converted to missing:

```text
0
UNKNOWN
NA
N/A
```

This avoids imposing undocumented null conventions on source data.

## Adapted-field classifications

The active executable contracts determine whether a field is required.

| Classification | Meaning |
|---|---|
| `required` | Blank values violate the active contract. Verified reports require zero. |
| `optional` | Blank values are permitted by the contract and may reflect a clinical state. |
| `structural` | The current adapter does not receive a reliable structured source value. |

The current structural fields are:

```text
medications.dose_value
medications.dose_unit
medications.route
```

These fields remain visible in the report. They are not deleted or misreported as validation failures.

## Output artifacts

```text
data/synthea/cohort-quality/
├── synthea-quality-report.json
├── synthea-quality-report.md
├── attrition.csv
├── attrition-reasons.csv
├── source-missingness.csv
├── adapted-missingness.csv
├── row-completeness.csv
├── cohort-quality-comparison.csv
└── cohort-comparison/
    ├── synthea-cohort-comparison.json
    └── synthea-cohort-comparison.md
```

### `attrition.csv`

One row per cohort and clinical entity:

```text
cohort
dataset
source_file
source_rows
adapted_rows
omitted_rows
retention_rate
attrition_rate
```

### `attrition-reasons.csv`

One row per non-zero omission reason, including its share of source rows and omitted rows.

### `source-missingness.csv`

Field-level counts for the complete upstream Synthea schema. These are descriptive only; upstream columns are not assigned internal contract requirements.

### `adapted-missingness.csv`

Field-level counts for contract-ready datasets, including required status and missingness classification.

### `row-completeness.csv`

Contains:

```text
rows complete across every field
rows with at least one blank field
rows with missing required fields
missing cells across the adapted table
required missing cells
structural missing cells
```

### `cohort-quality-comparison.csv`

Reports descriptive differences in retention and adapted missing-cell rates as cohort B minus cohort A. These are not hypothesis tests.

## Reproducible identity

The stable quality fingerprint covers:

- report schema version;
- cohort comparison fingerprint;
- profile hashes;
- adaptation fingerprints;
- contract paths, versions, and hashes;
- row counts and omission reasons;
- source and adapted missingness counts;
- row completeness counts;
- descriptive pair comparisons.

It excludes:

```text
creation timestamp
absolute output path
```

Because rates are derived from fingerprinted counts, the report identity remains tied to the underlying evidence.

## Commands

Generate the report after both cohorts have been adapted:

```powershell
.\scripts\report_synthea_quality.ps1
```

Replace an existing report directory:

```powershell
.\scripts\report_synthea_quality.ps1 -Replace
```

Direct command:

```powershell
clinical-data-cohort quality-report `
  data/synthea/synthea-us-small-v1/normalized `
  data/synthea/synthea-us-small-cohort-b-v1/normalized `
  --output-dir data/synthea/cohort-quality
```

POSIX:

```bash
bash scripts/report_synthea_quality.sh
```

With replacement:

```bash
REPLACE=1 bash scripts/report_synthea_quality.sh
```

## Integrity checks

Report generation refuses:

- tampered source or adapted files;
- unsupported or mismatched Synthea profiles;
- overlapping cohort identifiers;
- unsafe cohort labels;
- unknown omission-reason prefixes;
- negative omission counts;
- source/adapted/omitted count mismatches;
- missing required values in verified adapted datasets;
- accidental overwrite of a non-empty report directory.

## Interpretation boundary

Summing rows across heterogeneous clinical entities is useful as an engineering overview but is not a patient-level denominator. Likewise, a missing-cell rate combines fields with different semantics.

The report supports statements such as:

> In this verified synthetic cohort artifact, 75% of source observation rows were retained because the adapter intentionally supports three observation concepts, while all required fields in retained records were complete.

It does not support statements about real-world prevalence, data quality in a hospital, treatment effectiveness, patient dropout, or clinical representativeness.
