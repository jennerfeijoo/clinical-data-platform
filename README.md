# Clinical Data Platform

> Status: active development toward `1.0.0` — version `0.20.0` runs the application container as a fixed non-root identity and validates a read-only, capability-free runtime.

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

## Hardened non-root container

Version `0.20.0` changes the runtime image and its validation policy:

| Control | Enforced behavior |
|---|---|
| Runtime identity | UID/GID `10001:10001`; no root fallback |
| Login surface | User `clinical` has `/usr/sbin/nologin` |
| Root filesystem | CI and Compose run it read-only |
| Linux capabilities | All capabilities are dropped |
| Privilege escalation | `no-new-privileges:true` |
| Temporary writes | `/tmp` is a `tmpfs` with `noexec,nosuid` |
| Process ceiling | `pids_limit: 256` |
| Application files | `/app`, `/opt/venv`, bundled samples, and SQL are read-only |
| Persistent outputs | Raw, processed, and analytics paths use explicit writable volumes |

The Dockerfile also removes package managers and Python bootstrap tooling from the final image, strips setuid/setgid bits from standard executable paths, and copies only the bundled sample data required by the demo.

Reference hardened execution:

```bash
docker build --tag clinical-data-platform:local .
docker run --rm \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --pids-limit 256 \
  clinical-data-platform:local validate-contracts
```

A writable operation requires an explicit volume owned by, or writable for, UID `10001`. CI verifies that raw receipt files are actually created by UID `10001` rather than by root.

- Technical policy: [`docs/container-hardening.md`](docs/container-hardening.md)
- Spanish guide: [`docs/learning/contenedor-no-root-es.md`](docs/learning/contenedor-no-root-es.md)

## Security and dependency scanning

Version `0.19.0` added independent controls for different risk surfaces:

| Surface | Control | Blocking policy |
|---|---|---|
| Resolved Python environment | `pip-audit` | Known vulnerabilities fail every pull request, push, scheduled scan, and manual run. |
| Python source patterns | Bandit | New findings with at least medium severity and confidence fail the job. |
| Python data flows | CodeQL `security-extended` | Results are published to GitHub code scanning. |
| Built container image | Trivy | Fixed high or critical OS/library vulnerabilities fail the job. |
| Dependency freshness | Dependabot | Weekly update pull requests for Python, Actions, and Docker. |
| Workflow supply chain | Full commit-SHA action pins | Policy tests reject mutable action tags and branches. |

The security workflow publishes JSON audit evidence and a CycloneDX Python SBOM. The Bandit gate uses a reviewed baseline containing exactly two B608 findings whose SQL fragments are selected only from internal constants; it does not disable B608 globally.

GitHub Dependency Review is not presented as implemented because Dependency Graph is not enabled for this repository. Pull requests are instead gated by auditing the complete resolved head environment. This blocks known vulnerabilities but does not provide a base-versus-head dependency diff.

Local checks:

```bash
python -m pip install --upgrade pip "setuptools>=83"
python -m pip install -e ".[dev,security]"
python -m pip check
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii -b security/bandit-baseline.json
```

- Security policy: [`SECURITY.md`](SECURITY.md)
- Technical policy: [`docs/security-scanning.md`](docs/security-scanning.md)
- Spanish guide: [`docs/learning/security-dependencias-es.md`](docs/learning/security-dependencias-es.md)

A green scan means that the configured tools found no blocking issue under their current advisory databases, rules, thresholds, baseline, and environment. It does not prove absence of vulnerabilities, secure deployment, PHI readiness, regulatory compliance, or clinical safety.

## Python compatibility

Version `0.20.0` retains the explicitly tested range:

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

Python 3.11 runs Ruff, strict mypy, coverage, Docker, hardened container smoke tests, and the governed loading benchmark. Python 3.12–3.14 each receive an isolated PostgreSQL 16 service and run installation, `pip check`, contracts, migrations, and the complete coverage-gated test suite.

