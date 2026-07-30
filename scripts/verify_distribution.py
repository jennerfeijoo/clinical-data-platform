#!/usr/bin/env python3
"""Verify built wheel and source-distribution contents and write release evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path
from typing import Final

WHEEL_REQUIRED: Final = (
    "clinical_data_platform/py.typed",
    "clinical_data_platform/cohort_definitions/hypertension.sql",
    "clinical_data_platform/contracts/manifest.toml",
    "clinical_data_platform/migrations/V008__add_execution_lifecycle_audit.sql",
)
WHEEL_FORBIDDEN_PREFIXES: Final = (
    ".github/",
    "data/",
    "docs/",
    "scripts/",
    "security/",
    "tests/",
)
SDIST_REQUIRED_SUFFIXES: Final = (
    "/CHANGELOG.md",
    "/CITATION.cff",
    "/CONTRIBUTING.md",
    "/LICENSE",
    "/README.md",
    "/SECURITY.md",
    "/SUPPORT.md",
    "/build_backend.py",
    "/docs/index.md",
    "/docs/limitations.md",
    "/docs/release-process.md",
    "/sql/cohorts/hypertension.sql",
    "/src/clinical_data_platform/cohort_definitions/hypertension.sql",
    "/src/clinical_data_platform/py.typed",
)
SDIST_FORBIDDEN_PARTS: Final = (
    "/.env",
    "/.git/",
    "/benchmarks/",
    "/data/analytics/",
    "/data/processed/",
    "/data/raw/",
    "/data/synthea/",
)
EXPECTED_PYTHON_CLAUSES: Final = frozenset({">=3.11", "<3.15"})


class DistributionError(RuntimeError):
    """Raised when built distribution artifacts violate release policy."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifact_pair(dist_directory: Path) -> tuple[Path, Path]:
    wheels = sorted(dist_directory.glob("*.whl"))
    sdists = sorted(dist_directory.glob("*.tar.gz"))
    unexpected = sorted(
        path.name
        for path in dist_directory.iterdir()
        if path.is_file() and path not in {*wheels, *sdists}
    )
    if len(wheels) != 1 or len(sdists) != 1 or unexpected:
        raise DistributionError(
            "Expected exactly one wheel and one tar.gz sdist with no other files; "
            f"wheels={len(wheels)}, sdists={len(sdists)}, unexpected={unexpected}."
        )
    return wheels[0], sdists[0]


