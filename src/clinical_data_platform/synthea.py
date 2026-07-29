"""Reproducible Synthea generation, adaptation, verification, and loading."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid5

import psycopg

from clinical_data_platform.contract import validate_records_against_contract
from clinical_data_platform.models import ClinicalRecord
from clinical_data_platform.registry import dataset_names, get_dataset_definition
from clinical_data_platform.structured_logging import (
    bind_log_context,
    emit_log,
    get_logger,
    log_operation,
)

PROFILE_PACKAGE: Final = "clinical_data_platform.synthea_profiles"
DEFAULT_PROFILE_RESOURCE: Final = "reproducible_small.toml"
PROFILE_SCHEMA_VERSION: Final = "1.0.0"
GENERATION_MANIFEST_VERSION: Final = "1.0.0"
ADAPTATION_MANIFEST_VERSION: Final = "1.0.0"
ADAPTER_VERSION: Final = "1.0.0"
EVENT_NAMESPACE: Final = UUID("44554cc5-322b-53c4-90fd-d5036fd431d1")
LOGGER = get_logger("synthea")

REQUIRED_SOURCE_FILES: Final = (
    "patients.csv",
    "encounters.csv",
    "conditions.csv",
    "observations.csv",
    "medications.csv",
    "procedures.csv",
)

SOURCE_HEADERS: Final[dict[str, tuple[str, ...]]] = {
    "patients.csv": (
        "Id",
        "BIRTHDATE",
        "DEATHDATE",
        "SSN",
        "DRIVERS",
        "PASSPORT",
        "PREFIX",
        "FIRST",
        "MIDDLE",
        "LAST",
        "SUFFIX",
        "MAIDEN",
        "MARITAL",
        "RACE",
        "ETHNICITY",
        "GENDER",
        "BIRTHPLACE",
        "ADDRESS",
        "CITY",
        "STATE",
        "COUNTY",
        "FIPS",
        "ZIP",
        "LAT",
        "LON",
        "HEALTHCARE_EXPENSES",
        "HEALTHCARE_COVERAGE",
        "INCOME",
    ),
    "encounters.csv": (
        "Id",
        "START",
        "STOP",
        "PATIENT",
        "ORGANIZATION",
        "PROVIDER",
        "PAYER",
        "ENCOUNTERCLASS",
        "CODE",
        "DESCRIPTION",
        "BASE_ENCOUNTER_COST",
        "TOTAL_CLAIM_COST",
        "PAYER_COVERAGE",
        "REASONCODE",
        "REASONDESCRIPTION",
    ),
    "conditions.csv": (
        "START",
        "STOP",
        "PATIENT",
        "ENCOUNTER",
        "SYSTEM",
        "CODE",
        "DESCRIPTION",
    ),
    "observations.csv": (
        "DATE",
        "PATIENT",
        "ENCOUNTER",
        "CATEGORY",
        "CODE",
        "DESCRIPTION",
        "VALUE",
        "UNITS",
        "TYPE",
    ),
    "medications.csv": (
        "START",
        "STOP",
        "PATIENT",
        "PAYER",
        "ENCOUNTER",
        "CODE",
        "DESCRIPTION",
        "BASE_COST",
        "PAYER_COVERAGE",
        "DISPENSES",
        "TOTALCOST",
        "REASONCODE",
        "REASONDESCRIPTION",
    ),
    "procedures.csv": (
        "START",
        "STOP",
        "PATIENT",
        "ENCOUNTER",
        "SYSTEM",
        "CODE",
        "DESCRIPTION",
        "BASE_COST",
        "REASONCODE",
        "REASONDESCRIPTION",
    ),
}

OBSERVATION_CODES: Final[dict[str, tuple[str, str]]] = {
    "8480-6": ("SYSTOLIC_BP", "mmHg"),
    "8462-4": ("DIASTOLIC_BP", "mmHg"),
    "8867-4": ("HEART_RATE", "bpm"),
}

TERMINOLOGY_COLUMNS: Final = (
    "code_system",
    "code",
    "display",
    "domain",
    "verification_status",
    "source_reference",
)

CANONICAL_TERMINOLOGY_SYSTEMS: Final = {
    "ICD10": "ICD10CM",
    "SNOMED": "SNOMEDCT",
    "RXNORM": "RXNORM",
    "ATC": "ATC",
    "CPT": "CPT",
    "ICD10PCS": "ICD10PCS",
}


class SyntheaError(RuntimeError):
    """Base class for Synthea reproducibility failures."""


class SyntheaProfileError(SyntheaError):
    """Raised when a reproducibility profile is missing or inconsistent."""


class SyntheaGenerationError(SyntheaError):
    """Raised when the pinned upstream generator cannot run safely."""


class SyntheaManifestError(SyntheaError):
    """Raised when generated or adapted files do not match their manifest."""


class SyntheaAdapterError(SyntheaError):
    """Raised when Synthea CSV files cannot become contract-ready datasets."""


@dataclass(frozen=True, slots=True)
class SyntheaProfile:
    """All inputs that define one reproducible upstream generation."""

    name: str
    schema_version: str
    source_system: str
    upstream_repository: str
    upstream_ref: str
    upstream_version: str
    upstream_license: str
    minimum_java_version: int
    population_size: int
    random_seed: int
    clinician_seed: int
    reference_date: date
    state: str
    city: str | None
    thread_pool_size: int
    years_of_history: int
    included_files: tuple[str, ...]
    resource_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SyntheaCheckout:
    """Verified local checkout of the pinned Synthea ref."""

    path: Path
    commit_sha: str
    exact_ref: str


@dataclass(frozen=True, slots=True)
class SyntheaFileFingerprint:
    """Hash, size, header, and row count for one CSV artifact."""

    name: str
    sha256: str
    size_bytes: int
    row_count: int
    header: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SyntheaGenerationSummary:
    """Result of one pinned upstream Synthea generation."""

    profile_name: str
    profile_sha256: str
    upstream_commit: str
    csv_directory: Path
    manifest_path: Path
    dataset_fingerprint: str
    files: tuple[SyntheaFileFingerprint, ...]


@dataclass(frozen=True, slots=True)
class SyntheaAdaptationSummary:
    """Result of adapting Synthea CSV files into the six internal contracts."""

    profile_name: str
    profile_sha256: str
    output_directory: Path
    manifest_path: Path
    adaptation_fingerprint: str
    dataset_rows: dict[str, int]
    omitted_rows: dict[str, int]
    terminology_concepts: int


@dataclass(frozen=True, slots=True)
class SyntheaTerminologyImportSummary:
    """Result of importing unverified Synthea source concepts."""

    concepts_received: int
    concepts_inserted: int
    concepts_existing: int


@dataclass(frozen=True, slots=True)
class SyntheaLoadSummary:
    """Result of validating and persisting one adapted Synthea population."""

    terminology: SyntheaTerminologyImportSummary
    run_ids: dict[str, UUID]
    records_persisted: dict[str, int]


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(document: Mapping[str, object]) -> str:
    content = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return _sha256_bytes(content)


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(document, file, indent=2, sort_keys=True, ensure_ascii=False)
        file.write("\n")


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"JSON manifest not found: {path}")
    with path.open(encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise SyntheaManifestError(f"Manifest must contain a JSON object: {path}")
    return {str(key): value for key, value in raw.items()}


def _require_table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = document.get(name)
    if not isinstance(value, dict):
        raise SyntheaProfileError(f"Profile table [{name}] is required.")
    return {str(key): item for key, item in value.items()}


def _require_string(table: Mapping[str, object], key: str, *, allow_empty: bool = False) -> str:
    value = table.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SyntheaProfileError(f"Profile field {key!r} must be a string.")
    return value.strip()


def _require_integer(table: Mapping[str, object], key: str) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SyntheaProfileError(f"Profile field {key!r} must be an integer.")
    return value


def _require_string_list(table: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list) or not value:
        raise SyntheaProfileError(f"Profile field {key!r} must be a non-empty list.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SyntheaProfileError(f"Profile field {key!r} contains an invalid item.")
        result.append(item.strip())
    return tuple(result)


def load_synthea_profile(path: Path | None = None) -> SyntheaProfile:
    """Load and validate the packaged profile or an explicitly supplied TOML file."""
    if path is None:
        resource = files(PROFILE_PACKAGE).joinpath(DEFAULT_PROFILE_RESOURCE)
        content = resource.read_bytes()
        resource_path = f"{PROFILE_PACKAGE}/{DEFAULT_PROFILE_RESOURCE}"
    else:
        content = path.read_bytes()
        resource_path = str(path)

    try:
        document = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SyntheaProfileError("Synthea profile is not valid UTF-8 TOML.") from exc

    profile_table = _require_table(document, "profile")
    upstream_table = _require_table(document, "upstream")
    generation_table = _require_table(document, "generation")
    export_table = _require_table(document, "export")

    schema_version = _require_string(profile_table, "schema_version")
    if schema_version != PROFILE_SCHEMA_VERSION:
        raise SyntheaProfileError(
            f"Unsupported Synthea profile schema {schema_version!r}; "
            f"expected {PROFILE_SCHEMA_VERSION!r}."
        )

    reference_text = _require_string(generation_table, "reference_date")
    try:
        reference_date = date.fromisoformat(reference_text)
    except ValueError as exc:
        raise SyntheaProfileError("reference_date must use YYYY-MM-DD.") from exc

    city_text = _require_string(generation_table, "city", allow_empty=True)
    included_files = _require_string_list(export_table, "included_files")
    if included_files != REQUIRED_SOURCE_FILES:
        raise SyntheaProfileError(
            "included_files must list the six supported Synthea CSV files in canonical order."
        )

    profile = SyntheaProfile(
        name=_require_string(profile_table, "name"),
        schema_version=schema_version,
        source_system=_require_string(profile_table, "source_system"),
        upstream_repository=_require_string(upstream_table, "repository"),
        upstream_ref=_require_string(upstream_table, "ref"),
        upstream_version=_require_string(upstream_table, "version"),
        upstream_license=_require_string(upstream_table, "license"),
        minimum_java_version=_require_integer(upstream_table, "minimum_java_version"),
        population_size=_require_integer(generation_table, "population_size"),
        random_seed=_require_integer(generation_table, "random_seed"),
        clinician_seed=_require_integer(generation_table, "clinician_seed"),
        reference_date=reference_date,
        state=_require_string(generation_table, "state"),
        city=city_text or None,
        thread_pool_size=_require_integer(generation_table, "thread_pool_size"),
        years_of_history=_require_integer(generation_table, "years_of_history"),
        included_files=included_files,
        resource_path=resource_path,
        sha256=_sha256_bytes(content),
    )
    if profile.population_size <= 0:
        raise SyntheaProfileError("population_size must be positive.")
    if profile.random_seed < 0 or profile.clinician_seed < 0:
        raise SyntheaProfileError("Synthea seeds must be non-negative.")
    if profile.minimum_java_version < 17:
        raise SyntheaProfileError("minimum_java_version cannot be below 17 for Synthea 4.")
    if profile.thread_pool_size != 1:
        raise SyntheaProfileError(
            "thread_pool_size must be 1 so CSV ordering and generated identifiers are stable."
        )
    if profile.years_of_history != 0:
        raise SyntheaProfileError(
            "years_of_history must be 0 so the profile retains complete simulated history."
        )
    return profile


def synthea_profile_document(profile: SyntheaProfile) -> dict[str, object]:
    """Return a stable JSON-compatible representation of one profile."""
    return {
        "name": profile.name,
        "schema_version": profile.schema_version,
        "source_system": profile.source_system,
        "resource_path": profile.resource_path,
        "sha256": profile.sha256,
        "upstream": {
            "repository": profile.upstream_repository,
            "ref": profile.upstream_ref,
            "version": profile.upstream_version,
            "license": profile.upstream_license,
            "minimum_java_version": profile.minimum_java_version,
        },
        "generation": {
            "population_size": profile.population_size,
            "random_seed": profile.random_seed,
            "clinician_seed": profile.clinician_seed,
            "reference_date": profile.reference_date.isoformat(),
            "state": profile.state,
            "city": profile.city,
            "thread_pool_size": profile.thread_pool_size,
            "years_of_history": profile.years_of_history,
        },
        "included_files": list(profile.included_files),
    }


def _read_csv_records(path: Path, expected_header: Sequence[str]) -> list[ClinicalRecord]:
    if not path.exists():
        raise FileNotFoundError(f"Required Synthea CSV file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        actual_header = tuple(reader.fieldnames or ())
        if actual_header != tuple(expected_header):
            raise SyntheaAdapterError(
                f"Unexpected header for {path.name}: {actual_header}; "
                f"expected {tuple(expected_header)}."
            )
        records: list[ClinicalRecord] = []
        for raw in reader:
            record: ClinicalRecord = {}
            for key in expected_header:
                value = raw.get(key)
                record[key] = value if isinstance(value, str) else ""
            records.append(record)
    return records


def _csv_fingerprint(path: Path, expected_header: Sequence[str]) -> SyntheaFileFingerprint:
    records = _read_csv_records(path, expected_header)
    return SyntheaFileFingerprint(
        name=path.name,
        sha256=_sha256_file(path),
        size_bytes=path.stat().st_size,
        row_count=len(records),
        header=tuple(expected_header),
    )


def inspect_synthea_csv_directory(csv_directory: Path) -> tuple[SyntheaFileFingerprint, ...]:
    """Validate the pinned Synthea 4.0.0 CSV schema and fingerprint every source file."""
    if not csv_directory.is_dir():
        raise FileNotFoundError(f"Synthea CSV directory not found: {csv_directory}")
    return tuple(
        _csv_fingerprint(csv_directory / name, SOURCE_HEADERS[name])
        for name in REQUIRED_SOURCE_FILES
    )


def build_synthea_command(
    profile: SyntheaProfile,
    checkout_directory: Path,
    output_directory: Path,
    *,
    windows: bool | None = None,
) -> tuple[str, ...]:
    """Build the exact shell-free command for the pinned generation profile."""
    use_windows = os.name == "nt" if windows is None else windows
    launcher = checkout_directory / ("run_synthea.bat" if use_windows else "run_synthea")
    command = [
        str(launcher),
        "-s",
        str(profile.random_seed),
        "-cs",
        str(profile.clinician_seed),
        "-p",
        str(profile.population_size),
        "-r",
        profile.reference_date.strftime("%Y%m%d"),
        f"--exporter.baseDirectory={output_directory}",
        "--exporter.csv.export=true",
        "--exporter.csv.append_mode=false",
        "--exporter.csv.folder_per_run=false",
        f"--exporter.csv.included_files={','.join(profile.included_files)}",
        "--exporter.fhir.export=false",
        "--exporter.fhir_stu3.export=false",
        "--exporter.fhir_dstu2.export=false",
        "--exporter.hospital.fhir.export=false",
        "--exporter.practitioner.fhir.export=false",
        "--exporter.metadata.export=false",
        f"--exporter.years_of_history={profile.years_of_history}",
        f"--generate.thread_pool_size={profile.thread_pool_size}",
        "--generate.log_patients.detail=none",
        profile.state,
    ]
    if profile.city is not None:
        command.append(profile.city)
    return tuple(command)


def _run_command(command: Sequence[str], *, cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise SyntheaGenerationError(f"Executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        output = (exc.stderr or exc.stdout or "").strip()
        suffix = f": {output[-1000:]}" if output else ""
        raise SyntheaGenerationError(
            f"Command failed with exit code {exc.returncode}{suffix}"
        ) from exc
    return (completed.stdout or completed.stderr or "").strip()


def _verify_checkout(profile: SyntheaProfile, checkout_directory: Path) -> SyntheaCheckout:
    if not (checkout_directory / ".git").is_dir():
        raise SyntheaGenerationError(
            f"Synthea checkout is not a Git worktree: {checkout_directory}"
        )
    commit_sha = _run_command(
        ("git", "-C", str(checkout_directory), "rev-parse", "HEAD")
    ).splitlines()[0]
    exact_ref = _run_command(
        ("git", "-C", str(checkout_directory), "describe", "--tags", "--exact-match")
    ).splitlines()[0]
    if exact_ref != profile.upstream_ref:
        raise SyntheaGenerationError(
            f"Checkout ref is {exact_ref!r}; expected {profile.upstream_ref!r}."
        )
    status = _run_command(
        ("git", "-C", str(checkout_directory), "status", "--porcelain")
    )
    if status:
        raise SyntheaGenerationError("Synthea checkout contains uncommitted changes.")
    return SyntheaCheckout(
        path=checkout_directory,
        commit_sha=commit_sha,
        exact_ref=exact_ref,
    )


def prepare_synthea_checkout(
    profile: SyntheaProfile,
    checkout_directory: Path,
    *,
    replace: bool = False,
) -> SyntheaCheckout:
    """Clone the pinned upstream tag or verify an existing clean checkout."""
    if checkout_directory.exists() and replace:
        shutil.rmtree(checkout_directory)
    if not checkout_directory.exists():
        checkout_directory.parent.mkdir(parents=True, exist_ok=True)
        with log_operation(
            LOGGER,
            "synthea.checkout",
            operation="clone_pinned_upstream",
            upstream_ref=profile.upstream_ref,
        ) as result:
            _run_command(
                (
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    profile.upstream_ref,
                    profile.upstream_repository,
                    str(checkout_directory),
                )
            )
            result["checkout_directory"] = str(checkout_directory)
    return _verify_checkout(profile, checkout_directory)


def _java_version(minimum_version: int) -> str:
    output = _run_command(("java", "-version"))
    first_line = output.splitlines()[0] if output else ""
    match = re.search(r'version\s+"(?P<major>\d+)', first_line)
    if match is None:
        match = re.search(r"openjdk\s+(?P<major>\d+)", first_line, flags=re.IGNORECASE)
    if match is None:
        raise SyntheaGenerationError(f"Could not parse Java version: {first_line!r}")
    major = int(match.group("major"))
    if major < minimum_version:
        raise SyntheaGenerationError(
            f"Java {major} is installed; Synthea profile requires Java {minimum_version}+."
        )
    return first_line


def _file_document(file: SyntheaFileFingerprint) -> dict[str, object]:
    return {
        "name": file.name,
        "sha256": file.sha256,
        "size_bytes": file.size_bytes,
        "row_count": file.row_count,
        "header": list(file.header),
    }


def _generation_fingerprint(
    profile: SyntheaProfile,
    upstream_commit: str,
    source_files: Sequence[SyntheaFileFingerprint],
) -> str:
    return _canonical_json_sha256(
        {
            "profile_sha256": profile.sha256,
            "upstream_commit": upstream_commit,
            "files": [_file_document(file) for file in source_files],
        }
    )


def _normalized_generation_command(
    command: Sequence[str],
    checkout_directory: Path,
    output_directory: Path,
) -> list[str]:
    checkout_text = str(checkout_directory)
    output_text = str(output_directory)
    normalized: list[str] = []
    for argument in command:
        normalized.append(
            argument.replace(checkout_text, "<SYNTHEA_CHECKOUT>").replace(
                output_text,
                "<SYNTHEA_OUTPUT>",
            )
        )
    return normalized


def generate_synthea_dataset(
    workspace: Path,
    *,
    profile: SyntheaProfile | None = None,
    checkout_directory: Path | None = None,
    replace: bool = False,
) -> SyntheaGenerationSummary:
    """Run the pinned Synthea profile and write a content manifest for its CSV files."""
    selected = profile or load_synthea_profile()
    workspace = workspace.resolve()
    checkout_path = (
        checkout_directory.resolve()
        if checkout_directory is not None
        else workspace / "upstream" / f"synthea-{selected.upstream_version}"
    )
    output_directory = workspace / "generated"
    if output_directory.exists() and any(output_directory.iterdir()):
        if not replace:
            raise SyntheaGenerationError(
                f"Generation output is not empty: {output_directory}; use replace=True."
            )
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    with bind_log_context(synthea_profile=selected.name):
        checkout = prepare_synthea_checkout(
            selected,
            checkout_path,
            replace=False,
        )
        java_version = _java_version(selected.minimum_java_version)
        command = build_synthea_command(selected, checkout.path, output_directory)
        with log_operation(
            LOGGER,
            "synthea.generation",
            operation="generate_synthetic_population",
            population_size=selected.population_size,
            reference_date=selected.reference_date.isoformat(),
            upstream_commit=checkout.commit_sha,
        ) as result:
            _run_command(command, cwd=checkout.path)
            result["output_directory"] = str(output_directory)

    csv_directory = output_directory / "csv"
    source_files = inspect_synthea_csv_directory(csv_directory)
    dataset_fingerprint = _generation_fingerprint(
        selected,
        checkout.commit_sha,
        source_files,
    )
    manifest_path = workspace / "synthea-generation-manifest.json"
    manifest: dict[str, object] = {
        "manifest_version": GENERATION_MANIFEST_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "profile": synthea_profile_document(selected),
        "upstream_commit": checkout.commit_sha,
        "java_version": java_version,
        "command": _normalized_generation_command(
            command,
            checkout.path,
            output_directory,
        ),
        "csv_directory": "generated/csv",
        "files": [_file_document(file) for file in source_files],
        "dataset_fingerprint": dataset_fingerprint,
    }
    _write_json(manifest_path, manifest)
    emit_log(
        LOGGER,
        20,
        "synthea.generation.manifest_written",
        "Wrote reproducible Synthea generation manifest.",
        profile_name=selected.name,
        dataset_fingerprint=dataset_fingerprint,
        file_count=len(source_files),
    )
    return SyntheaGenerationSummary(
        profile_name=selected.name,
        profile_sha256=selected.sha256,
        upstream_commit=checkout.commit_sha,
        csv_directory=csv_directory,
        manifest_path=manifest_path,
        dataset_fingerprint=dataset_fingerprint,
        files=source_files,
    )


def _manifest_file_map(raw_files: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(raw_files, list):
        raise SyntheaManifestError("Manifest files must be a list.")
    result: dict[str, Mapping[str, object]] = {}
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise SyntheaManifestError("Manifest file entry must be an object.")
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise SyntheaManifestError("Manifest file entry requires a name.")
        result[name] = {str(key): value for key, value in raw.items()}
    return result


def verify_synthea_generation(
    manifest_path: Path,
    *,
    csv_directory: Path | None = None,
    profile: SyntheaProfile | None = None,
) -> SyntheaGenerationSummary:
    """Verify source CSV bytes, schema, counts, profile identity, and fingerprint."""
    selected = profile or load_synthea_profile()
    manifest = _read_json_object(manifest_path)
    if manifest.get("manifest_version") != GENERATION_MANIFEST_VERSION:
        raise SyntheaManifestError("Unsupported Synthea generation manifest version.")
    profile_document = manifest.get("profile")
    if not isinstance(profile_document, dict):
        raise SyntheaManifestError("Generation manifest has no profile object.")
    if profile_document.get("sha256") != selected.sha256:
        raise SyntheaManifestError("Generation manifest profile hash does not match.")
    upstream_commit = manifest.get("upstream_commit")
    if not isinstance(upstream_commit, str) or len(upstream_commit) != 40:
        raise SyntheaManifestError("Generation manifest has an invalid upstream commit.")
    resolved_csv = csv_directory or manifest_path.parent / "generated" / "csv"
    actual_files = inspect_synthea_csv_directory(resolved_csv)
    expected_files = _manifest_file_map(manifest.get("files"))
    for file in actual_files:
        expected = expected_files.get(file.name)
        if expected is None:
            raise SyntheaManifestError(f"Manifest is missing {file.name}.")
        if expected.get("sha256") != file.sha256:
            raise SyntheaManifestError(f"SHA-256 mismatch for {file.name}.")
        if expected.get("size_bytes") != file.size_bytes:
            raise SyntheaManifestError(f"Byte-size mismatch for {file.name}.")
        if expected.get("row_count") != file.row_count:
            raise SyntheaManifestError(f"Row-count mismatch for {file.name}.")
    fingerprint = _generation_fingerprint(selected, upstream_commit, actual_files)
    if manifest.get("dataset_fingerprint") != fingerprint:
        raise SyntheaManifestError("Generation dataset fingerprint does not match.")
    return SyntheaGenerationSummary(
        profile_name=selected.name,
        profile_sha256=selected.sha256,
        upstream_commit=upstream_commit,
        csv_directory=resolved_csv,
        manifest_path=manifest_path,
        dataset_fingerprint=fingerprint,
        files=actual_files,
    )


def _normalize_datetime(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("Datetime value is empty.")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        parsed = datetime.combine(date.fromisoformat(text), datetime.min.time(), tzinfo=UTC)
        return parsed.isoformat()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _normalize_optional_datetime(value: str) -> str:
    return _normalize_datetime(value) if value.strip() else ""


def _stable_event_id(dataset: str, source_file: str, row_number: int, row: Mapping[str, str]) -> str:
    canonical = json.dumps(
        {key: row.get(key, "").strip() for key in sorted(row)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return str(uuid5(EVENT_NAMESPACE, f"{dataset}|{source_file}|{row_number}|{canonical}"))


def _normalize_encounter_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "inpatient":
        return "INPATIENT"
    if normalized == "emergency":
        return "EMERGENCY"
    return "OUTPATIENT"


def _normalize_code_system(value: str, *, domain: str) -> str | None:
    normalized = value.strip().upper().replace("_", "-")
    aliases = {
        "SNOMED": "SNOMED",
        "SNOMED-CT": "SNOMED",
        "SNOMEDCT": "SNOMED",
        "HTTP://SNOMED.INFO/SCT": "SNOMED",
        "ICD10": "ICD10",
        "ICD-10": "ICD10",
        "ICD10CM": "ICD10",
        "ICD-10-CM": "ICD10",
        "HTTP://HL7.ORG/FHIR/SID/ICD-10-CM": "ICD10",
        "CPT": "CPT",
        "ICD10PCS": "ICD10PCS",
        "ICD-10-PCS": "ICD10PCS",
    }
    resolved = aliases.get(normalized)
    allowed = {
        "condition": {"SNOMED", "ICD10"},
        "procedure": {"SNOMED", "CPT", "ICD10PCS"},
    }
    return resolved if resolved in allowed[domain] else None


def _normalize_observation_unit(code: str, value: str) -> str | None:
    normalized = value.strip().lower().replace(" ", "")
    if code in {"8480-6", "8462-4"} and normalized in {
        "mmhg",
        "mm[hg]",
    }:
        return "mmHg"
    if code == "8867-4" and normalized in {
        "bpm",
        "/min",
        "1/min",
        "{beats}/min",
    }:
        return "bpm"
    return None


def _prepare_output_directory(output_directory: Path, *, replace: bool) -> None:
    if output_directory.exists() and any(output_directory.iterdir()):
        if not replace:
            raise SyntheaAdapterError(
                f"Adaptation output is not empty: {output_directory}; use replace=True."
            )
        shutil.rmtree(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)


def _write_records(path: Path, columns: Sequence[str], records: Sequence[ClinicalRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def _terminology_record(
    system: str,
    code: str,
    display: str,
    domain: str,
    profile: SyntheaProfile,
) -> ClinicalRecord:
    return {
        "code_system": system,
        "code": code,
        "display": display.strip() or f"{system} code {code}",
        "domain": domain,
        "verification_status": "unverified",
        "source_reference": (
            f"Synthea {profile.upstream_version} CSV export; profile {profile.name}"
        ),
    }


def _add_terminology(
    concepts: dict[tuple[str, str], ClinicalRecord],
    record: ClinicalRecord,
) -> None:
    key = (record["code_system"], record["code"])
    existing = concepts.get(key)
    if existing is not None and existing["domain"] != record["domain"]:
        raise SyntheaAdapterError(
            f"Terminology code {key[0]}:{key[1]} appears in multiple clinical domains."
        )
    if existing is None:
        concepts[key] = record


def _validate_adapted_records(
    profile: SyntheaProfile,
    datasets: Mapping[str, list[ClinicalRecord]],
) -> None:
    for dataset in dataset_names():
        contract = get_dataset_definition(dataset).contract
        result = validate_records_against_contract(
            datasets[dataset],
            contract,
            reference_date=profile.reference_date,
        )
        if result.invalid_records or result.errors:
            details = "; ".join(
                f"row={error.row_number} field={error.field} rule={error.rule}"
                for error in result.errors[:5]
            )
            raise SyntheaAdapterError(
                f"Adapted {dataset} records violate contract {contract.version}: {details}"
            )


def _adapt_patients(
    rows: Sequence[ClinicalRecord],
    profile: SyntheaProfile,
) -> list[ClinicalRecord]:
    adapted: list[ClinicalRecord] = []
    for row in rows:
        gender = row["GENDER"].strip().upper()
        adapted.append(
            {
                "patient_id": row["Id"].strip(),
                "sex_at_birth": gender if gender in {"F", "M"} else "UNKNOWN",
                "birth_date": row["BIRTHDATE"].strip(),
                "death_date": row["DEATHDATE"].strip(),
                "source_system": profile.source_system,
            }
        )
    return sorted(adapted, key=lambda record: record["patient_id"])


def _adapt_encounters(
    rows: Sequence[ClinicalRecord],
    profile: SyntheaProfile,
    patient_ids: set[str],
    omitted: Counter[str],
) -> list[ClinicalRecord]:
    adapted: list[ClinicalRecord] = []
    for row in rows:
        patient_id = row["PATIENT"].strip()
        if patient_id not in patient_ids:
            omitted["encounter_unknown_patient"] += 1
            continue
        try:
            start = _normalize_datetime(row["START"])
            stop = _normalize_datetime(row["STOP"])
        except ValueError:
            omitted["encounter_invalid_datetime"] += 1
            continue
        adapted.append(
            {
                "encounter_id": row["Id"].strip(),
                "patient_id": patient_id,
                "encounter_type": _normalize_encounter_type(row["ENCOUNTERCLASS"]),
                "start_datetime": start,
                "end_datetime": stop,
                "source_system": profile.source_system,
            }
        )
    return sorted(adapted, key=lambda record: record["encounter_id"])


def _event_has_parent(
    patient_id: str,
    encounter_id: str,
    patient_ids: set[str],
    encounter_patients: Mapping[str, str],
) -> bool:
    return (
        patient_id in patient_ids
        and encounter_id in encounter_patients
        and encounter_patients[encounter_id] == patient_id
    )


def _adapt_conditions(
    rows: Sequence[ClinicalRecord],
    profile: SyntheaProfile,
    patient_ids: set[str],
    encounter_patients: Mapping[str, str],
    omitted: Counter[str],
    concepts: dict[tuple[str, str], ClinicalRecord],
) -> list[ClinicalRecord]:
    adapted: list[ClinicalRecord] = []
    for index, row in enumerate(rows, start=2):
        patient_id = row["PATIENT"].strip()
        encounter_id = row["ENCOUNTER"].strip()
        if not _event_has_parent(
            patient_id,
            encounter_id,
            patient_ids,
            encounter_patients,
        ):
            omitted["condition_invalid_parent"] += 1
            continue
        system = _normalize_code_system(row["SYSTEM"], domain="condition")
        code = row["CODE"].strip()
        if system is None or not code:
            omitted["condition_unsupported_code"] += 1
            continue
        try:
            occurred_at = _normalize_datetime(row["START"])
        except ValueError:
            omitted["condition_invalid_datetime"] += 1
            continue
        adapted.append(
            {
                "diagnosis_id": _stable_event_id(
                    "diagnoses",
                    "conditions.csv",
                    index,
                    row,
                ),
                "patient_id": patient_id,
                "encounter_id": encounter_id,
                "code_system": system,
                "diagnosis_code": code,
                "diagnosis_datetime": occurred_at,
                "source_system": profile.source_system,
            }
        )
        _add_terminology(
            concepts,
            _terminology_record(
                system,
                code,
                row["DESCRIPTION"],
                "condition",
                profile,
            ),
        )
    return sorted(adapted, key=lambda record: record["diagnosis_id"])


def _adapt_observations(
    rows: Sequence[ClinicalRecord],
    profile: SyntheaProfile,
    patient_ids: set[str],
    encounter_patients: Mapping[str, str],
    omitted: Counter[str],
) -> list[ClinicalRecord]:
    adapted: list[ClinicalRecord] = []
    for index, row in enumerate(rows, start=2):
        source_code = row["CODE"].strip()
        profile_value = OBSERVATION_CODES.get(source_code)
        if profile_value is None:
            omitted["observation_outside_supported_subset"] += 1
            continue
        patient_id = row["PATIENT"].strip()
        encounter_id = row["ENCOUNTER"].strip()
        if not _event_has_parent(
            patient_id,
            encounter_id,
            patient_ids,
            encounter_patients,
        ):
            omitted["observation_invalid_parent"] += 1
            continue
        try:
            numeric = float(row["VALUE"].strip())
        except ValueError:
            omitted["observation_non_numeric"] += 1
            continue
        if not math.isfinite(numeric):
            omitted["observation_non_finite"] += 1
            continue
        observation_code, expected_unit = profile_value
        unit = _normalize_observation_unit(source_code, row["UNITS"])
        if unit != expected_unit:
            omitted["observation_unsupported_unit"] += 1
            continue
        try:
            observed_at = _normalize_datetime(row["DATE"])
        except ValueError:
            omitted["observation_invalid_datetime"] += 1
            continue
        adapted.append(
            {
                "observation_id": _stable_event_id(
                    "observations",
                    "observations.csv",
                    index,
                    row,
                ),
                "patient_id": patient_id,
                "encounter_id": encounter_id,
                "observation_code": observation_code,
                "value_numeric": format(numeric, ".15g"),
                "unit": unit,
                "observed_at": observed_at,
                "source_system": profile.source_system,
            }
        )
    return sorted(adapted, key=lambda record: record["observation_id"])


def _adapt_medications(
    rows: Sequence[ClinicalRecord],
    profile: SyntheaProfile,
    patient_ids: set[str],
    encounter_patients: Mapping[str, str],
    omitted: Counter[str],
    concepts: dict[tuple[str, str], ClinicalRecord],
) -> list[ClinicalRecord]:
    adapted: list[ClinicalRecord] = []
    for index, row in enumerate(rows, start=2):
        patient_id = row["PATIENT"].strip()
        encounter_id = row["ENCOUNTER"].strip()
        if not _event_has_parent(
            patient_id,
            encounter_id,
            patient_ids,
            encounter_patients,
        ):
            omitted["medication_invalid_parent"] += 1
            continue
        code = row["CODE"].strip()
        if not code:
            omitted["medication_missing_code"] += 1
            continue
        try:
            start = _normalize_datetime(row["START"])
            stop = _normalize_optional_datetime(row["STOP"])
        except ValueError:
            omitted["medication_invalid_datetime"] += 1
            continue
        adapted.append(
            {
                "medication_id": _stable_event_id(
                    "medications",
                    "medications.csv",
                    index,
                    row,
                ),
                "patient_id": patient_id,
                "encounter_id": encounter_id,
                "code_system": "RXNORM",
                "medication_code": code,
                "status": "COMPLETED" if stop else "ACTIVE",
                "start_datetime": start,
                "end_datetime": stop,
                "dose_value": "",
                "dose_unit": "",
                "route": "",
                "source_system": profile.source_system,
            }
        )
        _add_terminology(
            concepts,
            _terminology_record(
                "RXNORM",
                code,
                row["DESCRIPTION"],
                "medication",
                profile,
            ),
        )
    return sorted(adapted, key=lambda record: record["medication_id"])


def _adapt_procedures(
    rows: Sequence[ClinicalRecord],
    profile: SyntheaProfile,
    patient_ids: set[str],
    encounter_patients: Mapping[str, str],
    omitted: Counter[str],
    concepts: dict[tuple[str, str], ClinicalRecord],
) -> list[ClinicalRecord]:
    adapted: list[ClinicalRecord] = []
    for index, row in enumerate(rows, start=2):
        patient_id = row["PATIENT"].strip()
        encounter_id = row["ENCOUNTER"].strip()
        if not _event_has_parent(
            patient_id,
            encounter_id,
            patient_ids,
            encounter_patients,
        ):
            omitted["procedure_invalid_parent"] += 1
            continue
        system = _normalize_code_system(row["SYSTEM"], domain="procedure")
        code = row["CODE"].strip()
        if system is None or not code:
            omitted["procedure_unsupported_code"] += 1
            continue
        try:
            occurred_at = _normalize_datetime(row["START"])
        except ValueError:
            omitted["procedure_invalid_datetime"] += 1
            continue
        adapted.append(
            {
                "procedure_id": _stable_event_id(
                    "procedures",
                    "procedures.csv",
                    index,
                    row,
                ),
                "patient_id": patient_id,
                "encounter_id": encounter_id,
                "code_system": system,
                "procedure_code": code,
                "procedure_datetime": occurred_at,
                "status": "COMPLETED",
                "source_system": profile.source_system,
            }
        )
        _add_terminology(
            concepts,
            _terminology_record(
                system,
                code,
                row["DESCRIPTION"],
                "procedure",
                profile,
            ),
        )
    return sorted(adapted, key=lambda record: record["procedure_id"])


def _output_fingerprints(output_directory: Path) -> tuple[SyntheaFileFingerprint, ...]:
    fingerprints: list[SyntheaFileFingerprint] = []
    for dataset in dataset_names():
        columns = get_dataset_definition(dataset).columns
        path = output_directory / f"{dataset}.csv"
        fingerprints.append(_csv_fingerprint(path, columns))
    fingerprints.append(_csv_fingerprint(output_directory / "terminology.csv", TERMINOLOGY_COLUMNS))
    return tuple(fingerprints)


def _adaptation_fingerprint(
    profile: SyntheaProfile,
    source_files: Sequence[SyntheaFileFingerprint],
    output_files: Sequence[SyntheaFileFingerprint],
    omitted: Mapping[str, int],
) -> str:
    return _canonical_json_sha256(
        {
            "adapter_version": ADAPTER_VERSION,
            "profile_sha256": profile.sha256,
            "source_files": [_file_document(file) for file in source_files],
            "output_files": [_file_document(file) for file in output_files],
            "omitted_rows": dict(sorted(omitted.items())),
        }
    )


def adapt_synthea_csv(
    csv_directory: Path,
    output_directory: Path,
    *,
    profile: SyntheaProfile | None = None,
    generation_manifest_path: Path | None = None,
    replace: bool = False,
) -> SyntheaAdaptationSummary:
    """Convert the pinned Synthea CSV schema into six contract-ready datasets."""
    selected = profile or load_synthea_profile()
    if generation_manifest_path is not None:
        verify_synthea_generation(
            generation_manifest_path,
            csv_directory=csv_directory,
            profile=selected,
        )
    source_files = inspect_synthea_csv_directory(csv_directory)
    _prepare_output_directory(output_directory, replace=replace)
    source_rows = {
        name: _read_csv_records(csv_directory / name, SOURCE_HEADERS[name])
        for name in REQUIRED_SOURCE_FILES
    }
    omitted: Counter[str] = Counter()
    concepts: dict[tuple[str, str], ClinicalRecord] = {}

    with bind_log_context(synthea_profile=selected.name):
        with log_operation(
            LOGGER,
            "synthea.adaptation",
            operation="adapt_synthea_csv",
            source_directory=str(csv_directory),
        ) as result:
            patients = _adapt_patients(source_rows["patients.csv"], selected)
            patient_ids = {record["patient_id"] for record in patients}
            encounters = _adapt_encounters(
                source_rows["encounters.csv"],
                selected,
                patient_ids,
                omitted,
            )
            encounter_patients = {
                record["encounter_id"]: record["patient_id"] for record in encounters
            }
            datasets: dict[str, list[ClinicalRecord]] = {
                "patients": patients,
                "encounters": encounters,
                "diagnoses": _adapt_conditions(
                    source_rows["conditions.csv"],
                    selected,
                    patient_ids,
                    encounter_patients,
                    omitted,
                    concepts,
                ),
                "observations": _adapt_observations(
                    source_rows["observations.csv"],
                    selected,
                    patient_ids,
                    encounter_patients,
                    omitted,
                ),
                "medications": _adapt_medications(
                    source_rows["medications.csv"],
                    selected,
                    patient_ids,
                    encounter_patients,
                    omitted,
                    concepts,
                ),
                "procedures": _adapt_procedures(
                    source_rows["procedures.csv"],
                    selected,
                    patient_ids,
                    encounter_patients,
                    omitted,
                    concepts,
                ),
            }
            _validate_adapted_records(selected, datasets)
            for dataset in dataset_names():
                _write_records(
                    output_directory / f"{dataset}.csv",
                    get_dataset_definition(dataset).columns,
                    datasets[dataset],
                )
            terminology_rows = [concepts[key] for key in sorted(concepts)]
            _write_records(
                output_directory / "terminology.csv",
                TERMINOLOGY_COLUMNS,
                terminology_rows,
            )
            result["dataset_rows"] = {
                dataset: len(datasets[dataset]) for dataset in dataset_names()
            }
            result["terminology_concepts"] = len(terminology_rows)
            result["omitted_rows"] = dict(sorted(omitted.items()))

    output_files = _output_fingerprints(output_directory)
    fingerprint = _adaptation_fingerprint(
        selected,
        source_files,
        output_files,
        omitted,
    )
    dataset_rows = {
        dataset: next(
            file.row_count for file in output_files if file.name == f"{dataset}.csv"
        )
        for dataset in dataset_names()
    }
    terminology_count = next(
        file.row_count for file in output_files if file.name == "terminology.csv"
    )
    manifest_path = output_directory / "synthea-adaptation-manifest.json"
    manifest: dict[str, object] = {
        "manifest_version": ADAPTATION_MANIFEST_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "adapter_version": ADAPTER_VERSION,
        "profile": synthea_profile_document(selected),
        "source_directory": str(csv_directory),
        "source_files": [_file_document(file) for file in source_files],
        "output_files": [_file_document(file) for file in output_files],
        "dataset_rows": dataset_rows,
        "omitted_rows": dict(sorted(omitted.items())),
        "terminology_concepts": terminology_count,
        "adaptation_fingerprint": fingerprint,
    }
    if generation_manifest_path is not None:
        manifest["generation_manifest_sha256"] = _sha256_file(generation_manifest_path)
    _write_json(manifest_path, manifest)
    return SyntheaAdaptationSummary(
        profile_name=selected.name,
        profile_sha256=selected.sha256,
        output_directory=output_directory,
        manifest_path=manifest_path,
        adaptation_fingerprint=fingerprint,
        dataset_rows=dataset_rows,
        omitted_rows=dict(sorted(omitted.items())),
        terminology_concepts=terminology_count,
    )


def verify_synthea_adaptation(
    output_directory: Path,
    *,
    profile: SyntheaProfile | None = None,
) -> SyntheaAdaptationSummary:
    """Verify every adapted artifact and its deterministic adaptation fingerprint."""
    selected = profile or load_synthea_profile()
    manifest_path = output_directory / "synthea-adaptation-manifest.json"
    manifest = _read_json_object(manifest_path)
    if manifest.get("manifest_version") != ADAPTATION_MANIFEST_VERSION:
        raise SyntheaManifestError("Unsupported adaptation manifest version.")
    if manifest.get("adapter_version") != ADAPTER_VERSION:
        raise SyntheaManifestError("Adaptation manifest uses another adapter version.")
    profile_document = manifest.get("profile")
    if not isinstance(profile_document, dict) or profile_document.get("sha256") != selected.sha256:
        raise SyntheaManifestError("Adaptation profile hash does not match.")
    source_directory = manifest.get("source_directory")
    if not isinstance(source_directory, str) or not source_directory:
        raise SyntheaManifestError("Adaptation manifest has no source directory.")
    source_files = inspect_synthea_csv_directory(Path(source_directory))
    actual_output = _output_fingerprints(output_directory)
    expected_output = _manifest_file_map(manifest.get("output_files"))
    for file in actual_output:
        expected = expected_output.get(file.name)
        if expected is None or expected.get("sha256") != file.sha256:
            raise SyntheaManifestError(f"Adapted file hash mismatch: {file.name}")
        if expected.get("row_count") != file.row_count:
            raise SyntheaManifestError(f"Adapted row-count mismatch: {file.name}")
        if expected.get("size_bytes") != file.size_bytes:
            raise SyntheaManifestError(f"Adapted byte-size mismatch: {file.name}")
    omitted_raw = manifest.get("omitted_rows")
    if not isinstance(omitted_raw, dict):
        raise SyntheaManifestError("Adaptation manifest omitted_rows must be an object.")
    omitted = {
        str(key): int(value)
        for key, value in omitted_raw.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    fingerprint = _adaptation_fingerprint(
        selected,
        source_files,
        actual_output,
        omitted,
    )
    if manifest.get("adaptation_fingerprint") != fingerprint:
        raise SyntheaManifestError("Adaptation fingerprint does not match.")
    dataset_rows = {
        dataset: next(
            file.row_count for file in actual_output if file.name == f"{dataset}.csv"
        )
        for dataset in dataset_names()
    }
    terminology_count = next(
        file.row_count for file in actual_output if file.name == "terminology.csv"
    )
    return SyntheaAdaptationSummary(
        profile_name=selected.name,
        profile_sha256=selected.sha256,
        output_directory=output_directory,
        manifest_path=manifest_path,
        adaptation_fingerprint=fingerprint,
        dataset_rows=dataset_rows,
        omitted_rows=omitted,
        terminology_concepts=terminology_count,
    )


def import_synthea_terminology(
    connection: psycopg.Connection[Any],
    terminology_path: Path,
) -> SyntheaTerminologyImportSummary:
    """Import source concepts as explicit unverified local terminology entries."""
    records = _read_csv_records(terminology_path, TERMINOLOGY_COLUMNS)
    inserted = 0
    existing = 0
    with connection.transaction():
        for record in records:
            source_system = record["code_system"].strip().upper()
            canonical_system = CANONICAL_TERMINOLOGY_SYSTEMS.get(source_system)
            if canonical_system is None:
                raise SyntheaAdapterError(
                    f"Cannot import unsupported terminology system {source_system!r}."
                )
            code = record["code"].strip()
            domain = record["domain"].strip()
            current = connection.execute(
                """
                SELECT domain
                FROM terminology.concepts
                WHERE code_system_id = %s
                  AND code = %s
                """,
                (canonical_system, code),
            ).fetchone()
            if current is not None:
                if str(current[0]) != domain:
                    raise SyntheaAdapterError(
                        f"Existing terminology domain differs for {source_system}:{code}."
                    )
                existing += 1
                continue
            connection.execute(
                """
                INSERT INTO terminology.concepts (
                    code_system_id,
                    code,
                    display,
                    domain,
                    active,
                    verification_status,
                    source_reference
                )
                VALUES (%s, %s, %s, %s, TRUE, 'unverified', %s)
                """,
                (
                    canonical_system,
                    code,
                    record["display"].strip(),
                    domain,
                    record["source_reference"].strip(),
                ),
            )
            inserted += 1
    return SyntheaTerminologyImportSummary(
        concepts_received=len(records),
        concepts_inserted=inserted,
        concepts_existing=existing,
    )


def load_adapted_synthea_dataset(
    connection: psycopg.Connection[Any],
    normalized_directory: Path,
    processed_root: Path,
    *,
    raw_root: Path,
    profile: SyntheaProfile | None = None,
) -> SyntheaLoadSummary:
    """Verify, validate, and persist all six adapted datasets using existing pipelines."""
    from clinical_data_platform.database import persist_dataset_validation_outputs
    from clinical_data_platform.pipeline import run_dataset_validation

    selected = profile or load_synthea_profile()
    verify_synthea_adaptation(normalized_directory, profile=selected)
    terminology = import_synthea_terminology(
        connection,
        normalized_directory / "terminology.csv",
    )
    run_ids: dict[str, UUID] = {}
    records_persisted: dict[str, int] = {}
    for dataset in dataset_names():
        validation = run_dataset_validation(
            dataset,
            normalized_directory / f"{dataset}.csv",
            processed_root / dataset,
            raw_root=raw_root,
            reference_date=selected.reference_date,
        )
        if validation.rows_invalid or validation.validation_errors:
            raise SyntheaAdapterError(
                f"Adapted {dataset} unexpectedly failed contract validation."
            )
        persistence = persist_dataset_validation_outputs(
            connection,
            dataset,
            processed_root / dataset,
            raw_root=raw_root,
        )
        run_ids[dataset] = validation.run_id
        records_persisted[dataset] = persistence.records_upserted
    return SyntheaLoadSummary(
        terminology=terminology,
        run_ids=run_ids,
        records_persisted=records_persisted,
    )
