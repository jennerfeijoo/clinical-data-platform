# Command-line reference

The project installs three entrypoints:

```text
clinical-data
clinical-data-cohort
clinical-data-benchmark
```

Run any command with `--help` for the authoritative parser output of the installed version. Commands use synthetic or appropriately licensed public data only.

## `clinical-data`

### Contracts

```bash
clinical-data list-contracts
clinical-data show-contract patients
clinical-data validate-contracts
```

These commands inspect the active versioned contract manifest and packaged contract resources. They do not access PostgreSQL.

### Immutable raw landing

```bash
clinical-data raw-capture patients source.csv --raw-root data/raw
clinical-data raw-verify receipts/patients/YYYY/MM/DD/<receipt>.json --raw-root data/raw
```

`raw-capture` creates a content-addressed object and an append-only receipt manifest at application level. `raw-verify` checks manifest integrity, object size, and SHA-256 identity. The local filesystem is not claimed to be WORM storage.

### PostgreSQL migrations

```bash
clinical-data database-status
clinical-data database-migrate
clinical-data database-validate
```

The database URL is read from `--database-url` or `DATABASE_URL`. `--baseline-existing` is an explicit adoption control for a recognized legacy schema; it must not be used for an unknown or partially modified database.

### Generic dataset validation and loading

```bash
clinical-data validate-dataset patients data/sample/patients.csv
clinical-data load-dataset patients
```

Supported datasets are:

```text
patients
encounters
diagnoses
observations
medications
procedures
```

Validation captures raw lineage and writes processed quality outputs. Loading verifies those outputs, applies migrations, and persists them under the history, immutability, terminology, and execution-audit policies.

### Hypertension cohort

```bash
clinical-data build-hypertension-cohort
clinical-data build-hypertension-cohort --sql reviewed-definition.sql
```

The default cohort definition is packaged inside the installed wheel. The repository path `sql/cohorts/hypertension.sql` remains a readable development copy and is checked against the packaged resource. `--sql` permits an explicit reviewed override. Cohort exports are written to `data/analytics` unless another output directory is supplied.

### Synthea single-profile workflow

```bash
clinical-data synthea-profile
clinical-data synthea-generate
clinical-data synthea-adapt <csv-directory>
clinical-data synthea-verify <normalized-directory>
clinical-data synthea-load <normalized-directory>
```

The default profile pins Synthea, seeds, reference date, geography, export scope, and thread count. Generation requires Java and Git. Adaptation and verification operate on existing CSV artifacts.

### End-to-end synthetic demo

```bash
clinical-data run-demo --repository-root .
```

The demo captures the bundled synthetic sample datasets, migrates PostgreSQL, validates and persists all six entities, builds the hypertension cohort, and exports analytical artifacts. It is not a production deployment path.

## `clinical-data-cohort`

### Profiles and generation

```bash
clinical-data-cohort list-profiles
clinical-data-cohort profile synthea-us-small-v1
clinical-data-cohort generate synthea-us-small-v1
clinical-data-cohort adapt synthea-us-small-v1 <csv-directory>
clinical-data-cohort verify synthea-us-small-v1 <normalized-directory>
```

The packaged profiles currently define two matched-design cohorts whose patient and clinician seeds differ.

### Pair comparison and quality evidence

```bash
clinical-data-cohort compare <cohort-a> <cohort-b>
clinical-data-cohort quality-report <cohort-a> <cohort-b>
```

Comparison requires distinct profile and adaptation fingerprints and zero identifier overlap across all six entity domains. The quality report generates technical attrition, omission-reason, source-missingness, adapted-missingness, completeness, and cohort-comparison evidence.

### Pair loading

```bash
clinical-data-cohort load-pair <cohort-a> <cohort-b>
```

The command performs comparison and database preflight before loading the cohorts with separate processing roots and run identifiers. The pair is not one global transaction.

## `clinical-data-benchmark`

```bash
clinical-data-benchmark \
  --allow-destructive-reset \
  --patients 250 1000 2500 \
  --repetitions 6 \
  --warmups 1 \
  --seed 20260729
```

The destructive confirmation is mandatory. The benchmark refuses a governed database that already contains platform data and truncates platform state between measured trials. It must run only against an isolated, disposable database.

The benchmark compares the governed PostgreSQL `COPY` path with the former `executemany` reference path. It verifies database fingerprints before reporting timing differences. It measures the persistence segment, not complete pipeline latency or production capacity.

## Exit behavior and logs

Argument and policy errors return a non-zero exit code. The primary `clinical-data` entrypoint emits structured logs to standard error and command output to standard output. Configure logs with:

```text
CLINICAL_DATA_LOG_LEVEL
CLINICAL_DATA_LOG_FORMAT
CLINICAL_DATA_CORRELATION_ID
```

Logs are operational telemetry. The durable execution timeline in PostgreSQL and the local hash-chained validation journal remain the audit evidence for pipeline state.
