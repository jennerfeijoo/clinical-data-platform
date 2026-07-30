#!/usr/bin/env python3
"""Validate release metadata, documentation, and packaged resource policy."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
SEMANTIC_VERSION: Final = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REQUIRED_RELEASE_FILES: Final = (
    "CHANGELOG.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "SUPPORT.md",
    "docs/index.md",
    "docs/release-process.md",
    "docs/limitations.md",
)


class ReleaseCheckError(RuntimeError):
    """Raised when release metadata or release policy is inconsistent."""


def _read(path: Path) -> str:
    if not path.is_file():
        raise ReleaseCheckError(
            f"Required release file is missing: {path.relative_to(ROOT)}"
        )
    return path.read_text(encoding="utf-8")


def _single_match(pattern: str, text: str, label: str) -> str:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if len(matches) != 1:
        raise ReleaseCheckError(
            f"Expected exactly one {label}; found {len(matches)}."
        )
    value = matches[0]
    return str(value)


def _first_changelog_version(text: str) -> str:
    versions = re.findall(
        r"^##\s+([0-9]+\.[0-9]+\.[0-9]+)\s*$",
        text,
        flags=re.MULTILINE,
    )
    if not versions:
        raise ReleaseCheckError("CHANGELOG.md has no semantic version heading.")
    if len(versions) != len(set(versions)):
        raise ReleaseCheckError("CHANGELOG.md contains duplicate version headings.")
    return versions[0]


def _citation_scalar(text: str, key: str) -> str:
    pattern = rf"^{re.escape(key)}:\s*[\"']?([^\"'\n]+)[\"']?\s*$"
    return _single_match(pattern, text, f"CITATION.cff {key}")


def _version_sources(root: Path) -> dict[str, str]:
    pyproject = tomllib.loads(_read(root / "pyproject.toml"))
    project_version = str(pyproject["project"]["version"])
    init_version = _single_match(
        r'^__version__\s*=\s*["\']([^"\']+)["\']$',
        _read(root / "src" / "clinical_data_platform" / "__init__.py"),
        "package __version__ assignment",
    )
    changelog_version = _first_changelog_version(_read(root / "CHANGELOG.md"))
    citation_version = _citation_scalar(_read(root / "CITATION.cff"), "version")
    readme_version = _single_match(
        r"^> Status:.*version `([0-9]+\.[0-9]+\.[0-9]+)`.*$",
        _read(root / "README.md"),
        "README status version",
    )
    package_test_version = _single_match(
        r'__version__\s*==\s*["\']([^"\']+)["\']',
        _read(root / "tests" / "test_package.py"),
        "package version assertion",
    )
    ci_version = _single_match(
        r"importlib\.metadata\.version\('clinical-data-platform'\)\s*==\s*'([^']+)'",
        _read(root / ".github" / "workflows" / "ci.yml"),
        "CI package version assertion",
    )
    return {
        "pyproject": project_version,
        "package": init_version,
        "changelog": changelog_version,
        "citation": citation_version,
        "readme": readme_version,
        "package_test": package_test_version,
        "ci": ci_version,
    }


def _validate_release_extra(pyproject: dict[str, object]) -> tuple[str, ...]:
    project = pyproject["project"]
    if not isinstance(project, dict):
        raise ReleaseCheckError("pyproject project metadata is not a table.")
    optional = project.get("optional-dependencies")
    if not isinstance(optional, dict):
        raise ReleaseCheckError("pyproject optional dependencies are missing.")
    release_dependencies = optional.get("release")
    if not isinstance(release_dependencies, list):
        raise ReleaseCheckError("The release optional dependency group is missing.")
    names = tuple(
        str(item).split("<", maxsplit=1)[0].split(">", maxsplit=1)[0]
        for item in release_dependencies
    )
    if not any(name.startswith("build") for name in names):
        raise ReleaseCheckError("The release dependency group must include build.")
    if not any(name.startswith("twine") for name in names):
        raise ReleaseCheckError("The release dependency group must include twine.")
    return tuple(str(item) for item in release_dependencies)


def _validate_package_data(pyproject: dict[str, object]) -> None:
    tool = pyproject.get("tool")
    if not isinstance(tool, dict):
        raise ReleaseCheckError("pyproject tool metadata is missing.")
    setuptools = tool.get("setuptools")
    if not isinstance(setuptools, dict):
        raise ReleaseCheckError("setuptools configuration is missing.")
    package_data = setuptools.get("package-data")
    if not isinstance(package_data, dict):
        raise ReleaseCheckError("setuptools package-data configuration is missing.")
    root_data = package_data.get("clinical_data_platform")
    cohort_data = package_data.get("clinical_data_platform.cohort_definitions")
    if not isinstance(root_data, list) or "py.typed" not in root_data:
        raise ReleaseCheckError("The wheel must include the py.typed marker.")
    if not isinstance(cohort_data, list) or "*.sql" not in cohort_data:
        raise ReleaseCheckError("The wheel must include packaged cohort SQL resources.")


def validate_release(
    root: Path = ROOT,
    *,
    expected_version: str | None = None,
    expected_tag: str | None = None,
) -> dict[str, object]:
    """Validate all release invariants and return a machine-readable summary."""
    for relative_path in REQUIRED_RELEASE_FILES:
        _read(root / relative_path)

    versions = _version_sources(root)
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        raise ReleaseCheckError(f"Release versions disagree: {versions}")
    version = unique_versions.pop()
    if SEMANTIC_VERSION.fullmatch(version) is None:
        raise ReleaseCheckError(f"Release version is not X.Y.Z: {version}")
    if expected_version is not None and version != expected_version:
        raise ReleaseCheckError(
            f"Expected version {expected_version}, but metadata declares {version}."
        )
    expected_release_tag = f"v{version}"
    if expected_tag is not None and expected_tag != expected_release_tag:
        raise ReleaseCheckError(
            f"Expected tag {expected_release_tag}, but received {expected_tag}."
        )

    pyproject = tomllib.loads(_read(root / "pyproject.toml"))
    release_dependencies = _validate_release_extra(pyproject)
    _validate_package_data(pyproject)

    root_sql = (root / "sql" / "cohorts" / "hypertension.sql").read_bytes()
    packaged_sql = (
        root
        / "src"
        / "clinical_data_platform"
        / "cohort_definitions"
        / "hypertension.sql"
    ).read_bytes()
    if root_sql != packaged_sql:
        raise ReleaseCheckError(
            "The repository and packaged hypertension SQL definitions differ."
        )

    citation = _read(root / "CITATION.cff")
    release_date = _citation_scalar(citation, "date-released")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", release_date) is None:
        raise ReleaseCheckError(
            f"CITATION.cff date-released is not an ISO date: {release_date}"
        )

    release_workflow = _read(root / ".github" / "workflows" / "release.yml")
    required_workflow_fragments = (
        'tags: ["v[0-9]*.[0-9]*.[0-9]*"]',
        "python scripts/check_release.py",
        "python -m build",
        "python -m twine check",
        "python scripts/verify_distribution.py",
        "gh release create",
    )
    missing_workflow = [
        fragment
        for fragment in required_workflow_fragments
        if fragment not in release_workflow
    ]
    if missing_workflow:
        raise ReleaseCheckError(
            f"Release workflow is missing required controls: {missing_workflow}"
        )

    return {
        "schema_version": "1.0.0",
        "version": version,
        "expected_tag": expected_release_tag,
        "release_date": release_date,
        "version_sources": versions,
        "release_dependencies": list(release_dependencies),
        "required_files": list(REQUIRED_RELEASE_FILES),
        "packaged_cohort_sql_matches_repository": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default=None)
    parser.add_argument("--expected-tag", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        summary = validate_release(
            expected_version=args.expected_version,
            expected_tag=args.expected_tag,
        )
    except ReleaseCheckError as error:
        raise SystemExit(f"Release check failed: {error}") from error
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
