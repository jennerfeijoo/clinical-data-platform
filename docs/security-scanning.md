# Security and dependency scanning

Version `0.19.0` adds executable security controls to the synthetic clinical data platform. These checks complement tests, type checking, database constraints, and audit lineage; they do not replace them.

## Control map

| Risk surface | Control | Failure policy |
|---|---|---|
| Resolved Python environment | `pip-audit` | Any known vulnerability reported by the selected advisory service fails the job. |
| Python source | Bandit | New findings with at least medium severity and medium confidence fail the job. |
| Python data flows | CodeQL `security-extended` | Results are uploaded to GitHub code scanning. |
| Built container image | Trivy | Fixed high or critical OS/library vulnerabilities fail the job. |
| Dependency freshness | Dependabot | Weekly update pull requests for `pip`, GitHub Actions, and Docker. |
| Workflow supply chain | Full action SHA pins | Tests reject mutable tags or branches in `uses:` lines. |

## Python dependency evidence and pull-request gate

The security workflow installs:

```text
.[dev,security]
```

Before resolving the project it upgrades the packaging toolchain to `setuptools>=83`, which is also the build-system floor declared in `pyproject.toml`.

It then executes:

```bash
python -m pip check
python -m pip_audit --local --format json
python -m pip_audit --local --format cyclonedx-json
```

The same job runs for every pull request. A newly added vulnerable package therefore makes the resolved head environment fail even though the repository does not currently provide a base-versus-head dependency diff.

The job uploads:

```text
pip-audit.json
python-sbom.cdx.json
```

The CycloneDX document is an inventory of the resolved CI environment. It is not a lockfile and does not guarantee that a later installation resolves identical transitive versions.

### Why GitHub Dependency Review is not used

The first implementation attempted to run GitHub's Dependency Review Action. GitHub rejected the job because Dependency Graph is not enabled for this repository. The final workflow does not hide that error with `continue-on-error`; it removes the unsupported action and retains the complete resolved-environment audit as the blocking pull-request dependency gate.

This has an explicit limitation: `pip-audit` evaluates the proposed environment but does not label a vulnerability as newly introduced relative to the base branch.

## Static analysis

Bandit runs against `src/` with:

```bash
python -m bandit -r src -ll -ii \
  -b security/bandit-baseline.json
```

`-ll` requires at least medium severity. `-ii` requires at least medium confidence. The baseline contains exactly two reviewed B608 findings:

1. `_select_run()` appends either an empty string or the constant `FOR UPDATE`, selected by a boolean; the `run_id` remains parameterized.
2. the two-cohort preflight selects table and identifier names exclusively from the fixed `DATASET_ID_COLUMNS` six-entity registry; identifier values remain parameterized.

The baseline is not a global B608 skip. It records those exact findings, and a policy test verifies the file names, test IDs, severity, and count. New findings or changed locations remain blocking. Bandit officially supports JSON baselines for reviewed non-issues.

CodeQL runs independently with the extended Python security query suite. Keeping it separate from Bandit matters because the two tools use different models and can detect different classes of weakness.

## Container scanning

The workflow builds the repository Dockerfile and scans the resulting image with Trivy:

```text
vulnerability types: OS packages and language libraries
severity: HIGH, CRITICAL
unfixed findings: reported but ignored by the failing gate
```

The initial scan detected fixed vulnerabilities in the packaging toolchain. The Dockerfile now upgrades:

```text
setuptools >=83
wheel >=0.46.2
jaraco.context >=6.1.0
```

Ignoring unfixed findings avoids blocking every build on a vulnerability for which no remediation exists, but the finding remains visible in the scanner output. This is a policy choice, not a statement that unfixed vulnerabilities are harmless.

## GitHub Actions pinning

Every external action reference uses a full 40-character commit SHA. A version comment remains next to the pin, for example:

```yaml
uses: actions/checkout@<full-sha> # v4.3.1
```

Dependabot can propose updates to these pins. Each update still requires normal pull-request review and CI.

## Scheduled execution

The security workflow runs on:

- pushes to `main`;
- pull requests;
- manual dispatch;
- a weekly scheduled scan.

Scheduled execution matters because an unchanged dependency can become vulnerable after a new advisory is published.

## Local commands

```bash
python -m pip install --upgrade pip "setuptools>=83"
python -m pip install -e ".[dev,security]"
python -m pip check
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii -b security/bandit-baseline.json
```

CodeQL and the container scan remain authoritative GitHub Actions results because they depend on GitHub services or the CI container environment.

## Interpretation limits

A green security workflow means that the configured scanners did not find a blocking issue under their current databases, rules, thresholds, baseline, and execution environment. It does not prove:

- absence of unknown or logic vulnerabilities;
- safety of every transitive native library;
- resistance to targeted supply-chain compromise;
- secure deployment configuration;
- penetration-test coverage;
- PHI readiness, regulatory compliance, or clinical safety.

The repository remains synthetic-only and must not be presented as a production clinical system.
