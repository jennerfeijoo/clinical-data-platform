# Security and dependency scanning

Version `0.19.0` adds executable security controls to the synthetic clinical data platform. These checks complement tests, type checking, database constraints, and audit lineage; they do not replace them.

## Control map

| Risk surface | Control | Failure policy |
|---|---|---|
| Python dependencies | `pip-audit` | Any known vulnerability reported by the selected advisory service fails the job. |
| Python source | Bandit | Findings with at least medium severity and medium confidence fail the job. |
| Python data flows | CodeQL `security-extended` | Results are uploaded to GitHub code scanning. |
| Pull-request dependency changes | Dependency Review Action | Newly introduced high or critical vulnerabilities fail the pull request. |
| Built container image | Trivy | Fixed high or critical OS/library vulnerabilities fail the job. |
| Dependency freshness | Dependabot | Weekly update pull requests for `pip`, GitHub Actions, and Docker. |
| Workflow supply chain | Full action SHA pins | Tests reject mutable tags or branches in `uses:` lines. |

## Python dependency evidence

The security workflow installs:

```text
.[dev,security]
```

and then executes:

```bash
python -m pip check
python -m pip_audit --local --format json
python -m pip_audit --local --format cyclonedx-json
```

The job uploads:

```text
pip-audit.json
python-sbom.cdx.json
```

The CycloneDX document is an inventory of the resolved CI environment. It is not a lockfile and does not guarantee that a later installation resolves identical transitive versions.

## Static analysis

Bandit runs against `src/` with:

```bash
python -m bandit -r src -ll -ii
```

`-ll` requires at least medium severity. `-ii` requires at least medium confidence. This reduces low-confidence noise while preserving a failing gate for more credible findings.

CodeQL runs independently with the extended Python security query suite. Keeping it separate from Bandit matters because the two tools use different models and can detect different classes of weakness.

## Pull-request dependency review

The dependency review job runs only for pull requests and rejects newly introduced vulnerabilities at severity `high` or `critical`. It evaluates dependency changes rather than rescanning only the current environment.

## Container scanning

The workflow builds the same repository Dockerfile and scans the resulting image with Trivy:

```text
vulnerability types: OS packages and language libraries
severity: HIGH, CRITICAL
unfixed findings: reported but ignored by the failing gate
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
python -m pip install -e ".[dev,security]"
python -m pip check
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii
```

CodeQL, dependency review, and the container scan remain authoritative GitHub Actions results because they depend on GitHub services or the CI container environment.

## Interpretation limits

A green security workflow means that the configured scanners did not find a blocking issue under their current databases, rules, thresholds, and execution environment. It does not prove:

- absence of unknown or logic vulnerabilities;
- safety of every transitive native library;
- resistance to targeted supply-chain compromise;
- secure deployment configuration;
- penetration-test coverage;
- PHI readiness, regulatory compliance, or clinical safety.

The repository remains synthetic-only and must not be presented as a production clinical system.
