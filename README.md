# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.16.0` adds reproducible, contract-aware attrition and missingness reports for two independently seeded Synthea cohorts.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like CSV sources become auditable, terminology-linked, analysis-ready datasets.

The repository uses synthetic data only. It is intended for engineering review and learning, not for identifiable patient data, clinical decisions, epidemiological inference, regulatory deployment, or production healthcare operations.

## Architecture

```text
Pinned Synthea profile or external CSV
            │
            ▼
Immutable raw landing zone
    ├── content-addressed object
    └── append-only receipt
            │
            ▼
Versioned executable contract
            │
            ▼
Generic validation pipeline
    ├── valid rows
    ├── quarantined rows
    ├── normalized validation errors
    ├── quality report
    └── hash-chained execution journal
            │
            ▼
PostgreSQL COPY → temporary typed staging
            │
            ▼
Governed target merge
    ├── terminology resolution
    ├── record hashes
    ├── patient SCD Type 2 history
    ├── immutable-event guards
    ├── foreign keys and checks
    └── source-run lineage
            │
            ├── versioned analytical cohorts
            ├── reproducible loading benchmark
            └── paired attrition and missingness evidence
```

Structured JSON logs observe operations. PostgreSQL stores authoritative execution states, ordered events, retries, and durable failure evidence.

There is no patient-specific pipeline, no Synthea-specific persistence path, no permanent staging schema, and no monolithic schema installer.

## Two reproducible Synthea cohorts

The package contains two matched-design profiles:

| Control | Cohort A | Cohort B |
|---|---|---|
| Profile | `synthea-us-small-v1` | `synthea-us-small-cohort-b-v1` |
| Synthea release | `v4.0.0` | `v4.0.0` |
| Population | 100 | 100 |
| Random seed | `20260729` | `20260829` |
| Clinician seed | `20260730` | `20260830` |
| Reference date | `2026-07-29` | `2026-07-29` |
| Geography | Massachusetts | Massachusetts |
| Threads | 1 | 1 |
| Retained history | complete | complete |

Software version, geography, date, size, export scope, thread count, and retained history remain fixed. Only the patient and clinician seeds change. Cohort B is therefore an independent stochastic replica under the same controlled design.

The pair comparison requires:

```text
distinct profile hashes
AND distinct random seeds
AND distinct clinician seeds
AND distinct adaptation fingerprints
AND zero overlap across:
    patient_id
    encounter_id
    diagnosis_id
    observation_id
    medication_id
    procedure_id
```

Generate and verify both cohorts:

```powershell
.\scripts\generate_synthea_cohorts.ps1
```

Compare them directly:

```powershell
clinical-data-cohort compare `
  data/synthea/synthea-us-small-v1/normalized `
  data/synthea/synthea-us-small-cohort-b-v1/normalized `
  --output-dir data/synthea/cohort-comparison
```

Load both through the governed pipeline:

```powershell
.\scripts\load_synthea_cohorts.ps1 -ReplaceComparison
```

A complete pair load creates twelve separate completed pipeline runs:

```text
6 datasets × 2 cohorts = 12 run_ids
```

Before loading, the pair loader checks PostgreSQL for identifiers belonging to either cohort. Any collision causes refusal before new validation or persistence runs are created.

Technical protocol: [`docs/synthea-cohorts.md`](docs/synthea-cohorts.md).

Spanish guide: [`docs/learning/segunda-cohorte-synthea-es.md`](docs/learning/segunda-cohorte-synthea-es.md).

## Attrition and missingness reports

Version `0.16.0` converts the adaptation process into reproducible quality evidence:

```text
source rows
→ adapted rows
→ explicit omission reasons
→ source-field missingness
→ contract-aware adapted missingness
→ row completeness
→ descriptive A/B comparison
→ stable quality fingerprint
```

Attrition means technical row exclusion during adaptation, not patient dropout or loss to follow-up.

For every entity the report requires:

```text
source_rows = adapted_rows + omitted_rows
```

Adapted missingness is classified as:

| Classification | Meaning |
|---|---|
| `required` | A blank value violates the active executable contract. |
| `optional` | Absence is permitted and may represent a valid clinical state. |
| `structural` | The current adapter does not receive a reliable structured source value. |

Current structural fields are `medications.dose_value`, `medications.dose_unit`, and `medications.route`.

Generate the report:

```powershell
.\scripts\report_synthea_quality.ps1
```

Direct command:

```powershell
clinical-data-cohort quality-report `
  data/synthea/synthea-us-small-v1/normalized `
  data/synthea/synthea-us-small-cohort-b-v1/normalized `
  --output-dir data/synthea/cohort-quality
```

