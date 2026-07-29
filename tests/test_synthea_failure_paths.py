from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinical_data_platform import synthea

VALID_PROFILE = """[profile]
schema_version = "1.0.0"
name = "synthea-us-small-v1"
source_system = "SYNTHEA_4_0_0"

[upstream]
repository = "https://github.com/synthetichealth/synthea.git"
ref = "v4.0.0"
version = "4.0.0"
license = "Apache-2.0"
minimum_java_version = 17

[generation]
population_size = 100
random_seed = 20260729
clinician_seed = 20260730
reference_date = "2026-07-29"
state = "Massachusetts"
city = ""
thread_pool_size = 1
years_of_history = 0

[export]
included_files = [
  "patients.csv",
  "encounters.csv",
  "conditions.csv",
  "observations.csv",
  "medications.csv",
  "procedures.csv",
]
"""


def _write_profile(tmp_path: Path, content: str | bytes) -> Path:
    path = tmp_path / "profile.toml"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def test_profile_helpers_reject_wrong_shapes() -> None:
    with pytest.raises(synthea.SyntheaProfileError, match=r"table \[upstream\]"):
        synthea._require_table({}, "upstream")
    with pytest.raises(synthea.SyntheaProfileError, match="must be a string"):
        synthea._require_string({"name": 1}, "name")
    with pytest.raises(synthea.SyntheaProfileError, match="must be a string"):
        synthea._require_string({"name": "   "}, "name")
    assert synthea._require_string({"city": "   "}, "city", allow_empty=True) == ""
    with pytest.raises(synthea.SyntheaProfileError, match="must be an integer"):
        synthea._require_integer({"seed": True}, "seed")
    with pytest.raises(synthea.SyntheaProfileError, match="non-empty list"):
        synthea._require_string_list({"files": []}, "files")
    with pytest.raises(synthea.SyntheaProfileError, match="invalid item"):
        synthea._require_string_list({"files": ["patients.csv", ""]}, "files")


def test_profile_rejects_invalid_encoding_and_toml(tmp_path: Path) -> None:
    with pytest.raises(synthea.SyntheaProfileError, match="valid UTF-8 TOML"):
        synthea.load_synthea_profile(_write_profile(tmp_path, b"\xff"))
    with pytest.raises(synthea.SyntheaProfileError, match="valid UTF-8 TOML"):
        synthea.load_synthea_profile(_write_profile(tmp_path, "[profile\n"))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('schema_version = "1.0.0"', 'schema_version = "2.0.0"', "Unsupported"),
        ('reference_date = "2026-07-29"', 'reference_date = "29-07-2026"', "YYYY-MM-DD"),
        ('population_size = 100', 'population_size = 0', "must be positive"),
        ('random_seed = 20260729', 'random_seed = -1', "non-negative"),
        ('minimum_java_version = 17', 'minimum_java_version = 16', "below 17"),
        ('thread_pool_size = 1', 'thread_pool_size = 2', "must be 1"),
        ('years_of_history = 0', 'years_of_history = 1', "must be 0"),
    ],
)
def test_profile_rejects_invalid_governance_values(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    path = _write_profile(tmp_path, VALID_PROFILE.replace(old, new))
    with pytest.raises(synthea.SyntheaProfileError, match=message):
        synthea.load_synthea_profile(path)


def test_profile_rejects_wrong_export_order_and_missing_table(tmp_path: Path) -> None:
    wrong_order = VALID_PROFILE.replace(
        '  "patients.csv",\n  "encounters.csv",',
        '  "encounters.csv",\n  "patients.csv",',
    )
    with pytest.raises(synthea.SyntheaProfileError, match="canonical order"):
        synthea.load_synthea_profile(_write_profile(tmp_path, wrong_order))

    without_export = VALID_PROFILE.split("[export]", maxsplit=1)[0]
    with pytest.raises(synthea.SyntheaProfileError, match=r"table \[export\]"):
        synthea.load_synthea_profile(_write_profile(tmp_path, without_export))


def test_json_and_csv_readers_reject_invalid_artifacts(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="JSON manifest not found"):
        synthea._read_json_object(missing)

    list_document = tmp_path / "list.json"
    list_document.write_text("[]", encoding="utf-8")
    with pytest.raises(synthea.SyntheaManifestError, match="JSON object"):
        synthea._read_json_object(list_document)

    with pytest.raises(FileNotFoundError, match="CSV file not found"):
        synthea._read_csv_records(tmp_path / "missing.csv", ("Id",))

    wrong_header = tmp_path / "patients.csv"
    wrong_header.write_text("WRONG\nvalue\n", encoding="utf-8")
    with pytest.raises(synthea.SyntheaAdapterError, match="Unexpected header"):
        synthea._read_csv_records(wrong_header, ("Id",))

    with pytest.raises(FileNotFoundError, match="CSV directory not found"):
        synthea.inspect_synthea_csv_directory(tmp_path / "not-a-directory")


def test_build_command_includes_optional_city(tmp_path: Path) -> None:
    profile = synthea.load_synthea_profile()
    command_without_city = synthea.build_synthea_command(
        profile,
        tmp_path / "checkout",
        tmp_path / "output",
        windows=False,
    )
    assert command_without_city[-1] == "Massachusetts"
    assert command_without_city[0].endswith("run_synthea")

    command_with_city = synthea.build_synthea_command(
        replace(profile, city="Boston"),
        tmp_path / "checkout",
        tmp_path / "output",
        windows=True,
    )
    assert command_with_city[-2:] == ("Massachusetts", "Boston")
    assert command_with_city[0].endswith("run_synthea.bat")


def test_run_command_wraps_missing_and_failed_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("missing")

    monkeypatch.setattr(synthea.subprocess, "run", missing)
    with pytest.raises(synthea.SyntheaGenerationError, match="Executable not found"):
        synthea._run_command(("missing-command",))

    def failed(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(7, ["bad"], stderr="generation failed")

    monkeypatch.setattr(synthea.subprocess, "run", failed)
    with pytest.raises(synthea.SyntheaGenerationError, match="exit code 7"):
        synthea._run_command(("bad-command",))

    monkeypatch.setattr(
        synthea.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="", stderr="diagnostic\n"),
    )
    assert synthea._run_command(("ok",)) == "diagnostic"


def test_checkout_verification_rejects_invalid_worktrees(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = synthea.load_synthea_profile()
    checkout = tmp_path / "synthea"
    checkout.mkdir()
    with pytest.raises(synthea.SyntheaGenerationError, match="not a Git worktree"):
        synthea._verify_checkout(profile, checkout)

    (checkout / ".git").mkdir()
    responses = iter(("commit-sha", "v3.0.0"))
    monkeypatch.setattr(synthea, "_run_command", lambda *_args, **_kwargs: next(responses))
    with pytest.raises(synthea.SyntheaGenerationError, match="expected 'v4.0.0'"):
        synthea._verify_checkout(profile, checkout)

    dirty_responses = iter(("commit-sha", "v4.0.0", " M modified-file"))
    monkeypatch.setattr(
        synthea,
        "_run_command",
        lambda *_args, **_kwargs: next(dirty_responses),
    )
    with pytest.raises(synthea.SyntheaGenerationError, match="uncommitted changes"):
        synthea._verify_checkout(profile, checkout)

    clean_responses = iter(("commit-sha", "v4.0.0", ""))
    monkeypatch.setattr(
        synthea,
        "_run_command",
        lambda *_args, **_kwargs: next(clean_responses),
    )
    verified = synthea._verify_checkout(profile, checkout)
    assert verified.commit_sha == "commit-sha"
    assert verified.exact_ref == "v4.0.0"
