# Security policy

## Supported version

Security fixes are applied to the current `main` branch. Version `1.0.0` is the current stable release; no separate long-term-support branch is maintained, and pre-1.0 snapshots are unsupported.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, tokens, private data, or information that would make exploitation easier.

Use GitHub's private vulnerability reporting feature for this repository when available. Include:

- the affected commit, tag, version, or artifact SHA-256;
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
- Dependabot for Python, GitHub Actions, and Docker update proposals;
- hardened container smoke tests under a read-only root filesystem, dropped capabilities, `no-new-privileges`, and a constrained `/tmp` tmpfs;
- release-toolchain auditing, wheel and source-distribution content inspection, clean-wheel installation, reproducible double builds, and SHA-256 release evidence.

The dedicated GitHub Dependency Review Action is not used because Dependency Graph is not enabled. Pull requests are instead blocked when the complete resolved Python environment contains a known vulnerability. This audits the proposed head environment but does not provide a base-versus-head dependency diff.

GitHub Actions are pinned to full commit SHAs and updated through reviewed pull requests.

## Release artifact policy

Tag releases are built from the exact tagged commit by `.github/workflows/release.yml`. The workflow verifies version/tag consistency, builds the wheel and source distribution twice with a fixed source epoch, compares the artifacts byte for byte, inspects their contents, installs the wheel outside the source repository, and publishes:

```text
wheel
source distribution
SHA256SUMS
release-manifest.json
```

Published release tags and assets must not be moved or silently replaced. A correction requires a new version so consumers can distinguish the bytes and provenance.

The current workflow creates GitHub Releases only. It does not publish to PyPI and does not request an OpenID Connect publishing token. PyPI Trusted Publishing requires separate configuration and review.

Artifact checks reduce packaging and provenance errors. They do not provide cryptographic signing, SLSA certification, malicious-maintainer resistance, complete dependency provenance, or protection if GitHub, the runner, or repository credentials are compromised.

## Container runtime policy

The application image declares the fixed runtime identity `10001:10001`. The associated `clinical` account uses `/usr/sbin/nologin`. The packaged application, virtual environment, sample files, and SQL are not writable by that identity.

The supported hardened execution profile uses:

```text
read-only root filesystem
all Linux capabilities dropped
no-new-privileges enabled
/tmp supplied as noexec,nosuid tmpfs
PID limit of 256
explicit writable volumes for raw, processed, and analytics outputs
```

CI verifies the configured image user, effective UID/GID, non-login shell, read-only application paths, PostgreSQL connectivity, and raw receipt ownership. Compose applies the same restrictions to the demo application service.

These controls reduce the impact of a compromised application process. They do not create a complete sandbox and do not replace host security, network policy, secret management, image signing, runtime monitoring, or orchestrator-level policy.

## Reviewed Bandit baseline

The baseline contains two B608 findings where SQL fragments come exclusively from internal constants:

- an optional `FOR UPDATE` clause selected from a boolean;
- clinical table and identifier names selected from the fixed six-entity registry.

The baseline suppresses only those recorded findings. New findings, changed locations, or additional B608 results remain blocking.

## Scope limits

Passing automated scans, release checks, and hardened container tests does not prove absence of vulnerabilities. The controls do not establish regulatory compliance, production readiness, secure PHI handling, penetration-test coverage, artifact authenticity under every threat model, or protection against unknown vulnerabilities and malicious dependencies.