Artifacts:

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
```

The quality fingerprint covers the cohort comparison identity, profiles, adaptation fingerprints, contracts, counts, omission reasons, missingness, row completeness, and descriptive comparisons. It excludes timestamps and absolute output paths.

Technical protocol: [`docs/attrition-missingness.md`](docs/attrition-missingness.md).

Spanish guide: [`docs/learning/reportes-attrition-missingness-es.md`](docs/learning/reportes-attrition-missingness-es.md).

## Reproducible Synthea adaptation

```text
Synthea patients.csv      → patients.csv
Synthea encounters.csv    → encounters.csv
Synthea conditions.csv    → diagnoses.csv
Synthea observations.csv  → observations.csv
Synthea medications.csv   → medications.csv
Synthea procedures.csv    → procedures.csv
```

The adapter also writes `terminology.csv` and `synthea-adaptation-manifest.json`. Missing source-event identifiers use deterministic UUIDv5 values. Parent relationships, exact headers, executable contracts, omissions, terminology concepts, hashes, and fingerprints are verified.

The observation adapter intentionally retains only:

| LOINC source | Internal code |
|---|---|
| `8480-6` | `SYSTOLIC_BP` |
| `8462-4` | `DIASTOLIC_BP` |
| `8867-4` | `HEART_RATE` |

Other observations are explicitly counted as omitted rather than forced into the narrow contract.

See [`docs/synthea.md`](docs/synthea.md).

## Governed PostgreSQL loading benchmark

The benchmark compares:

```text
current route
record iterator
→ COPY FROM STDIN
→ temporary typed staging
→ set-based INSERT ... SELECT ... ON CONFLICT
```

with the former `executemany` reference using equivalent target semantics.

Balanced protocol:

| Control | Value |
|---|---|
| Data | deterministic six-entity synthetic workload |
| Seed | `20260729` |
| Reference date | `2026-07-29` |
| Patient sizes | 250, 1,000, 2,500 |
| Clinical rows | 3,750, 15,000, 37,500 |
| Warm-ups | 1 per method and size |
| Measured repetitions | 6 per method and size |
| Starting-position balance | COPY first 3 times; `executemany` first 3 times |
| Writer concurrency | 1 |

GitHub Actions workflow run `30470147850` produced:

| Patients | Rows | COPY median | `executemany` median | COPY speedup | Time reduction |
|---:|---:|---:|---:|---:|---:|
| 250 | 3,750 | 825.694 ms | 1,083.028 ms | 1.312× | 23.76% |
| 1,000 | 15,000 | 3,183.671 ms | 4,341.867 ms | 1.364× | 26.68% |
| 2,500 | 37,500 | 7,936.444 ms | 10,955.541 ms | 1.380× | 27.56% |

This supports a limited engineering statement: on the recorded hosted-runner environment, COPY reduced median governed initial-load time by approximately **23.8–27.6%** relative to the former route.

Permanent evidence:

```text
benchmarks/loading/github-actions-run-30470147850/
├── benchmark-summary.md
├── benchmark-trials.csv
└── reference-run.json
```

See [`docs/loading-benchmark.md`](docs/loading-benchmark.md).

## Six clinical entities

```text
patients
   └── encounters
          ├── diagnoses
          ├── observations
          ├── medications
          └── procedures
