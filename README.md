# Clinical Data Platform

> Status: stable software release — version `1.0.0` provides governed synthetic clinical data engineering with reproducible artifacts, PostgreSQL-backed validation, mandatory quality gates, and an explicitly non-clinical scope.

Clinical Data Platform is a synthetic clinical data engineering project demonstrating how healthcare-like CSV sources become auditable, terminology-linked, analysis-ready datasets.

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

## Installation

Development installation:

```bash
python -m venv .venv
python -m pip install --upgrade pip "setuptools>=83"
python -m pip install -e ".[dev,security,release]"
python -m pip check
```

A wheel produced by the release gate can be installed directly:

```bash
python -m pip install clinical_data_platform-1.0.0-py3-none-any.whl
clinical-data validate-contracts
clinical-data-cohort list-profiles
```

The project is not published to PyPI by the current workflow. Governed artifacts are published as GitHub Release assets until Trusted Publishing is configured and reviewed separately.

## Stable release scope

Version `1.0.0` declares the package interface, executable contracts, migration chain, runtime resources, command-line entrypoints, and governed artifact process stable for the documented synthetic-data use case.

“Stable” describes software maturity and compatibility policy. It does **not** mean the platform is validated for patient care, PHI, clinical decisions, regulated deployment, epidemiological inference, or production healthcare operations.

The stable release contains no schema change beyond the already validated V001–V008 migration chain. Future backward-incompatible package, contract, CLI, or persisted-schema changes require a new major version.

- [Stable release readiness](docs/stable-release-readiness.md)
- [Current limitations](docs/limitations.md)

## Release engineering

The governed artifact boundary is:

```text
validated commit
→ version-consistency gate
→ wheel + source distribution
→ second independent build
→ byte-for-byte comparison
→ metadata and content inspection
→ clean wheel installation outside the repository
→ SHA256SUMS + release-manifest.json
→ tag-driven GitHub Release
```

The release gate requires agreement among `pyproject.toml`, package `__version__`, CHANGELOG, CITATION metadata, README, package tests, CI, and the tag `vX.Y.Z`.

The wheel contains the executable package and runtime resources, including contracts, migrations, Synthea profiles, `py.typed`, and the default hypertension cohort SQL. Repository-only documentation, tests, scripts, and generated datasets are excluded from the wheel.

Local release checks:

```bash
python scripts/check_release.py --expected-version 1.0.0
python -m build --outdir dist
python -m twine check dist/*
python scripts/verify_distribution.py dist \
  --expected-version 1.0.0 \
  --manifest release-manifest.json \
  --checksums SHA256SUMS
```

- [Release process](docs/release-process.md)
- [Documentation index](docs/index.md)
- [CLI reference](docs/cli-reference.md)
- [Contributing](CONTRIBUTING.md)
- [Support policy](SUPPORT.md)
- [Citation metadata](CITATION.cff)

## Hardened non-root container

The runtime image uses a fixed identity and a restricted execution profile:

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

A writable operation requires an explicit volume writable by UID `10001`.

- [Container hardening](docs/container-hardening.md)
- [Spanish learning guide](docs/learning/contenedor-no-root-es.md)

## Security and dependency scanning

Independent controls cover different risk surfaces:

| Surface | Control | Blocking policy |
|---|---|---|
| Resolved Python environment | `pip-audit` | Known vulnerabilities fail pull requests, pushes, scheduled scans, and manual runs |
| Python source patterns | Bandit | New findings with at least medium severity and confidence fail the job |
| Python data flows | CodeQL `security-extended` | Results are published to GitHub code scanning |
| Built container image | Trivy | Fixed high or critical OS/library vulnerabilities fail the job |
| Dependency freshness | Dependabot | Weekly update pull requests for Python, Actions, and Docker |
| Workflow supply chain | Full commit-SHA action pins | Policy tests reject mutable action tags and branches |

The dependency audit includes development, security, and release tooling and publishes JSON evidence plus a CycloneDX SBOM. GitHub Dependency Review is not presented as implemented because Dependency Graph is not enabled; the complete resolved head environment is audited instead.

