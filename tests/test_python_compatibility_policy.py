from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_VERSIONS = ("3.11", "3.12", "3.13", "3.14")
PYTHON_CLASSIFIER_PREFIX = "Programming Language :: Python :: 3."


def test_package_metadata_declares_only_tested_python_versions() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = document["project"]

    assert project["requires-python"] == ">=3.11,<3.15"
    classifiers = set(project["classifiers"])
    declared_version_classifiers = {
        classifier
        for classifier in classifiers
        if classifier.startswith(PYTHON_CLASSIFIER_PREFIX)
    }
    expected_version_classifiers = {
        f"Programming Language :: Python :: {version}" for version in SUPPORTED_VERSIONS
    }

    assert "Programming Language :: Python :: 3" in classifiers
    assert declared_version_classifiers == expected_version_classifiers


def test_ci_matrix_matches_package_support_policy() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert 'python-version: "3.11"' in workflow
    assert 'python-version: ["3.12", "3.13", "3.14"]' in workflow
    assert "fail-fast: false" in workflow
    assert "python -m pip check" in workflow
    assert "python -m pytest" in workflow
    assert "actions/setup-python@v6" in workflow


def test_benchmark_stays_on_reference_python() -> None:
    workflow = (ROOT / ".github" / "workflows" / "benchmark.yml").read_text(
        encoding="utf-8"
    )

    assert "Python 3.11 reference" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "actions/setup-python@v6" in workflow