```

| Dataset | Storage policy | Primary identifier |
|---|---|---|
| patients | current snapshot + SCD Type 2 history | `patient_id` |
| encounters | immutable event | `encounter_id` |
| diagnoses | immutable event + terminology binding | `diagnosis_id` |
| observations | immutable event + terminology binding | `observation_id` |
| medications | immutable event + terminology binding | `medication_id` |
| procedures | immutable event + terminology binding | `procedure_id` |

Exact duplicates preserve the original event and lineage. Conflicting identifier reuse rolls back the clinical transaction and leaves a failed execution timeline.

## Execution lifecycle

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

A failed attempt remains auditable and may retry. Loading uses separate durable transaction boundaries for run registration, governed clinical persistence, and post-rollback failure evidence.

## Raw landing zone

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Identical files share one content object, while each reception has a separate append-only receipt. This is application-level local immutability, not certified WORM storage.

## Executable contracts

```text
contracts/
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
├── observations/v1.0.0.toml
├── medications/v1.0.0.toml
└── procedures/v1.0.0.toml
```

The engine executes structural, required-value, uniqueness, type, categorical, temporal, unit, and plausible-range rules. Every validation run records contract path, version, and SHA-256.

## Minimal terminology layer

```text
terminology.code_systems
terminology.system_aliases
terminology.concepts
terminology.concept_mappings
terminology.normalized_clinical_codes
```

The local registry contains small subsets of ICD-10-CM, LOINC, RxNorm, ATC, SNOMED CT, CPT, and ICD-10-PCS. It is not a complete terminology server. Synthea concepts absent from the curated subset are imported explicitly as `unverified`.

## PostgreSQL migrations

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient SCD2 and immutable-event policy
V006 medications and procedures
V007 minimal terminology integration
V008 execution lifecycle and durable failure audit
```

The quality-report milestone requires no V009 because it adds verified application artifacts rather than permanent database objects.

Expected state:

```text
detected=8
current=8
latest=8
pending=[]
```

## Local development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

Copy-Item .env.example .env
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data database-migrate
clinical-data database-validate
clinical-data run-demo --repository-root .
```

## Quality checks

```bash
clinical-data validate-contracts
clinical-data database-migrate
clinical-data database-validate
clinical-data-cohort list-profiles
clinical-data-cohort quality-report --help
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

Normal CI uses small checked-in fixtures for both Synthea cohorts. The full Java generator and larger loading benchmark remain separate from ordinary CI.

## Implemented capabilities

- generic contract-governed architecture;
- versioned executable contracts;
- formal PostgreSQL migrations;
- immutable content-addressed raw landing zone;
- patient SCD Type 2 history and immutable events;
- six clinical entities and minimal terminology integration;
- complete execution states, retries, and durable failures;
- structured JSON logging;
- reproducible Synthea generation and deterministic adaptation;
- two matched-design independently seeded Synthea profiles;
- identifier-disjoint cohort comparison and separate load lineage;
- reproducible attrition, omission-reason, missingness, and completeness reports;
- PostgreSQL COPY loading with typed staging;
- correctness-gated loading benchmark;
- versioned hypertension cohort and feature export;
- Docker, Compose, PowerShell, POSIX, Ruff, strict mypy, pytest, PostgreSQL integration, and GitHub Actions.

## Documentation

- [`docs/attrition-missingness.md`](docs/attrition-missingness.md): quality-report definitions, artifacts, and limits;
- [`docs/synthea-cohorts.md`](docs/synthea-cohorts.md): two-cohort protocol and boundaries;
- [`docs/synthea.md`](docs/synthea.md): generation and adaptation;
- [`docs/loading-benchmark.md`](docs/loading-benchmark.md): benchmark protocol and evidence;
- [`docs/bulk-loading.md`](docs/bulk-loading.md): COPY, staging, merge, and transactions;
- [`docs/architecture.md`](docs/architecture.md): architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/execution-audit.md`](docs/execution-audit.md): lifecycle and failure evidence;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): SCD2 and immutable events;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/terminology.md`](docs/terminology.md): terminology model and licensing boundary;
- [`docs/learning/reportes-attrition-missingness-es.md`](docs/learning/reportes-attrition-missingness-es.md): Spanish quality-report guide;
- [`docs/learning/segunda-cohorte-synthea-es.md`](docs/learning/segunda-cohorte-synthea-es.md): Spanish second-cohort guide.

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- coverage of at least 90%;
- multi-version Python CI;
- dependency and security scanning;
- non-root container hardening;
- final documentation and release `1.0.0`.

The two-cohort load is not one global transaction. Contract validation still materializes the complete source dataset. The full Synthea generator is not executed in normal CI. Attrition is row-level technical exclusion, not participant follow-up. Missingness classification does not establish MCAR, MAR, or MNAR. The benchmark measures initial single-writer loading, not production capacity. The logging layer has no centralized transport or OpenTelemetry.

## License

MIT License. See [`LICENSE`](LICENSE).
