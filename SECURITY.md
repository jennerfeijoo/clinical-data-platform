# Security policy

## Supported version

Security fixes are applied to the current `main` branch. The repository is under active development toward `1.0.0`; older pre-release snapshots are not maintained as separate supported release lines.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, tokens, private data, or information that would make exploitation easier.

Use GitHub's private vulnerability reporting feature for this repository when available. Include:

- the affected commit or version;
- the component and execution path;
- reproducible steps using synthetic data only;
- expected and observed behavior;
- impact and prerequisites;
- a minimal proposed mitigation when known.

Do not include identifiable patient information. The project is synthetic-only and is not approved for PHI or production clinical use.

## Automated controls

The repository runs:

- `pip-audit` for known Python dependency vulnerabilities;
- Bandit for Python static analysis;
- CodeQL with the extended Python security query suite;
- GitHub dependency review for pull-request dependency changes;
- Trivy for high and critical vulnerabilities in the built container image;
- Dependabot for Python, GitHub Actions, and Docker update proposals.

GitHub Actions are pinned to full commit SHAs and updated through reviewed pull requests.

## Scope limits

Passing automated scans does not prove absence of vulnerabilities. The controls do not establish regulatory compliance, production readiness, secure PHI handling, penetration-test coverage, or protection against unknown vulnerabilities and malicious dependencies.
