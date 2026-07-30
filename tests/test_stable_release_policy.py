from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stable_release_metadata_and_boundaries() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    classifiers = set(project["classifiers"])

    assert project["version"] == "1.0.0"
    assert "Development Status :: 5 - Production/Stable" in classifiers
    assert "Development Status :: 4 - Beta" not in classifiers

    readiness = (ROOT / "docs" / "stable-release-readiness.md").read_text(
        encoding="utf-8"
    )
    assert "synthetic clinical data" in readiness
    assert "No `V009` migration" in readiness
    assert "PyPI publication remains disabled" in readiness
    assert "does not establish" in readiness

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "stable software release `1.0.0`" in readme
    assert "not a claim of healthcare production readiness" in readme


def test_release_workflow_remains_tag_only_and_has_no_pypi_publication() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert 'tags: ["v[0-9]*.[0-9]*.[0-9]*"]' in workflow
    assert "gh release create" in workflow
    assert "pypi" not in workflow.lower()
    assert "id-token: write" not in workflow


def test_stable_version_is_synchronized_in_public_sources() -> None:
    files = {
        "package": ROOT / "src" / "clinical_data_platform" / "__init__.py",
        "changelog": ROOT / "CHANGELOG.md",
        "citation": ROOT / "CITATION.cff",
        "readme": ROOT / "README.md",
        "package test": ROOT / "tests" / "test_package.py",
        "ci": ROOT / ".github" / "workflows" / "ci.yml",
    }

    for label, path in files.items():
        text = path.read_text(encoding="utf-8")
        assert "1.0.0" in text, f"{label} does not identify the stable version"

    changelog = files["changelog"].read_text(encoding="utf-8")
    assert re.search(r"^## 1\.0\.0$", changelog, flags=re.MULTILINE)