- Technical policy: [`docs/python-compatibility.md`](docs/python-compatibility.md)
- Spanish guide: [`docs/learning/compatibilidad-python-ci-es.md`](docs/learning/compatibilidad-python-ci-es.md)

## Mandatory test coverage

The project enforces at least 90% statement coverage through shared pytest configuration:

```bash
python -m pytest
```

Coverage is a regression barrier, not proof of clinical correctness, security, or production readiness.

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
→ stable fingerprints
```

- [`docs/synthea.md`](docs/synthea.md)
- [`docs/synthea-cohorts.md`](docs/synthea-cohorts.md)
- [`docs/attrition-missingness.md`](docs/attrition-missingness.md)

## PostgreSQL loading and benchmark

Validated rows are streamed through PostgreSQL `COPY` into typed temporary staging tables and then merged into governed clinical targets with triggers, constraints, terminology resolution, lineage, and transaction boundaries active.

The benchmark compares this route with the former `executemany` implementation using deterministic synthetic workloads and database-fingerprint equivalence checks.

- [`docs/bulk-loading.md`](docs/bulk-loading.md)
- [`docs/loading-benchmark.md`](docs/loading-benchmark.md)

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

The container-hardening milestone introduces no `V009` because it changes image construction, runtime policy, CI, tests, Compose, and documentation rather than persistent database objects.

## Local development

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip "setuptools>=83"
python -m pip install -e ".[dev,security]"
python -m pip check

Copy-Item .env.example .env
docker compose up -d postgres
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"

clinical-data database-migrate
clinical-data database-validate
clinical-data run-demo --repository-root .
```

Hardened Compose demo:

```bash
docker compose --profile demo up --build --abort-on-container-exit app
```

Quality checks:

```bash
clinical-data validate-contracts
clinical-data-cohort list-profiles
python -m ruff check .
python -m mypy src
python -m pytest
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii -b security/bandit-baseline.json
docker build --tag clinical-data-platform:local .
```

## Implemented capabilities

- generic contract-governed architecture and versioned executable contracts;
- formal PostgreSQL migrations and immutable content-addressed raw landing;
- six clinical entities, minimal terminology integration, SCD2 history, and immutable events;
- complete execution states, retries, durable failures, and structured JSON logs;
- reproducible Synthea generation, two independent cohorts, and quality reports;
- PostgreSQL COPY loading and a correctness-gated benchmark;
- mandatory statement coverage of at least 90%;
- PostgreSQL-backed CPython 3.11–3.14 compatibility CI;
- `pip-audit`, Bandit with a governed baseline, CodeQL, Trivy, Dependabot, and full-SHA action pinning;
- a fixed non-root container identity, read-only root filesystem policy, dropped capabilities, no-new-privileges, and explicit writable volumes;
- Docker, Compose, PowerShell, POSIX, Ruff, strict mypy, pytest, and GitHub Actions.

## Documentation

- [`docs/container-hardening.md`](docs/container-hardening.md)
- [`docs/security-scanning.md`](docs/security-scanning.md)
- [`docs/python-compatibility.md`](docs/python-compatibility.md)
- [`docs/testing-coverage.md`](docs/testing-coverage.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/database.md`](docs/database.md)
- [`docs/execution-audit.md`](docs/execution-audit.md)
- [`docs/clinical-history-policy.md`](docs/clinical-history-policy.md)
- [`docs/clinical-entities.md`](docs/clinical-entities.md)
- [`docs/terminology.md`](docs/terminology.md)

## Current limitations

Remaining milestone before `1.0.0`:

- final documentation and release engineering.

The repository is not PHI-ready. The Synthea Java generator is not executed in normal CI. Contract validation still materializes complete source datasets. The two-cohort load is not one global transaction. Attrition is technical row exclusion, not participant follow-up. Missingness classification does not establish MCAR, MAR, or MNAR. The benchmark measures initial single-writer loading, not production capacity. Automated security tools and container hardening do not replace threat modeling, manual review, penetration testing, secret management, network policy, deployment hardening, or regulatory controls.

## License

MIT License. See [`LICENSE`](LICENSE).
