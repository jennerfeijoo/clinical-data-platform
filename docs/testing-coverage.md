# Testing and coverage policy

## Purpose

The coverage gate provides a measurable lower bound for exercised Python behavior. It is intended to prevent untested code growth and to make missing test evidence visible during review.

It does not prove that the platform is clinically correct, production-ready, secure, free from defects, representative of real populations, or suitable for identifiable patient data.

## Enforced threshold

Version `0.17.0` requires at least **90% statement coverage** across the `clinical_data_platform` package.

The shared configuration is stored in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-ra --strict-markers --cov=clinical_data_platform --cov-report=term-missing --cov-fail-under=90"

[tool.coverage.run]
source = ["clinical_data_platform"]

[tool.coverage.report]
fail_under = 90
show_missing = true
skip_covered = false
```

A normal test invocation therefore enforces the threshold locally and in GitHub Actions:

```bash
python -m pytest
```

A result below 90 exits non-zero. This makes the threshold a merge gate rather than a documentation-only target.

## Reference result

The validated pull-request run recorded:

```text
3,935 measured statements
3,547 covered statements
388 missed statements
90.14% total statement coverage
142 tests passed
```

The project moved from 82% to 90.14% without adding module exclusions or coverage pragmas for the new milestone.

## Test portfolio

### Real deterministic executions

Tests execute the following behavior against packaged definitions, temporary directories, and synthetic fixtures:

- contract discovery, rendering, and validation;
- immutable raw capture and receipt verification;
- generic dataset validation;
- Synthea profile loading;
- Synthea CSV adaptation and verification;
- independent cohort comparison;
- attrition and missingness report generation;
- path-safety and staged publication behavior;
- PostgreSQL integration through the existing disposable CI service.

### Controlled external boundaries

Unit tests replace external or expensive boundaries when the purpose is to test orchestration rather than the dependency itself:

- Java and the full Synthea generator;
- Git subprocess execution;
- selected database command paths;
- benchmark timing execution.

The doubles must preserve the expected interface and allow assertions on arguments, ordering, outputs, and propagated failures. They must not be used to claim that the substituted external system was validated.

### Failure-path tests

Coverage includes governed rejection of:

- malformed or invalid UTF-8 TOML profiles;
- missing profile tables and invalid field types;
- unsupported schema versions;
- invalid reference dates, seeds, population sizes, Java requirements, thread counts, and retained-history settings;
- missing or malformed JSON manifests;
- missing CSV files and unexpected headers;
- missing executables and failed subprocesses;
- non-Git checkouts, wrong tags, and dirty worktrees;
- unsupported Java version text and versions below the required minimum;
- unsafe report replacement paths and failed publication.

These tests are valuable because many data-platform failures occur at trust boundaries rather than in the nominal happy path.

## Interpretation rules

Coverage answers:

> Which measured Python statements were executed by at least one test?

Coverage does not answer:

- whether every assertion is correct;
- whether all input combinations were explored;
- whether clinical semantics are valid;
- whether concurrency behavior is correct;
- whether performance targets are met;
- whether a security vulnerability exists;
- whether real healthcare data can be processed safely.

A line can be executed without its outcome being meaningfully asserted. For this reason, new tests should be behavioral: they should verify returned values, persisted state, generated artifacts, emitted errors, or dependency calls.

## Maintenance policy

Every change that adds executable behavior must do one of the following:

1. add tests that preserve total coverage at or above 90%;
2. refactor unreachable or obsolete code out of the package;
3. justify a narrowly scoped exclusion during review.

Broad module exclusions and lowering `fail_under` are not acceptable substitutes for test evidence.

Before opening a pull request, run:

```bash
python -m ruff check .
python -m mypy src
python -m pytest
```

The coverage report lists every unexecuted line. Reviewers should inspect both the percentage and the test assertions that produced it.

## Scope boundary

All repository fixtures remain synthetic. The coverage milestone does not introduce PHI and does not change the repository's non-clinical, non-regulatory status.
