# Python compatibility policy

Version `0.18.0` makes Python-version compatibility an executable CI property rather than an informal statement.

## Supported range

The package metadata declares:

```toml
requires-python = ">=3.11,<3.15"
```

The supported CPython versions are therefore:

```text
3.11
3.12
3.13
3.14
```

Python 3.11 is the minimum and reference version. Python 3.15 and later are intentionally rejected until a future change adds them to the tested matrix and updates package metadata.

## CI design

The workflow separates two responsibilities.

### Reference quality job

Python 3.11 runs the complete reference pipeline:

- dependency installation and `pip check`;
- structured logging smoke test;
- Synthea adaptation and verification;
- two-cohort comparison and quality reporting;
- contract and migration validation;
- raw landing-zone smoke test;
- Ruff and strict mypy;
- the full pytest suite with the mandatory 90% statement-coverage threshold;
- Docker build and container smoke tests.

The governed loading benchmark also remains pinned to Python 3.11 so performance evidence is not confounded by interpreter changes.

### Compatibility matrix

Python 3.12, 3.13, and 3.14 each run in an independent GitHub Actions job with:

- a separate PostgreSQL 16 service container;
- editable installation of the package and development dependencies;
- dependency consistency validation with `python -m pip check`;
- package-version and interpreter-version assertions;
- executable contract validation;
- packaged Synthea-profile discovery;
- migration and database validation;
- the complete pytest and PostgreSQL integration suite;
- the same mandatory 90% statement-coverage threshold.

The matrix uses `fail-fast: false`. Every supported interpreter reports its own result even when another matrix entry fails.

## Why the upper bound exists

An open-ended declaration such as `>=3.11` would allow installation on a future interpreter that has never passed this repository's tests. The `<3.15` bound aligns package installation with the versions proven by CI.

Adding a new Python minor version requires all of the following in one reviewed change:

1. extend the compatibility matrix;
2. update `requires-python` and classifiers;
3. run the full PostgreSQL-backed suite on the new version;
4. retain the coverage threshold;
5. update this document, the README, and the changelog.

## Policy-drift test

`tests/test_python_compatibility_policy.py` verifies that:

- package metadata declares the intended range;
- all four supported-version classifiers exist;
- Python 3.11 remains the reference job;
- the compatibility matrix contains Python 3.12, 3.13, and 3.14;
- `fail-fast: false`, `pip check`, pytest, and `setup-python@v6` remain present;
- the benchmark remains pinned to the reference interpreter.

This test does not replace GitHub Actions execution. It prevents common configuration drift before the workflow starts.

## Local checks

Run the currently active interpreter:

```bash
python --version
python -m pip install -e ".[dev]"
python -m pip check
python -m pytest
```

Local success proves only the interpreter currently selected on that machine. The GitHub Actions matrix is the authoritative multi-version result.

## Interpretation limits

Passing the matrix demonstrates compatibility with the tested CPython versions, dependency set, PostgreSQL service, and synthetic fixtures used by CI. It does not prove:

- compatibility with alternative Python implementations;
- compatibility with Python 3.15 or later;
- support for every operating system or architecture;
- clinical correctness or production suitability;
- PHI readiness, regulatory compliance, or complete security.
