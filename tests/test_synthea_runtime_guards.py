from __future__ import annotations

from pathlib import Path

import pytest

from clinical_data_platform import synthea


def test_prepare_checkout_replaces_and_clones_before_verification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = synthea.load_synthea_profile()
    checkout = tmp_path / "upstream" / "synthea"
    checkout.mkdir(parents=True)
    (checkout / "stale.txt").write_text("stale", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def run_command(command: tuple[str, ...], **_kwargs: object) -> str:
        commands.append(command)
        checkout.mkdir(parents=True, exist_ok=True)
        (checkout / ".git").mkdir(exist_ok=True)
        return ""

    expected = synthea.SyntheaCheckout(
        path=checkout,
        commit_sha="commit-sha",
        exact_ref="v4.0.0",
    )
    monkeypatch.setattr(synthea, "_run_command", run_command)
    monkeypatch.setattr(
        synthea,
        "_verify_checkout",
        lambda selected, path: expected
        if selected is profile and path == checkout
        else pytest.fail("Unexpected checkout verification arguments"),
    )

    result = synthea.prepare_synthea_checkout(profile, checkout, replace=True)

    assert result == expected
    assert not (checkout / "stale.txt").exists()
    assert commands
    assert commands[0][:4] == ("git", "clone", "--depth", "1")
    assert commands[0][-1] == str(checkout)


def test_java_version_accepts_supported_formats_and_rejects_invalid_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        synthea,
        "_run_command",
        lambda *_args, **_kwargs: 'openjdk version "21.0.2" 2024-01-16',
    )
    assert synthea._java_version(17).startswith("openjdk version")

    monkeypatch.setattr(
        synthea,
        "_run_command",
        lambda *_args, **_kwargs: "openjdk 17 2021-09-14",
    )
    assert synthea._java_version(17) == "openjdk 17 2021-09-14"

    monkeypatch.setattr(synthea, "_run_command", lambda *_args, **_kwargs: "unknown")
    with pytest.raises(synthea.SyntheaGenerationError, match="Could not parse"):
        synthea._java_version(17)

    monkeypatch.setattr(
        synthea,
        "_run_command",
        lambda *_args, **_kwargs: 'openjdk version "11.0.20"',
    )
    with pytest.raises(synthea.SyntheaGenerationError, match="requires Java 17"):
        synthea._java_version(17)
