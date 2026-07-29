# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.10.0` adds complete execution states and durable failure auditing.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like source files become auditable, analysis-ready, terminology-linked datasets.

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
Hash-chained local execution journal
        │
        ▼
Generic validation pipeline
        ├── valid rows
        ├── quarantined rows
        ├── normalized errors
        └── quality report: validated
        │
        ▼
Formal PostgreSQL migrations V001–V008
        │
        ▼
Durable execution audit
        ├── current run state
        ├── ordered event timeline
        └── failures retained after clinical rollback
        │
        ▼
Terminology resolution and clinical persistence
        │
        ▼
Versioned cohort SQL and feature export
```

There is no patient-specific validation pipeline and no monolithic schema installer.

## Complete execution lifecycle

A normal run follows:

```text
created
→ raw_captured
→ validating
→ validated
→ loading
→ completed
```

A failed load remains auditable:

```text
validated
→ loading       attempt 1
→ failed        attempt 1
```

After the external problem is corrected, the same validated run can continue:

```text
failed
→ loading       attempt 2
→ completed     attempt 2
```

`completed` is terminal. Unsupported transitions are rejected by PostgreSQL.

### Why failures survive rollback

Loading uses separate transaction boundaries:

1. the validated run, imported local journal, and `loading` transition are committed;
2. clinical rows, validation errors, and `completed` are committed atomically;
3. when step 2 fails, clinical writes roll back and a new transaction stores `failed` with its stage, exception type, message, SQLSTATE, details, and attempt number.

This preserves both requirements:

```text
no partial clinical data
+ durable evidence of the failed attempt
```

### Local and durable journals

Validation writes:

```text
data/processed/<dataset>/execution/<run-id>.jsonl
```

Each event contains its own SHA-256 and the previous event SHA-256. Before loading, the platform verifies identities, sequence, state transitions, hashes, and chain continuity.

PostgreSQL stores the imported and loading-stage timeline in:

```text
audit.pipeline_run_events
```

The current projection is stored in:

```text
audit.pipeline_runs
```

Runs created before V008 receive an explicit evidence gap:

```text
audit_gap_reason = pre_v008_execution_history_unavailable
```

No historical events are fabricated.

See [`docs/execution-audit.md`](docs/execution-audit.md).

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

Every event references a patient and encounter. Exact event duplicates preserve the original row and lineage. Reusing an event identifier with different business content rolls back the clinical transaction and leaves a failed execution timeline.

## Minimal terminology layer

V007 creates:

```text
terminology.code_systems
terminology.system_aliases
terminology.concepts
terminology.concept_mappings
terminology.normalized_clinical_codes
```

The installed subset registers ICD-10-CM, LOINC, RxNorm, ATC, SNOMED CT, CPT, ICD-10-PCS, and the project-local observation system. External systems are represented by small local subsets, not complete releases.

Bundled local-to-LOINC mappings:

| Local source code | Normalized code |
|---|---|
| `SYSTOLIC_BP` | `LOINC:8480-6` |
| `DIASTOLIC_BP` | `LOINC:8462-4` |
| `HEART_RATE` | `LOINC:8867-4` |

Unknown systems, unknown codes, inactive concepts, and wrong-domain concepts are rejected during persistence. The resulting failure is audited while clinical rows are rolled back.

See [`docs/terminology.md`](docs/terminology.md).

## Clinical history policy

Every current clinical row has a `record_sha256` calculated from normalized business content. Lineage and terminology foreign keys are excluded so operational metadata does not create false clinical changes.

Patient demographic changes append SCD Type 2 versions to `clinical.patient_history`. Encounter, diagnosis, observation, medication, and procedure events are immutable.

## Immutable raw landing zone

Sources are captured before parsing under:

```text
data/raw/
├── objects/sha256/<prefix>/<sha256>/source.csv
└── receipts/<dataset>/<YYYY>/<MM>/<DD>/<receipt-uuid>.json
```

Identical files share one content object, while each reception has a separate append-only receipt. The implementation verifies checksums, byte sizes, paths, and manifest lineage before persistence.

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

The contract engine executes structural, required-value, uniqueness, type, categorical, temporal, unit, and plausible-range rules. Every validation run records exact contract path, version, and SHA-256.

## PostgreSQL migrations

```text
migrations/
├── V001__create_core_clinical_schema.sql
├── V002__add_longitudinal_entities_and_cohorts.sql
├── V003__add_contract_lineage.sql
├── V004__add_raw_landing_lineage.sql
├── V005__add_clinical_history_policy.sql
├── V006__add_medications_and_procedures.sql
├── V007__add_minimal_clinical_terminologies.sql
└── V008__add_execution_lifecycle_audit.sql
```

Migration history is stored in `public.schema_migrations`. The engine verifies contiguous ordering, names, checksums, detected structure, pending versions, and downgrade attempts. Migrations execute transactionally under a PostgreSQL advisory lock.

## Implemented capabilities

- six contract-governed clinical datasets;
- explicit run state machine and retry attempts;
- hash-chained local validation journals;
- durable PostgreSQL execution timelines and failure metadata;
- clinical rollback without losing failure evidence;
- minimal versioned terminology registry and normalized concepts;
- immutable content-addressed raw capture and append-only receipts;
- normalized validation errors and rejected-record quarantine;
- source, raw, contract, run, record, terminology, and cohort lineage;
- formal install, upgrade, baseline, and drift checks;
- patient SCD Type 2 history and immutable clinical events;
- transactional and run-idempotent persistence;
- versioned hypertension cohort and baseline features;
- Docker, Docker Compose, PowerShell, POSIX, Ruff, strict mypy, pytest, coverage, PostgreSQL integration tests, and GitHub Actions.

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

The demo captures, validates, audits, migrates, normalizes coded concepts, persists, builds the hypertension cohort, and writes:

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
detected=8
current=8
latest=8
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

The clean demo produces six completed runs with six events each, 31 normalized terminology bindings, and a hypertension cohort containing `P001` and `P002`.

## Inspect execution state

```sql
SELECT
    run_id,
    dataset_name,
    status,
    current_stage,
    attempt_count,
    failure_code,
    failure_message,
    audit_event_count,
    audit_gap_reason
