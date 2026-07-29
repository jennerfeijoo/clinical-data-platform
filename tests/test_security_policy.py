from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRECTORY = ROOT / ".github" / "workflows"
FULL_SHA_ACTION = re.compile(r"^\s*uses:\s+[^\s@]+@([0-9a-f]{40})(?:\s+#.*)?$")


def test_all_github_actions_are_pinned_to_full_commit_shas() -> None:
    action_lines: list[tuple[Path, int, str]] = []

    for workflow_path in sorted(WORKFLOW_DIRECTORY.glob("*.yml")):
        for line_number, line in enumerate(
            workflow_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "uses:" in line:
                action_lines.append((workflow_path, line_number, line))

    assert action_lines
    invalid = [
        f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}"
        for path, line_number, line in action_lines
        if FULL_SHA_ACTION.match(line) is None
    ]
    assert invalid == []


def test_security_optional_dependencies_and_build_tool_floor_are_declared() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    security_dependencies = document["project"]["optional-dependencies"]["security"]
    assert any(dependency.startswith("bandit") for dependency in security_dependencies)
    assert any(dependency.startswith("pip-audit") for dependency in security_dependencies)
    assert document["build-system"]["requires"] == ["setuptools>=83"]
    assert document["tool"]["bandit"]["exclude_dirs"] == ["tests"]


def test_security_workflow_contains_independent_required_scanners() -> None:
    workflow = (WORKFLOW_DIRECTORY / "security.yml").read_text(encoding="utf-8")

    required_controls = (
        "python -m pip_audit",
        "python -m bandit",
        "security/bandit-baseline.json",
        "github/codeql-action/init@",
        "github/codeql-action/analyze@",
        "aquasecurity/trivy-action@",
        "severity: HIGH,CRITICAL",
        'exit-code: "1"',
        '"setuptools>=83"',
    )
    for control in required_controls:
        assert control in workflow


def test_bandit_baseline_contains_only_two_reviewed_constant_sql_findings() -> None:
    baseline = json.loads(
        (ROOT / "security" / "bandit-baseline.json").read_text(encoding="utf-8")
    )
    findings = baseline["results"]

    assert len(findings) == 2
    assert {
        (finding["filename"], finding["test_id"], finding["issue_severity"])
        for finding in findings
    } == {
        ("src/clinical_data_platform/run_audit.py", "B608", "MEDIUM"),
        ("src/clinical_data_platform/synthea_cohorts.py", "B608", "MEDIUM"),
    }


def test_container_runtime_excludes_global_build_and_scan_only_packages() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim AS builder" in dockerfile
    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "COPY --from=builder /opt/venv /opt/venv" in dockerfile
    assert 'PATH="/opt/venv/bin:$PATH"' in dockerfile
    for package in ("pip", "setuptools", "wheel", "msgpack", "jaraco.context"):
        assert package in dockerfile


def test_dependabot_covers_python_actions_and_docker() -> None:
    configuration = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    ecosystems = set(re.findall(r"package-ecosystem:\s+([\w-]+)", configuration))

    assert ecosystems == {"pip", "github-actions", "docker"}
