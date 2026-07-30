# Stable release readiness: 1.0.0

## Decision

Version `1.0.0` is the first stable software release of Clinical Data Platform for its documented purpose: reproducible and auditable engineering workflows over synthetic clinical data.

The stable designation applies to the software interface and artifact process. It does not mean the platform is validated for healthcare production, identifiable patient data, clinical decision support, epidemiological inference, or regulated use.

## Stable compatibility surface

Within the `1.x` series, backward compatibility is expected for:

- the three installed console entrypoints: `clinical-data`, `clinical-data-cohort`, and `clinical-data-benchmark`;
- the six dataset identifiers and their versioned executable contract discovery mechanism;
- the V001–V008 PostgreSQL migration chain and the documented migration CLI;
- packaged runtime resources: contracts, migrations, Synthea profiles, `py.typed`, and the default hypertension cohort SQL;
- release artifact names, wheel metadata, checksums, and `release-manifest.json` schema;
- durable run-state names and the documented distinction between operational logs and audit evidence.

A backward-incompatible change to these surfaces requires a new major version or an explicitly documented migration path.

## Readiness evidence

The stable release is gated by all of the following:

1. Package metadata, `__version__`, CHANGELOG, CITATION, README, tests, CI, and semantic tag identity agree on `1.0.0`.
2. CPython 3.11, 3.12, 3.13, and 3.14 pass the PostgreSQL-backed test suite.
3. Statement coverage remains at or above 90%.
4. Ruff and strict mypy pass.
5. The wheel and source distribution are built twice with `SOURCE_DATE_EPOCH` and are byte-identical.
6. `twine check` and governed distribution-content inspection pass.
7. The wheel installs in a clean virtual environment outside the repository and executes packaged contracts, profiles, migrations, cohort SQL, and entrypoints.
8. `pip-audit`, CycloneDX SBOM generation, Bandit, CodeQL, and Trivy pass under their documented policies.
9. The hardened container runs as UID/GID `10001:10001` with a read-only root filesystem, no Linux capabilities, and no privilege escalation.
10. The governed PostgreSQL loading benchmark passes its correctness checks and publishes evidence.

## Database decision

No `V009` migration is introduced for `1.0.0`. The stable release uses the already validated V001–V008 schema and changes only versioning, documentation, tests, and release metadata.

## Distribution decision

The governed release publishes these GitHub Release assets:

- `clinical_data_platform-1.0.0-py3-none-any.whl`;
- `clinical_data_platform-1.0.0.tar.gz`;
- `SHA256SUMS`;
- `release-manifest.json`.

PyPI publication remains disabled. Enabling it requires a separate review of project ownership, package-name availability, Trusted Publishing, OIDC permissions, recovery procedures, and release revocation policy.

## Explicit non-goals

Version `1.0.0` does not establish:

- PHI readiness or compliance with GDPR, HIPAA, or another legal framework;
- clinical, diagnostic, prognostic, or therapeutic validity;
- regulatory suitability or software-as-a-medical-device status;
- production availability, backup, disaster recovery, high availability, or multi-tenant isolation;
- complete terminology releases or terminology-server behavior;
- epidemiological validity of Synthea populations;
- MCAR, MAR, or MNAR classification of missingness;
- production-scale throughput or concurrent-writer performance;
- absence of vulnerabilities not detected by the configured tools.

## Post-1.0 change policy

Patch releases fix defects without intentionally changing documented behavior. Minor releases add backward-compatible capabilities. Major releases may change compatibility surfaces and must provide explicit migration and deprecation documentation.
