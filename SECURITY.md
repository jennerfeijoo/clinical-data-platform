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

- `pip-audit` on every pull request, push, weekly schedule, and manual security run;
- Bandit for Python static analysis against a narrow reviewed baseline;
- CodeQL with the extended Python security query suite;
- Trivy for high and critical vulnerabilities in the built container image;
- Dependabot for Python, GitHub Actions, and Docker update proposals.

The dedicated GitHub Dependency Review Action is not used because Dependency Graph is not enabled for this repository. Pull requests are instead blocked when the complete resolved Python environment contains a known vulnerability. This audits the proposed head environment but does not provide a base-versus-head dependency diff.

GitHub Actions are pinned to full commit SHAs and updated through reviewed pull requests.

## Reviewed Bandit baseline

The baseline contains two B608 findings where SQL fragments come exclusively from internal constants:

- an optional `FOR UPDATE` clause selected from a boolean;
- clinical table and identifier names selected from the fixed six-entity registry.

The baseline suppresses only those recorded findings. New findings, changed locations, or additional B608 results remain blocking.

## Scope limits

Passing automated scans does not prove absence of vulnerabilities. The controls do not establish regulatory compliance, production readiness, secure PHI handling, penetration-test coverage, or protection against unknown vulnerabilities and malicious dependencies.
