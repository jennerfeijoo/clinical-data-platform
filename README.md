# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.8.0` completes the six-entity clinical model.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like source files can become auditable, analysis-ready datasets.

The repository uses only synthetic data. It is intended for engineering review and learning, not for identifiable patient data, clinical decisions, or production healthcare deployment.

## Architecture

```text
External CSV source
        │
        ▼
Immutable raw capture
        ├── SHA-256 content object
        └── append-only receipt manifest
        │
        ▼
Versioned executable TOML contract
        │
        ▼
Generic validation pipeline
        ├── valid rows
        ├── quarantined rows
        ├── normalized errors
        └── quality report
        │
        ▼
Formal PostgreSQL migrations
        │
        ▼
Hybrid clinical persistence
        ├── patient current snapshot + SCD2 history
        └── five immutable event entities
        │
        ▼
Versioned cohort SQL and feature export
```

There is no patient-specific validation pipeline and no monolithic schema installer.

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
| diagnoses | immutable event | `diagnosis_id` |
| observations | immutable event | `observation_id` |
| medications | immutable event | `medication_id` |
| procedures | immutable event | `procedure_id` |

Every event references a patient and encounter. PostgreSQL foreign keys reject orphaned events.

Exact event duplicates are no-ops that preserve original lineage. Reusing an event identifier with different business content raises an integrity error and rolls back the complete dataset load.

## Medication model

Medication events include:

```text
medication_id
patient_id
encounter_id
code_system
medication_code
status
start_datetime
end_datetime
dose_value
dose_unit
route
source_system
```

The executable contract accepts `RXNORM` and `ATC` as declared code-system names. It validates status, route, types, and temporal order. PostgreSQL additionally enforces foreign keys, positive dose, paired dose value/unit, record hashing, and immutability.

## Procedure model

Procedure events include:

```text
procedure_id
patient_id
encounter_id
code_system
procedure_code
procedure_datetime
status
source_system
```

The contract accepts `SNOMED`, `CPT`, and `ICD10PCS` as declared code-system names. It does not yet validate individual codes against external terminology releases.

## Clinical history policy

Every current clinical row has a `record_sha256` calculated from normalized business content. Lineage fields are excluded so that re-receiving the same content does not create a false change.

Patient demographic changes close the prior row in `clinical.patient_history` and append a new current version. Encounter, diagnosis, observation, medication, and procedure events are immutable.

The policy is declared in `src/clinical_data_platform/history.py` and enforced by migrations V005 and V006.

## Immutable raw landing zone

Sources are captured before parsing under:

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Identical files share one content object, while each reception receives a separate append-only receipt. The local implementation provides checksum verification, content deduplication, staging, atomic publication, no application-level replacement, read-only permissions, path-traversal protection, and lineage verification.

This is application-level local immutability, not certified WORM storage.

## Executable contracts

Active versions are selected by:

```text
src/clinical_data_platform/contracts/manifest.toml
```

```text
contracts/
├── patients/v1.0.0.toml
├── encounters/v1.0.0.toml
├── diagnoses/v1.0.0.toml
├── observations/v1.0.0.toml
├── medications/v1.0.0.toml
└── procedures/v1.0.0.toml
```

The contract engine executes structural, required-value, uniqueness, type, categorical, temporal, unit, and plausible-range rules. Each validation run records contract path, semantic version, and SHA-256.

## PostgreSQL migrations

```text
migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
├── V004__add_raw_landing_lineage.sql
├── V005__add_clinical_history_policy.sql
└── V006__add_medications_and_procedures.sql
```

Migration history is stored in `public.schema_migrations`. The engine verifies contiguous ordering, names, checksums, detected structure, pending versions, and downgrade attempts. Migrations execute transactionally under a PostgreSQL advisory lock.

## Implemented capabilities

- six contract-governed clinical datasets;
- immutable content-addressed raw capture and append-only receipts;
- normalized validation errors and rejected-record quarantine;
- source, raw, contract, run, record, and cohort lineage;
- formal PostgreSQL install, upgrade, baseline, and drift checks;
- current patient snapshot plus SCD Type 2 history;
- immutable clinical-event conflict protection;
- transactional and run-idempotent persistence;
- referential integrity and database constraints;
- versioned hypertension cohort and baseline features;
- Docker, Docker Compose, PowerShell, and POSIX workflows;
- Ruff, strict mypy, pytest, coverage, PostgreSQL integration tests, and GitHub Actions.

## Fastest complete run

Requirements: Git and Docker with Docker Compose.

```bash
git clone https://github.com/jennerfeijoo/clinical-data-platform.git
cd clinical-data-platform
```

PowerShell:

```powershell
.\scripts\run_demo.ps1
```

POSIX shell:

```bash
sh scripts/run_demo.sh
```

The demo captures, validates, migrates, persists, builds the hypertension cohort, and writes:

```text
data/raw/
data/processed/
data/analytics/
```

## Local Python development

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

## Expected bundled sample

| Dataset | Received | Valid | Invalid | Errors | Contract |
|---|---:|---:|---:|---:|---:|
| Patients | 8 | 5 | 3 | 3 | 1.0.0 |
| Encounters | 8 | 7 | 1 | 1 | 1.0.0 |
| Diagnoses | 7 | 6 | 1 | 2 | 1.0.0 |
| Observations | 14 | 13 | 1 | 1 | 1.0.0 |
| Medications | 7 | 6 | 1 | 1 | 1.0.0 |
| Procedures | 7 | 6 | 1 | 1 | 1.0.0 |

The default hypertension cohort contains `P001` and `P002`.

## Review entity counts

```sql
SELECT 'patients' AS dataset, COUNT(*) FROM clinical.patients
UNION ALL
SELECT 'encounters', COUNT(*) FROM clinical.encounters
UNION ALL
SELECT 'diagnoses', COUNT(*) FROM clinical.diagnoses
UNION ALL
SELECT 'observations', COUNT(*) FROM clinical.observations
UNION ALL
SELECT 'medications', COUNT(*) FROM clinical.medications
UNION ALL
SELECT 'procedures', COUNT(*) FROM clinical.procedures
ORDER BY dataset;
```

Expected counts after a clean demo: 5 patients, 7 encounters, 6 diagnoses, 13 observations, 6 medications, and 6 procedures.

## Quality checks

```bash
clinical-data validate-contracts
clinical-data database-migrate
clinical-data database-validate
python -m ruff check .
python -m mypy src
python -m pytest --cov=clinical_data_platform --cov-report=term-missing
docker build --tag clinical-data-platform:local .
```

CI exercises contract validation, migrations, raw capture, patient history, all six entities, immutable-event rollback, cohort generation, and container smoke tests.

## Documentation

- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): snapshot and immutable-event policy;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): review sequence and SQL;
- [`docs/learning/six-clinical-entities-es.md`](docs/learning/six-clinical-entities-es.md): detailed Spanish study guide;
- additional learning guides under [`docs/learning/`](docs/learning/).

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- terminology normalization;
- complete execution states and structured logging;
- reproducible Synthea datasets;
- bulk PostgreSQL `COPY` loading and benchmarks;
- an additional cohort with attrition and missingness reporting;
- stronger coverage, multi-version CI, security, container, and release hardening.

The project intentionally excludes identifiable patient data, production decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
