# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.9.0` adds minimal clinical terminology normalization.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like source files can become auditable, analysis-ready, terminology-linked datasets.

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
Formal PostgreSQL migrations V001–V007
        │
        ▼
Terminology resolution
        ├── source-system aliases
        ├── active concepts by domain
        └── reviewed local-to-standard mappings
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
| diagnoses | immutable event + terminology binding | `diagnosis_id` |
| observations | immutable event + terminology binding | `observation_id` |
| medications | immutable event + terminology binding | `medication_id` |
| procedures | immutable event + terminology binding | `procedure_id` |

Every event references a patient and encounter. PostgreSQL foreign keys reject orphaned events.

Exact event duplicates preserve the original row and lineage. Reusing an event identifier with different business content raises an integrity error and rolls back the complete dataset load.

## Minimal terminology layer

V007 creates:

```text
terminology.code_systems
terminology.system_aliases
terminology.concepts
terminology.concept_mappings
terminology.normalized_clinical_codes
```

The installed subset registers:

```text
ICD10CM
LOINC
RXNORM
ATC
SNOMEDCT
CPT
ICD10PCS
LOCAL_OBSERVATION
```

External systems are represented by small local subsets. They are not complete releases.

### Source and normalized representations

The source representation remains in the clinical row:

```text
LOCAL_OBSERVATION:SYSTOLIC_BP
```

The row also receives a foreign key to its normalized concept:

```text
LOINC:8480-6 — Systolic blood pressure
```

Bundled mappings:

| Local source code | Normalized system | Normalized code |
|---|---|---|
| `SYSTOLIC_BP` | LOINC | `8480-6` |
| `DIASTOLIC_BP` | LOINC | `8462-4` |
| `HEART_RATE` | LOINC | `8867-4` |

### Strict terminology boundary

A coded row can pass its file contract but fail persistence when:

- its system has no registered alias;
- its code is absent from the installed subset;
- its concept is inactive;
- its concept belongs to the wrong domain.

The complete dataset transaction then rolls back. Raw and processed artifacts remain available for investigation.

### Verification and licensing

Concept entries have one of three local statuses:

```text
verified
curated
unverified
```

The repository does not redistribute complete terminology releases. CPT descriptors are deliberately omitted, SNOMED CT entries remain subject to applicable licensing, and every external system is marked as an incomplete subset.

See [`docs/terminology.md`](docs/terminology.md) for the precise boundary.

## Clinical history policy

Every current clinical row has a `record_sha256` calculated from normalized business content. Lineage and terminology foreign keys are excluded so that operational metadata does not create false clinical changes.

Patient demographic changes close the prior row in `clinical.patient_history` and append a new current version. Encounter, diagnosis, observation, medication, and procedure events are immutable.

The policy is declared in `src/clinical_data_platform/history.py` and enforced by PostgreSQL triggers.

## Immutable raw landing zone

Sources are captured before parsing under:

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Identical files share one content object, while each reception receives a separate append-only receipt. The implementation verifies checksums, byte sizes, paths, and manifest lineage before persistence.

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

The contract engine executes structural, required-value, uniqueness, type, categorical, temporal, unit, and plausible-range rules. Each validation run records contract path, version, and SHA-256.

Contracts define the accepted source interface. PostgreSQL terminology resolution determines whether coded values are recognized by the installed terminology subset.

## PostgreSQL migrations

```text
migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
├── V004__add_raw_landing_lineage.sql
├── V005__add_clinical_history_policy.sql
├── V006__add_medications_and_procedures.sql
└── V007__add_minimal_clinical_terminologies.sql
```

Migration history is stored in `public.schema_migrations`. The engine verifies contiguous ordering, names, checksums, detected structure, pending versions, and downgrade attempts. Migrations execute transactionally under a PostgreSQL advisory lock.

## Implemented capabilities

- six contract-governed clinical datasets;
- minimal versioned terminology registry;
- source-system aliases and normalized clinical concepts;
- reviewed mappings from local observations to LOINC;
- strict rejection of unknown, inactive, or wrong-domain codes;
- immutable content-addressed raw capture and append-only receipts;
- normalized validation errors and rejected-record quarantine;
- source, raw, contract, run, record, terminology, and cohort lineage;
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

The demo captures, validates, migrates, normalizes coded concepts, persists, builds the hypertension cohort, and writes:

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

A current database reports:

```text
detected=7
current=7
latest=7
pending=[]
```

## Expected bundled sample

| Dataset | Received | Valid | Invalid | Persisted |
|---|---:|---:|---:|---:|
| Patients | 8 | 5 | 3 | 5 |
| Encounters | 8 | 7 | 1 | 7 |
| Diagnoses | 7 | 6 | 1 | 6 |
| Observations | 14 | 13 | 1 | 13 |
| Medications | 7 | 6 | 1 | 6 |
| Procedures | 7 | 6 | 1 | 6 |

The four coded event tables produce 31 normalized terminology bindings. The default hypertension cohort contains `P001` and `P002`.

## Inspect normalized codes

```sql
SELECT
    dataset_name,
    entity_id,
    source_system,
    source_code,
    normalized_system,
    normalized_code,
    normalized_display,
    domain,
    verification_status
FROM terminology.normalized_clinical_codes
ORDER BY dataset_name, entity_id;
```

## Python terminology API

```python
from clinical_data_platform.terminology import (
    list_terminology_systems,
    resolve_terminology_concept,
    validate_terminology_bindings,
)
```

Example:

```python
concept = resolve_terminology_concept(
    connection,
    "LOCAL_OBSERVATION",
    "SYSTOLIC_BP",
    "observation",
)

assert concept.code_system_id == "LOINC"
assert concept.code == "8480-6"
```

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

CI exercises contracts, V001–V007 migrations, raw capture, patient history, all six entities, terminology resolution and rejection, immutable-event rollback, cohort generation, and container smoke tests.

## Documentation

- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): snapshot and immutable-event policy;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/terminology.md`](docs/terminology.md): terminology model, mappings, and licensing boundary;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): review sequence and SQL;
- [`docs/learning/minimal-clinical-terminologies-es.md`](docs/learning/minimal-clinical-terminologies-es.md): detailed Spanish study guide;
- additional learning guides under [`docs/learning/`](docs/learning/).

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- complete execution states and structured logging;
- reproducible Synthea datasets;
- bulk PostgreSQL `COPY` loading and benchmarks;
- an additional cohort with attrition and missingness reporting;
- coverage of at least 90%;
- multi-version CI, security, container, and release hardening.

The terminology layer remains a small local subset. It does not provide complete releases, automated synchronization, hierarchy queries, UCUM normalization, multilingual terms, FHIR terminology operations, or clinical validation of code selection.

The project intentionally excludes identifiable patient data, production decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
