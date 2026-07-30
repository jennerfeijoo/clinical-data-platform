# Documentation index

This index separates architecture, operation, evidence, policy, and learning material for the Clinical Data Platform.

The repository is synthetic-only. Nothing in these documents authorizes identifiable patient data, clinical decisions, production healthcare operation, epidemiological inference, or regulatory use.

## Start here

- [README](../README.md): project purpose, architecture, installation, and primary commands.
- [CLI reference](cli-reference.md): command groups, required inputs, outputs, and destructive boundaries.
- [Architecture](architecture.md): components, data flow, and trust boundaries.
- [Architecture status at 1.0.0](architecture-status-1.0.md): implemented capabilities and remaining technical gaps.
- [Database](database.md): schemas, migrations, lineage, and inspection queries.
- [Repository file reference](repository-file-reference.md): interpretation rules and companion per-file PDF.
- [Stable release readiness](stable-release-readiness.md): `1.0.0` compatibility surface, gates, and non-goals.
- [Current limitations](limitations.md): unsupported claims and known engineering boundaries.

## Data contracts, coverage, and ingestion

- [Executable contracts](contracts.md)
- [Immutable raw landing](raw-landing.md)
- [Clinical data coverage](clinical-data-coverage.md)
- [Clinical history policy](clinical-history-policy.md)
- [Clinical entities](clinical-entities.md)
- [Terminology integration](terminology.md)

## Execution and observability

- [Execution audit](execution-audit.md)
- [Structured logging](structured-logging.md)
- [Bulk PostgreSQL loading](bulk-loading.md)
- [Loading benchmark](loading-benchmark.md)

## Synthetic cohorts and quality evidence

- [Synthea profile and adapter](synthea.md)
- [Independent Synthea cohorts](synthea-cohorts.md)
- [Attrition and missingness](attrition-missingness.md)
- [Analysis guide](analysis-guide.md)

## Engineering policy

- [Testing and 90% coverage](testing-coverage.md)
- [Python compatibility](python-compatibility.md)
- [Security scanning](security-scanning.md)
- [Container hardening](container-hardening.md)
- [Stable release readiness](stable-release-readiness.md)
- [Release process](release-process.md)
- [Contribution policy](../CONTRIBUTING.md)
- [Support policy](../SUPPORT.md)
- [Security reporting](../SECURITY.md)
- [Changelog](../CHANGELOG.md)

## Spanish learning guides

The files in [`docs/learning`](learning/) explain selected engineering decisions in Spanish. They are educational companions; the technical policy documents and executable tests remain the normative implementation evidence.

- [Auditoría de ejecución](learning/execution-audit-es.md)
- [Cobertura de pruebas](learning/cobertura-pruebas-90-es.md)
- [Compatibilidad de Python](learning/compatibilidad-python-ci-es.md)
- [Seguridad de dependencias](learning/security-dependencias-es.md)
- [Contenedor no root](learning/contenedor-no-root-es.md)
- [Ingeniería de releases](learning/release-engineering-es.md)

## Evidence hierarchy

When prose and executable evidence disagree, investigate in this order:

1. immutable database migrations and versioned contracts;
2. source code and policy tests;
3. CI, security, benchmark, and release-workflow results tied to an exact commit;
4. generated JSON, CSV, SBOM, checksum, and benchmark artifacts;
5. documentation and learning guides.

Documentation must be corrected when it no longer matches the executable system. A passing workflow is evidence for the configured checks, not proof of clinical validity, complete security, or production readiness.
