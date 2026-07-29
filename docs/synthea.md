# Reproducible Synthea generation and adaptation

## Scope

This workflow generates synthetic populations with pinned Synthea profiles, records the exact generation inputs, adapts six upstream CSV files into the platform contracts, and verifies every source and output artifact by SHA-256.

Synthea produces synthetic records. These workflows must not be interpreted as sources of real patient data, epidemiological ground truth, clinically representative prevalence, or evidence suitable for patient care.

## Packaged profiles

The package now includes two profiles:

```text
src/clinical_data_platform/synthea_profiles/
├── reproducible_small.toml
└── reproducible_small_cohort_b.toml
```

| Control | `synthea-us-small-v1` | `synthea-us-small-cohort-b-v1` |
|---|---|---|
| Synthea release | `v4.0.0` | `v4.0.0` |
| Population | 100 | 100 |
| Random seed | 20260729 | 20260829 |
| Clinician seed | 20260730 | 20260830 |
| Reference date | 2026-07-29 | 2026-07-29 |
| Geography | Massachusetts | Massachusetts |
| Generator threads | 1 | 1 |
| Years of history | 0 | 0 |
| Export | six CSV files | six CSV files |

The original `clinical-data` Synthea commands continue to default to `synthea-us-small-v1`. The `clinical-data-cohort` entrypoint selects either packaged profile by stable name.

Single-thread generation is deliberate. Parallel generation can make output ordering and some run-scoped identifiers harder to reproduce exactly.

## Why a tag is not enough

Each profile pins `v4.0.0`, but the generation manifest also records the resolved upstream Git commit. This allows a previous result to retain the exact source identity even if an upstream ref were later moved or recreated.

The checkout must:

- resolve exactly to the configured tag;
- contain no uncommitted changes;
- use Java 17 or newer;
- be invoked without a shell-built command string.

## Exact upstream inputs

The command pins:

```text
-s random seed
-cs clinician seed
-p population size
-r reference date
--generate.thread_pool_size=1
--exporter.years_of_history=0
--exporter.csv.export=true
--exporter.csv.append_mode=false
--exporter.csv.folder_per_run=false
--exporter.csv.included_files=...
```

FHIR, hospital FHIR, practitioner FHIR, and metadata exporters are disabled. Only the six required CSV files are requested.

## Source files

```text
patients.csv
encounters.csv
conditions.csv
observations.csv
medications.csv
procedures.csv
```

The adapter validates exact Synthea 4.0.0 headers before reading rows. A changed or reordered upstream header is treated as schema drift and fails before adaptation.

## Generation manifest

`synthea-generation-manifest.json` records:

```text
profile path and SHA-256
upstream repository, tag, version, and commit
Java version
normalized command
source file names
exact headers
row counts
byte sizes
SHA-256 hashes
dataset fingerprint
```

The normalized command replaces machine-specific checkout and output paths with placeholders. The actual source bytes remain identified by their individual hashes.

## Adapter boundary

The adapter creates:

```text
normalized/
├── patients.csv
├── encounters.csv
├── diagnoses.csv
├── observations.csv
├── medications.csv
├── procedures.csv
├── terminology.csv
└── synthea-adaptation-manifest.json
```

The output files match the existing executable contracts. There is no Synthea-specific validation or persistence path.

### Patients

Synthea `Id`, `BIRTHDATE`, `DEATHDATE`, and `GENDER` become the internal patient fields. Gender values outside `F` and `M` become `UNKNOWN` because the source export does not provide a distinct sex-at-birth field for this adapter.

### Encounters

Encounter classes map as follows:

```text
inpatient → INPATIENT
emergency → EMERGENCY
all other classes → OUTPATIENT
```

The original encounter UUID is retained.

### Diagnoses

Synthea `conditions.csv` becomes `diagnoses.csv`. Because the source file has no stable condition-event identifier, the adapter generates a deterministic UUIDv5 from:

```text
dataset
source file
source row number
canonical source row content
```

Supported source systems are normalized to `SNOMED` or `ICD10`.

### Observations

The current platform contract intentionally accepts only:

