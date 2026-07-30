# Contributing

Clinical Data Platform accepts changes that preserve its synthetic-only, auditable, reproducible engineering scope.

## Scope and data boundary

Do not commit, upload, paste, or reference identifiable patient information, credentials, private keys, access tokens, proprietary datasets, or data whose license is unclear. Tests, examples, issues, and pull requests must use synthetic or appropriately licensed public data.

The project is not a clinical decision system, a PHI platform, or a regulatory implementation. Contributions must not broaden those claims without corresponding architecture, governance, validation, and documentation.

## Development setup

```bash
python -m venv .venv
python -m pip install --upgrade pip "setuptools>=83"
python -m pip install -e ".[dev,security,release]"
python -m pip check
```

Start the PostgreSQL service and configure the synthetic test database:

```bash
docker compose up -d postgres
export DATABASE_URL="postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
```

On PowerShell, set the variable with:

```powershell
$env:DATABASE_URL = "postgresql://clinical_user:clinical_password@localhost:5432/clinical_data"
```

## Required checks

Run these before opening a pull request:

```bash
python -m ruff check .
python -m mypy src
python -m pytest
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii -b security/bandit-baseline.json
python scripts/check_release.py --expected-version 1.0.0
```

The suite enforces at least 90% statement coverage. PostgreSQL integration tests require the configured disposable database.

## Change design

- Create a focused branch from the current `main` commit.
- Keep contracts, migrations, raw lineage, terminology, execution audit, and clinical history policies explicit.
- Add behavioral tests for success, failure, rollback, idempotency, and boundary conditions when applicable.
- Preserve deterministic inputs, reference dates, seeds, hashes, and fingerprints.
- Update README, technical documentation, learning documentation, and CHANGELOG when behavior or claims change.
- Do not weaken security, coverage, migration, or runtime gates merely to obtain a green workflow.

## Database changes

Persistent schema changes require a new immutable migration named:

```text
VNNN__lowercase_description.sql
```

Never edit the contents of an applied migration. Add migration tests covering upgrades from the previous version, currentness detection, checksums, and partial-schema rejection.

## Contracts and terminology

Contract changes require a new versioned contract resource and an explicit manifest update. Terminology additions must identify their code system and remain clearly described as local subsets unless a complete licensed release is actually incorporated.

## Pull requests

A pull request should state:

- the engineering problem and boundary;
- the design and alternatives considered;
- data and migration effects;
- new tests and evidence;
- documentation changes;
- known limitations and claims that remain unsupported.

All external GitHub Actions must be pinned to full commit SHAs. Dependency changes are audited in CI.

## Security reports

Do not publish exploit details in a public issue. Follow [`SECURITY.md`](SECURITY.md).

## Release changes

Version changes must keep `pyproject.toml`, `clinical_data_platform.__version__`, `CHANGELOG.md`, `CITATION.cff`, README, CI metadata assertions, and package tests synchronized. The governed procedure is documented in [`docs/release-process.md`](docs/release-process.md).
