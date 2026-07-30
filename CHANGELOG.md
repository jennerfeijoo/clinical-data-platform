# Changelog

## 0.21.0

- added a governed release gate that keeps package metadata, package `__version__`, CHANGELOG, CITATION metadata, README, tests, CI, and semantic release tags synchronized;
- added deterministic wheel and source-distribution inspection, SHA-256 checksums, a machine-readable release manifest, and byte-for-byte double-build verification in GitHub Actions;
- added clean virtual-environment installation from the built wheel outside the repository and exercised contracts, cohort profiles, migrations, entrypoints, and the packaged hypertension cohort definition;
- packaged the default hypertension cohort SQL and the `py.typed` marker so installed wheels no longer rely on repository-relative runtime files;
- added a tag-driven GitHub Release workflow with immutable artifact names and full-SHA-pinned Actions, while deliberately leaving PyPI publication disabled pending separate Trusted Publishing review;
- added `CITATION.cff`, `CONTRIBUTING.md`, `SUPPORT.md`, a source-distribution manifest, documentation index, CLI reference, consolidated limitation register, release procedure, and Spanish release-engineering guide;
- added release-toolchain dependency auditing and CI artifacts for pull-request inspection;
- retained the synthetic-only, non-clinical, non-PHI boundary and kept stable `1.0.0` as a separately reviewed milestone.

## 0.20.0

- changed the application image to the fixed non-root runtime identity `10001:10001` with a non-login account;
- made the supported runtime profile use a read-only root filesystem, `cap-drop=ALL`, `no-new-privileges`, a constrained `noexec,nosuid` `/tmp` tmpfs, and a PID limit;
- made `/app`, `/opt/venv`, bundled sample data, and SQL immutable to the application user while retaining explicit raw, processed, and analytics output mount points;
- stripped setuid/setgid bits from standard executable paths and retained the package-manager-free multi-stage runtime introduced in `0.19.0`;
- replaced the complete repository data bind mount in Compose with named output volumes and the same hardened runtime controls used by CI;
- added behavioral container tests for effective UID/GID, non-login shell, read-only paths, PostgreSQL connectivity, contracts, profiles, migrations, and raw-capture ownership;
- added policy tests that prevent removal of the Dockerfile, Compose, or CI hardening controls;
- added technical documentation and a Spanish learning guide, while retaining the synthetic-only, non-clinical, non-PHI project boundary.

## 0.19.0

- added a dedicated security workflow for complete Python environment auditing, Bandit, CodeQL, and Trivy container scanning;
- added CycloneDX SBOM and JSON scan artifacts for reproducible security evidence;
- configured weekly Dependabot updates for Python, GitHub Actions, and Docker;
- pinned every external GitHub Action to a full commit SHA and added a policy test that rejects mutable references;
- added a reviewed Bandit baseline limited to two constant-only B608 findings, with an exact policy test preventing silent expansion;
- raised the build-system floor to `setuptools>=83` and converted the container to a multi-stage build whose runtime excludes `pip`, `setuptools`, `wheel`, global site-packages, and `ensurepip` bootstrap bundles;
- documented that GitHub Dependency Review is unavailable because Dependency Graph is not enabled, while every pull request remains gated by a complete resolved-environment audit;
- added a repository security-reporting policy and technical documentation in English and Spanish;
- retained the synthetic-only, non-clinical, non-PHI project boundary and documented that automated scans do not prove security.

## 0.18.0

- added PostgreSQL-backed compatibility jobs for CPython 3.12, 3.13, and 3.14;
- retained Python 3.11 as the minimum, reference-quality, Docker, and benchmark interpreter;
- changed package metadata to the explicitly tested range `>=3.11,<3.15`;
- added Python 3.11–3.14 package classifiers and runtime metadata assertions;
- configured the compatibility matrix with `fail-fast: false`, isolated PostgreSQL services, `pip check`, contracts, migrations, and the full coverage-gated suite;
- upgraded workflow Python setup to `actions/setup-python@v6`;
- added a policy-drift test linking package metadata, CI matrix, and benchmark configuration;
- documented the support policy and maintenance process in English and Spanish;
- retained the synthetic-only, non-clinical, non-PHI project boundary.

## 0.17.0

- raised statement coverage from 82% to more than 90% without excluding package modules;
- made the 90% minimum mandatory through shared pytest-cov and coverage configuration;
- added behavioral tests for the primary, cohort, benchmark, demo, and logging entrypoints;
- exercised real contracts, raw capture, validation, Synthea adaptation, cohort comparison, and quality reporting with synthetic fixtures;
- added governed failure-path tests for Synthea profiles, source artifacts, external commands, Git checkout state, and Java versions;
- retained PostgreSQL and Java boundaries as controlled doubles where unit tests must remain deterministic;
- documented the coverage policy, interpretation limits, and maintenance workflow;
- retained the synthetic-only, non-clinical, non-PHI project boundary.

## 0.16.0

- added reproducible source-to-adapted attrition reports for both Synthea cohorts;
- reconciled every entity as source rows equals adapted plus explicitly omitted rows;
- added omission-reason, source-missingness, adapted-missingness, and row-completeness CSV artifacts;
- classified adapted missingness as required, optional, or structural;
- added a stable paired quality fingerprint and descriptive cohort comparison;
- added `clinical-data-cohort quality-report`, PowerShell and POSIX runners;
- added CI, tests, technical documentation, and a Spanish learning guide;
- retained the synthetic-only, non-clinical, non-PHI project boundary.

## 0.15.0

- added a second packaged Synthea profile with independent patient and clinician seeds;
- added deterministic comparison evidence for two matched-design cohorts;
- required zero overlap across all six clinical identifier domains;
- added database preflight and separate processing lineage for pair loading;
- added `clinical-data-cohort`, PowerShell and POSIX runners;
- added unit, CLI, PostgreSQL integration, container, and documentation coverage;
- retained the synthetic-only, non-clinical, non-PHI project boundary.

## 0.14.0

- added the documented, balanced, correctness-gated PostgreSQL loading benchmark.