FROM audit.pipeline_runs
ORDER BY updated_at DESC;
```

Timeline for one run:

```sql
SELECT
    sequence_number,
    attempt_number,
    from_status,
    to_status,
    stage,
    occurred_at,
    error_code,
    error_message,
    event_sha256
FROM audit.pipeline_run_timeline
WHERE run_id = '<run-uuid>'
ORDER BY sequence_number;
```

Python API:

```python
from clinical_data_platform.run_audit import (
    get_pipeline_run,
    list_pipeline_run_events,
    validate_pipeline_run_audit,
)
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

CI exercises contracts, V001–V008 migrations, raw capture, local and durable audit chains, retries, failure rollback, patient history, six entities, terminology resolution, cohort generation, and container smoke tests.

## Documentation

- [`docs/architecture.md`](docs/architecture.md): system architecture and boundaries;
- [`docs/database.md`](docs/database.md): migrations, persistence, and lineage;
- [`docs/execution-audit.md`](docs/execution-audit.md): lifecycle, transactions, retries, and inspection;
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md): snapshot and immutable-event policy;
- [`docs/clinical-entities.md`](docs/clinical-entities.md): six-entity model;
- [`docs/terminology.md`](docs/terminology.md): terminology model and licensing boundary;
- [`docs/analysis-guide.md`](docs/analysis-guide.md): review sequence and SQL;
- [`docs/learning/execution-audit-es.md`](docs/learning/execution-audit-es.md): detailed Spanish study guide;
- additional learning guides under [`docs/learning/`](docs/learning/).

## Current limitations

The repository is not yet version `1.0.0`. Remaining milestones include:

- structured application logging;
- reproducible Synthea datasets;
- bulk PostgreSQL `COPY` loading and benchmarks;
- an additional cohort with attrition and missingness reporting;
- coverage of at least 90%;
- multi-version CI, security, container, and release hardening.

The execution journal is tamper-evident but not administrator-resistant WORM storage. The terminology layer remains a small local subset. The project intentionally excludes identifiable patient data, production decision support, enterprise authentication, and regulatory deployment claims.

## License

MIT License. See [`LICENSE`](LICENSE).
