# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.18.0` adds PostgreSQL-backed CI across CPython 3.11–3.14 while retaining mandatory statement coverage of at least 90%.

Clinical Data Platform is a synthetic clinical data engineering project that demonstrates how healthcare-like CSV sources become auditable, terminology-linked, analysis-ready datasets.

The repository uses synthetic data only. It is intended for engineering review and learning, not for identifiable patient data, clinical decisions, epidemiological inference, regulatory deployment, or production healthcare operations.

## Architecture

```text
Pinned Synthea profile or external CSV
            │
            ▼
Immutable raw landing zone
            │
            ▼
Versioned executable contract
            │
            ▼
Generic validation pipeline
            │
            ▼
PostgreSQL COPY → typed temporary staging
            │
            ▼
Governed target merge
    ├── terminology normalization
    ├── record hashes and lineage
    ├── patient SCD Type 2 history
    ├── immutable clinical events
    └── audited execution states
            │
            ├── versioned analytical cohorts
            ├── reproducible loading benchmark
            └── attrition and missingness evidence
```

## Python compatibility

Version `0.18.0` declares:

```toml
requires-python = ">=3.11,<3.15"
```

| CPython | CI role |
|---|---|
| 3.11 | minimum and reference-quality environment |
| 3.12 | PostgreSQL-backed compatibility matrix |
| 3.13 | PostgreSQL-backed compatibility matrix |
| 3.14 | PostgreSQL-backed compatibility matrix |
| 3.15+ | rejected until explicitly tested |

Python 3.11 runs Ruff, strict mypy, coverage, Docker, container smoke tests, and the governed loading benchmark. Python 3.12–3.14 each receive an isolated PostgreSQL 16 service and run installation, `pip check`, contracts, migrations, and the complete coverage-gated test suite.

The matrix uses `fail-fast: false`, so every supported interpreter reports independently.

- Technical policy: [`docs/python-compatibility.md`](docs/python-compatibility.md)
- Spanish guide: [`docs/learning/compatibilidad-python-ci-es.md`](docs/learning/compatibilidad-python-ci-es.md)

## Mandatory test coverage

The project enforces at least 90% statement coverage through shared pytest configuration:

```text
3,935 measured statements
3,547 covered statements
388 missed statements
90.14% total coverage
142 tests passed
```

A normal `python -m pytest` run applies the threshold. Coverage is a regression barrier, not proof of clinical correctness, security, or production readiness.

- Technical policy: [`docs/testing-coverage.md`](docs/testing-coverage.md)
- Spanish guide: [`docs/learning/cobertura-pruebas-90-es.md`](docs/learning/cobertura-pruebas-90-es.md)

## Clinical model

```text
patients
   └── encounters
          ├── diagnoses
          ├── observations
          ├── medications
          └── procedures
```

| Dataset | Storage policy |
|---|---|
| patients | current snapshot + SCD Type 2 history |
| encounters | immutable event |
| diagnoses | immutable event + terminology binding |
| observations | immutable event + terminology binding |
| medications | immutable event + terminology binding |
| procedures | immutable event + terminology binding |

Exact duplicates preserve the original event and lineage. Conflicting identifier reuse rolls back the clinical transaction and leaves durable failure evidence.

## Reproducible Synthea cohorts

The package contains two matched-design Synthea 4.0.0 profiles with the same population size, reference date, geography, export scope, and thread count. Only the patient and clinician seeds differ.

The pair comparison requires distinct profile and adaptation fingerprints plus zero identifier overlap across all six clinical entities.

```powershell
.\scripts\generate_synthea_cohorts.ps1
.\scripts\load_synthea_cohorts.ps1 -ReplaceComparison
.\scripts\report_synthea_quality.ps1
```

Quality evidence includes:

```text
source rows
→ adapted rows
→ explicit omission reasons
→ source missingness
→ contract-aware missingness
→ row completeness
→ cohort comparison
→ stable fingerprint
```

See [`docs/synthea-cohorts.md`](docs/synthea-cohorts.md) and [`docs/attrition-missingness.md`](docs/attrition-missingness.md).

## PostgreSQL migrations

```text
V001 core schemas and patients
V002 encounters, diagnoses, observations, cohorts
V003 contract lineage
V004 raw lineage
V005 patient history and immutable-event policy
V006 medications and procedures
V007 minimal terminology integration
V008 execution lifecycle and durable failure audit
```

Expected state:

```text
detected=8
current=8
latest=8
pending=[]
```

The Python compatibility milestone introduces no V009 because it changes package metadata, workflows, tests, and documentation rather than persistent database objects.

## Local development

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip check

Copy-Item .env.example .env
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data database-migrate
clinical-data database-validate
clinical-data run-demo --repository-root .
```

Quality checks:

```bash
clinical-data validate-contracts
clinical-data-cohort list-profiles
python -m ruff check .
python -m mypy src
python -m pytest
docker build --tag clinical-data-platform:local .
```

A local run validates only the selected interpreter. GitHub Actions is the authoritative multi-version result.

## Implemented capabilities

- generic contract-governed architecture;
- executable versioned contracts and formal migrations;
- immutable content-addressed raw landing zone;
- six clinical entities and minimal terminology integration;
- patient SCD Type 2 history and immutable events;
- complete execution states, retries, durable failures, and structured JSON logs;
- reproducible Synthea generation, two independent cohorts, and quality reports;
- PostgreSQL COPY loading and a correctness-gated benchmark;
- mandatory statement coverage of at least 90%;
- PostgreSQL-backed CPython 3.11–3.14 CI;
- Docker, Compose, PowerShell, POSIX, Ruff, strict mypy, and pytest.

## Documentation

- [`docs/python-compatibility.md`](docs/python-compatibility.md)
- [`docs/testing-coverage.md`](docs/testing-coverage.md)
- [`docs/attrition-missingness.md`](docs/attrition-missingness.md)
- [`docs/synthea-cohorts.md`](docs/synthea-cohorts.md)
- [`docs/synthea.md`](docs/synthea.md)
- [`docs/loading-benchmark.md`](docs/loading-benchmark.md)
- [`docs/bulk-loading.md`](docs/bulk-loading.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/database.md`](docs/database.md)
- [`docs/execution-audit.md`](docs/execution-audit.md)
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md)
- [`docs/clinical-entities.md`](docs/clinical-entities.md)
- [`docs/terminology.md`](docs/terminology.md)

## Current limitations

Remaining milestones before `1.0.0`:

- dependency and security scanning;
- non-root container hardening;
- final documentation and release engineering.

The matrix covers CPython on Ubuntu runners, not every interpreter, operating system, or architecture. The full Synthea Java generator is not executed in normal CI. Attrition is technical row exclusion, not participant follow-up. Missingness classification does not establish MCAR, MAR, or MNAR. The benchmark measures initial single-writer loading, not production capacity. The repository is not PHI-ready.

## License

MIT License. See [`LICENSE`](LICENSE).