def _metadata_value(metadata: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", metadata, flags=re.MULTILINE)
    if match is None:
        raise DistributionError(f"Wheel METADATA does not contain {key}.")
    return match.group(1).strip()


def _python_clauses(value: str) -> frozenset[str]:
    return frozenset(clause.strip() for clause in value.split(",") if clause.strip())


def _verify_wheel(wheel: Path, expected_version: str) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        names = tuple(sorted(archive.namelist()))
        name_set = set(names)
        missing = [name for name in WHEEL_REQUIRED if name not in name_set]
        if missing:
            raise DistributionError(f"Wheel is missing runtime resources: {missing}")
        forbidden = [
            name
            for name in names
            if any(name.startswith(prefix) for prefix in WHEEL_FORBIDDEN_PREFIXES)
        ]
        if forbidden:
            raise DistributionError(
                f"Wheel contains repository-only paths: {forbidden[:10]}"
            )

        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        entry_point_files = [
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        ]
        if len(metadata_files) != 1 or len(entry_point_files) != 1:
            raise DistributionError(
                "Wheel must contain exactly one METADATA and one entry_points.txt file."
            )
        metadata = archive.read(metadata_files[0]).decode("utf-8")
        entry_points = archive.read(entry_point_files[0]).decode("utf-8")

    version = _metadata_value(metadata, "Version")
    if version != expected_version:
        raise DistributionError(
            f"Wheel version {version} does not match expected {expected_version}."
        )
    requires_python = _metadata_value(metadata, "Requires-Python")
    if _python_clauses(requires_python) != EXPECTED_PYTHON_CLAUSES:
        raise DistributionError(
            f"Unexpected wheel Requires-Python value: {requires_python}"
        )
    for command in ("clinical-data", "clinical-data-benchmark", "clinical-data-cohort"):
        if f"{command} =" not in entry_points:
            raise DistributionError(f"Wheel is missing the {command} entrypoint.")

    contract_count = sum(
        name.startswith("clinical_data_platform/contracts/")
        and name.endswith(".toml")
        for name in names
    )
    migration_count = sum(
        name.startswith("clinical_data_platform/migrations/")
        and name.endswith(".sql")
        for name in names
    )
    profile_count = sum(
        name.startswith("clinical_data_platform/synthea_profiles/")
        and name.endswith(".toml")
        for name in names
    )
    if contract_count < 7 or migration_count != 8 or profile_count < 2:
        raise DistributionError(
            "Wheel resource counts are incomplete: "
            f"contracts={contract_count}, migrations={migration_count}, "
            f"profiles={profile_count}."
        )
    return {
        "filename": wheel.name,
        "size_bytes": wheel.stat().st_size,
        "sha256": _sha256(wheel),
        "member_count": len(names),
        "contract_resource_count": contract_count,
        "migration_resource_count": migration_count,
        "synthea_profile_count": profile_count,
        "requires_python": requires_python,
    }


def _verify_sdist(sdist: Path, expected_version: str) -> dict[str, object]:
    with tarfile.open(sdist, mode="r:gz") as archive:
        names = tuple(sorted(member.name for member in archive.getmembers()))
    roots = {name.split("/", maxsplit=1)[0] for name in names if "/" in name}
    expected_root = f"clinical_data_platform-{expected_version}"
    if roots != {expected_root}:
        raise DistributionError(
            f"Unexpected source-distribution root directories: {sorted(roots)}"
        )
    missing = [
        suffix
        for suffix in SDIST_REQUIRED_SUFFIXES
        if not any(name.endswith(suffix) for name in names)
    ]
    if missing:
        raise DistributionError(f"Source distribution is missing files: {missing}")
    forbidden = [
        name
        for name in names
        if any(part in f"/{name}" for part in SDIST_FORBIDDEN_PARTS)
    ]
    if forbidden:
        raise DistributionError(
            f"Source distribution contains forbidden paths: {forbidden[:10]}"
        )
    return {
        "filename": sdist.name,
        "size_bytes": sdist.stat().st_size,
        "sha256": _sha256(sdist),
        "member_count": len(names),
        "root_directory": expected_root,
    }


def verify_distribution(
    dist_directory: Path,
    expected_version: str,
) -> dict[str, object]:
    """Verify a wheel/sdist pair and return deterministic release evidence."""
    if not dist_directory.is_dir():
        raise DistributionError(f"Distribution directory not found: {dist_directory}")
    wheel, sdist = _artifact_pair(dist_directory)
    return {
        "schema_version": "1.0.0",
        "project": "clinical-data-platform",
        "version": expected_version,
        "artifacts": {
            "wheel": _verify_wheel(wheel, expected_version),
            "sdist": _verify_sdist(sdist, expected_version),
        },
    }


def _write_checksums(summary: dict[str, object], path: Path) -> None:
    artifacts = summary["artifacts"]
    if not isinstance(artifacts, dict):
        raise DistributionError("Artifact summary has an invalid structure.")
    lines: list[str] = []
    for key in sorted(artifacts):
        artifact = artifacts[key]
        if not isinstance(artifact, dict):
            raise DistributionError("Artifact summary has an invalid entry.")
        lines.append(f"{artifact['sha256']}  {artifact['filename']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_directory", type=Path)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--checksums", type=Path, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        summary = verify_distribution(args.dist_directory, args.expected_version)
        if args.manifest is not None:
            args.manifest.write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if args.checksums is not None:
            _write_checksums(summary, args.checksums)
    except DistributionError as error:
        raise SystemExit(f"Distribution verification failed: {error}") from error
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
