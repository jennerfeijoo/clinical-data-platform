# Support policy

Clinical Data Platform is an educational and engineering portfolio project maintained through the current `main` branch.

## Supported surface

The actively tested surface is:

- CPython 3.11, 3.12, 3.13, and 3.14;
- PostgreSQL 16;
- the current packaged contracts, migrations V001–V008, Synthea profiles, cohort definition, and command-line entrypoints;
- the hardened Linux container profile documented in `docs/container-hardening.md`;
- synthetic and appropriately licensed public data only.

Pre-release versions are not maintained as parallel support branches. Security fixes are applied to the current development line.

## Requesting help

Use a GitHub issue for reproducible questions about installation, synthetic examples, tests, documentation, or expected command behavior. Include:

- package version and commit SHA;
- operating system and Python version;
- PostgreSQL and Docker versions when relevant;
- the exact synthetic command and sanitized error output;
- a minimal reproduction that contains no credentials or identifiable data.

## Out of scope

Support is not provided for:

- identifiable patient data or PHI workflows;
- clinical diagnosis, treatment, or decision support;
- regulatory, hospital, or production deployment approval;
- private infrastructure, credentials, secrets, or proprietary datasets;
- epidemiological inference from the bundled synthetic cohorts;
- guarantees of availability, response time, or long-term maintenance.

Security vulnerabilities must follow [`SECURITY.md`](SECURITY.md), not a public support issue.
