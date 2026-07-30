from __future__ import annotations

import gzip
import io
import json
import subprocess
import sys
import tarfile
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

from build_backend import normalize_sdist
from clinical_data_platform.cli import build_parser
from clinical_data_platform.cohort import load_hypertension_cohort_sql

ROOT = Path(__file__).resolve().parents[1]


def test_release_metadata_gate_passes_for_current_version() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/check_release.py",
            "--expected-version",
            "1.0.0",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    assert summary["version"] == "1.0.0"
    assert summary["expected_tag"] == "v1.0.0"
    assert summary["packaged_cohort_sql_matches_repository"] is True


def test_packaged_hypertension_definition_matches_repository_copy() -> None:
    sql, source = load_hypertension_cohort_sql()

    assert source == "clinical_data_platform.cohort_definitions:hypertension.sql"
    assert sql == (ROOT / "sql" / "cohorts" / "hypertension.sql").read_text(
        encoding="utf-8"
    )
    assert "INSERT INTO analytics.hypertension_features" in sql


def test_cli_default_uses_the_packaged_cohort_definition() -> None:
    args = build_parser().parse_args(["build-hypertension-cohort"])

    assert args.sql is None


def test_missing_explicit_sql_override_is_rejected(tmp_path: Path) -> None:
    explicit_path = tmp_path / "sql" / "cohorts" / "hypertension.sql"

    with pytest.raises(FileNotFoundError, match="Cohort SQL file not found"):
        load_hypertension_cohort_sql(explicit_path)


def test_wheel_runtime_markers_are_available_from_source_tree() -> None:
    package_root = files("clinical_data_platform")

    assert package_root.joinpath("py.typed").is_file()
    assert package_root.joinpath("cohort_definitions", "hypertension.sql").is_file()


def _write_variable_sdist(path: Path, *, tar_mtime: int, gzip_mtime: int) -> None:
    payload = b"release-evidence\n"
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo("clinical_data_platform-1.0.0/evidence.txt")
        member.size = len(payload)
        member.mtime = tar_mtime
        member.uid = tar_mtime
        member.gid = tar_mtime
        member.uname = f"user-{tar_mtime}"
        member.gname = f"group-{tar_mtime}"
        archive.addfile(member, io.BytesIO(payload))
    with path.open("wb") as raw_file:
        with gzip.GzipFile(
            filename=path.name,
            mode="wb",
            fileobj=raw_file,
            mtime=gzip_mtime,
        ) as compressed:
            compressed.write(tar_buffer.getvalue())


def test_sdist_normalization_canonicalizes_tar_and_gzip_metadata(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    _write_variable_sdist(first, tar_mtime=1, gzip_mtime=2)
    _write_variable_sdist(second, tar_mtime=3, gzip_mtime=4)

    normalize_sdist(first, 1_700_000_000)
    normalize_sdist(second, 1_700_000_000)

    assert first.read_bytes() == second.read_bytes()


def test_release_workflow_is_tag_only_and_does_not_publish_to_pypi() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert 'tags: ["v[0-9]*.[0-9]*.[0-9]*"]' in workflow
    assert "branches:" not in workflow
    assert "pull_request:" not in workflow
    assert "contents: write" in workflow
    assert "id-token: write" not in workflow
    assert "pypi" not in workflow.lower()
    assert "gh release create" in workflow
    assert "--verify-tag" in workflow


def test_release_workflow_requires_reproducibility_and_clean_wheel_install() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    required_fragments = (
        "SOURCE_DATE_EPOCH",
        "python -m build --outdir dist-a",
        "python -m build --outdir dist-b",
        'cmp "$artifact" "dist-b/$name"',
        "python -m twine check dist-a/*",
        "python scripts/verify_distribution.py",
        'python -m venv "$RUNNER_TEMP/release-venv"',
        'cd "$RUNNER_TEMP"',
        'clinical-data" validate-contracts',
        'clinical-data-cohort" list-profiles',
        "SHA256SUMS",
        "release-manifest.json",
    )
    for fragment in required_fragments:
        assert fragment in workflow


def test_project_declares_typed_and_release_package_metadata() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]
    release_dependencies = project["optional-dependencies"]["release"]
    package_data = document["tool"]["setuptools"]["package-data"]

    assert document["build-system"]["build-backend"] == "build_backend"
    assert document["build-system"]["backend-path"] == ["."]
    assert "Development Status :: 5 - Production/Stable" in project["classifiers"]
    assert "Typing :: Typed" in project["classifiers"]
    assert any(item.startswith("build") for item in release_dependencies)
    assert any(item.startswith("twine") for item in release_dependencies)
    assert package_data["clinical_data_platform"] == ["py.typed"]
    assert package_data["clinical_data_platform.cohort_definitions"] == ["*.sql"]
