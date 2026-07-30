from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE_FILE = ROOT / "docker-compose.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_runtime_image_declares_fixed_non_root_identity() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    required_fragments = (
        "groupadd --gid 10001 clinical",
        "--uid 10001",
        "--gid 10001",
        "--shell /usr/sbin/nologin",
        'HOME="/home/clinical"',
        'XDG_CACHE_HOME="/tmp/.cache"',
        'XDG_CONFIG_HOME="/tmp/.config"',
        "USER 10001:10001",
    )
    for fragment in required_fragments:
        assert fragment in dockerfile

    assert "USER root" not in dockerfile


def test_runtime_image_keeps_application_files_read_only() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY --chown=0:0 data/sample ./data/sample" in dockerfile
    assert "COPY --chown=0:0 sql ./sql" in dockerfile
    assert "chmod -R a-w /opt/venv /app" in dockerfile
    assert "/app/data/raw" in dockerfile
    assert "/app/data/processed" in dockerfile
    assert "/app/data/analytics" in dockerfile
    assert "find /usr /bin /sbin -xdev -type f -perm /6000" in dockerfile


def test_compose_demo_applies_runtime_restrictions() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    required_fragments = (
        'user: "10001:10001"',
        "read_only: true",
        "cap_drop:",
        "- ALL",
        "no-new-privileges:true",
        "pids_limit: 256",
        "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
        "app_raw:/app/data/raw",
        "app_processed:/app/data/processed",
        "app_analytics:/app/data/analytics",
    )
    for fragment in required_fragments:
        assert fragment in compose

    assert "./data:/app/data" not in compose


def test_ci_executes_real_commands_under_hardened_runtime() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    required_fragments = (
        "Verify hardened container identity and filesystem",
        "CONFIGURED_USER",
        'test "$CONFIGURED_USER" = "10001:10001"',
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges:true",
        "--pids-limit 256",
        "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
        "Validate PostgreSQL from hardened container",
        "Smoke-test container raw capture as UID 10001",
        'test "$(stat -c \'%u\' "$RECEIPT")" = "10001"',
    )
    for fragment in required_fragments:
        assert fragment in workflow
