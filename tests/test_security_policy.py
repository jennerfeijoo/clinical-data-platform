from __future__ import annotations

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


def test_security_optional_dependencies_and_bandit_policy_are_declared() -> None:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    security_dependencies = document["project"]["optional-dependencies"]["security"]
    assert any(dependency.startswith("bandit") for dependency in security_dependencies)
    assert any(dependency.startswith("pip-audit") for dependency in security_dependencies)
    assert document["tool"]["bandit"]["exclude_dirs"] == ["tests"]


def test_security_workflow_contains_independent_required_scanners() -> None:
    workflow = (WORKFLOW_DIRECTORY / "security.yml").read_text(encoding="utf-8")

    required_controls = (
        "actions/dependency-review-action@",
        "python -m pip_audit",
        "python -m bandit",
        "github/codeql-action/init@",
        "github/codeql-action/analyze@",
        "aquasecurity/trivy-action@",
        "severity: HIGH,CRITICAL",
        'exit-code: "1"',
    )
    for control in required_controls:
        assert control in workflow


def test_dependabot_covers_python_actions_and_docker() -> None:
    configuration = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    ecosystems = set(re.findall(r"package-ecosystem:\s+([\w-]+)", configuration))

    assert ecosystems == {"pip", "github-actions", "docker"}