```bash
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii -b security/bandit-baseline.json
```

- [Security policy](SECURITY.md)
- [Security scanning](docs/security-scanning.md)

## Python compatibility and testing

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

The project enforces at least 90% statement coverage:

```bash
python -m ruff check .
python -m mypy src
python -m pytest
```

Coverage is a regression barrier, not proof of clinical correctness, security, or production readiness.

- [Python compatibility](docs/python-compatibility.md)
- [Testing and coverage](docs/testing-coverage.md)

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

The package contains two matched-design Synthea 4.0.0 profiles with the same population size, reference date, geography, export scope, and thread count. Only patient and clinician seeds differ.

```powershell
.\scripts\generate_synthea_cohorts.ps1
.\scripts\load_synthea_cohorts.ps1 -ReplaceComparison
.\scripts\report_synthea_quality.ps1
```

The pair comparison requires distinct profile and adaptation fingerprints plus zero identifier overlap across all six clinical entities. Quality evidence includes source rows, adapted rows, explicit omission reasons, source missingness, contract-aware missingness, row completeness, cohort comparison, and stable fingerprints.

- [Synthea adapter](docs/synthea.md)
- [Independent cohorts](docs/synthea-cohorts.md)
- [Attrition and missingness](docs/attrition-missingness.md)

## PostgreSQL loading and benchmark

Validated rows are streamed through PostgreSQL `COPY` into typed temporary staging tables and merged into governed clinical targets with triggers, constraints, terminology resolution, lineage, and transaction boundaries active.

The benchmark compares this path with the former `executemany` implementation using deterministic synthetic workloads and database-fingerprint equivalence checks.

- [Bulk loading](docs/bulk-loading.md)
- [Loading benchmark](docs/loading-benchmark.md)

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

The stable release introduces no `V009` because it changes versioning, documentation, tests, and release metadata rather than persistent database objects.

## Local synthetic demo

```powershell
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

## Implemented capabilities

- generic contract-governed architecture and versioned executable contracts;
- formal PostgreSQL migrations and immutable content-addressed raw landing;
- six clinical entities, terminology subsets, SCD2 patient history, and immutable events;
- complete execution states, retries, durable failures, and structured JSON logs;
- reproducible Synthea generation, two independent cohorts, and quality reports;
- PostgreSQL COPY loading and a correctness-gated benchmark;
- mandatory statement coverage of at least 90%;
- PostgreSQL-backed CPython 3.11–3.14 compatibility CI;
- dependency, source, workflow, and container security scanning;
- fixed non-root container identity and hardened runtime profile;
- reproducible wheel and source-distribution builds, clean-install testing, checksums, citation metadata, and tag-driven GitHub Releases;
- stable `1.0.0` compatibility contract for the documented synthetic-data workflow.

## Documentation

Use the [documentation index](docs/index.md) as the primary map. Key references:

- [CLI reference](docs/cli-reference.md)
- [Architecture](docs/architecture.md)
- [Database](docs/database.md)
- [Execution audit](docs/execution-audit.md)
- [Structured logging](docs/structured-logging.md)
- [Clinical history policy](docs/clinical-history-policy.md)
- [Clinical entities](docs/clinical-entities.md)
- [Terminology](docs/terminology.md)
- [Current limitations](docs/limitations.md)
- [Stable release readiness](docs/stable-release-readiness.md)
- [Release process](docs/release-process.md)

## Current limitations

Version `1.0.0` is stable for the documented synthetic clinical data engineering use case. It is not a claim of healthcare production readiness.

The repository is not PHI-ready. The Synthea Java generator is not executed in normal CI. Contract validation still materializes complete source datasets. The two-cohort load is not one global transaction. Attrition is technical row exclusion, not participant follow-up. Missingness classification does not establish MCAR, MAR, or MNAR. The benchmark measures initial single-writer loading, not production capacity. Automated security tools, container hardening, and artifact checks do not replace clinical validation, threat modeling, penetration testing, secret management, deployment governance, or regulatory controls.

See [the consolidated limitation register](docs/limitations.md).

## License

MIT License. See [`LICENSE`](LICENSE).