| Synthea/LOINC code | Internal code | Internal unit |
|---|---|---|
| 8480-6 | `SYSTOLIC_BP` | `mmHg` |
| 8462-4 | `DIASTOLIC_BP` | `mmHg` |
| 8867-4 | `HEART_RATE` | `bpm` |

Other observations are omitted and counted in the adaptation manifest. They are not silently converted into the narrow observation contract.

### Medications

The Synthea medication CSV does not include a code-system column. The adapter treats `CODE` as RxNorm, matching Synthea's native CSV convention.

Status is derived as:

```text
blank STOP → ACTIVE
STOP present → COMPLETED
```

Dose and route remain empty because the CSV source does not contain a reliable structured dose/route representation for this adapter.

### Procedures

Supported source systems are normalized to `SNOMED`, `CPT`, or `ICD10PCS`. Adapted procedures are marked `COMPLETED` because each CSV row represents an exported performed procedure event.

## Parent integrity

Every dependent event must reference:

- an included patient;
- an included encounter;
- the same patient as that encounter.

Rows that violate this condition are omitted with an explicit reason count.

## Terminology import

The adapter writes source concepts used by diagnoses, medications, and procedures to `terminology.csv`.

During loading:

- existing concepts are reused;
- missing concepts are inserted into the existing canonical system;
- inserted concepts are marked `unverified`;
- a code cannot be imported into a conflicting clinical domain.

This supports generated populations without claiming that every source code was independently verified against an official terminology release.

## Adaptation manifest

`synthea-adaptation-manifest.json` records:

```text
adapter version
profile SHA-256
source file hashes and counts
output file hashes and counts
omitted-row reasons
terminology concept count
adaptation fingerprint
```

The adaptation fingerprint covers source fingerprints, output fingerprints, adapter version, profile hash, and omitted-row counts.

## Original single-profile commands

Inspect the default profile:

```powershell
clinical-data synthea-profile
```

Generate and adapt the original profile:

```powershell
.\scripts\generate_synthea.ps1
```

Manual sequence:

```powershell
clinical-data synthea-generate `
  --workspace data/synthea/synthea-us-small-v1

clinical-data synthea-adapt `
  data/synthea/synthea-us-small-v1/generated/csv `
  --output-dir data/synthea/synthea-us-small-v1/normalized `
  --generation-manifest `
    data/synthea/synthea-us-small-v1/synthea-generation-manifest.json

clinical-data synthea-verify `
  data/synthea/synthea-us-small-v1/normalized
```

## Named profile commands

List both packaged profiles:

```powershell
clinical-data-cohort list-profiles
```

Inspect cohort B:

```powershell
clinical-data-cohort profile synthea-us-small-cohort-b-v1
```

Generate and adapt both profiles:

```powershell
.\scripts\generate_synthea_cohorts.ps1
```

The two-cohort comparison and pair-loading protocol is documented in [`synthea-cohorts.md`](synthea-cohorts.md).

## What CI verifies

Normal CI does not clone and execute the full Java generator. It verifies:

- both packaged profiles;
- the controlled equality of study-design parameters;
- distinct patient and clinician seeds;
- exact upstream CSV headers;
- deterministic adaptation;
- manifest verification and tamper detection;
- contract validity of every adapted output;
- terminology import;
- zero identifier overlap between two fixtures;
- end-to-end pair loading through PostgreSQL.

The checked-in fixtures are schema and behavior fixtures, not the final 100-patient generated datasets.

## Reproducibility claim

The implementation can verify exact repeatability when two executions produce the same source-file hashes and dataset fingerprint. Fixed inputs substantially reduce variability, but the repository does not claim that every future operating system, JVM, or upstream dependency environment will always produce byte-identical output.

The manifests expose differences rather than hiding them.

## Current limits

- the adapter supports six Synthea CSV files;
- observations are restricted to three vital-sign concepts;
- terminology entries absent from the local subset are imported as unverified;
- no upstream Java generation occurs in standard CI;
- generated workspaces are ignored by Git;
- pair loading uses twelve existing per-dataset execution lifecycles rather than one global transaction;
- no epidemiological or clinical-validity claim is made.
