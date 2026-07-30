"""Setuptools build backend with deterministic source-distribution normalization."""

from __future__ import annotations

import copy
import gzip
import io
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any


def _setuptools_backend() -> Any:
    from setuptools import build_meta

    return build_meta


def _canonical_tar_payload(tar_payload: bytes, source_date_epoch: int) -> bytes:
    output = io.BytesIO()
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_payload), mode="r:") as source:
            members = sorted(source.getmembers(), key=lambda member: member.name)
            with tarfile.open(
                fileobj=output,
                mode="w",
                format=tarfile.PAX_FORMAT,
            ) as target:
                for member in members:
                    canonical = copy.copy(member)
                    canonical.mtime = source_date_epoch
                    canonical.uid = 0
                    canonical.gid = 0
                    canonical.uname = ""
                    canonical.gname = ""
                    canonical.pax_headers = {}
                    content = source.extractfile(member) if member.isfile() else None
                    if member.isfile() and content is None:
                        raise ValueError(f"Could not read TAR member: {member.name}")
                    target.addfile(canonical, content)
    except tarfile.TarError as error:
        raise ValueError("Invalid TAR payload in source distribution.") from error
    return output.getvalue()


def normalize_sdist(path: Path, source_date_epoch: int) -> None:
    """Rewrite one .tar.gz with deterministic TAR and gzip metadata."""
    if source_date_epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH cannot be negative.")
    if not path.is_file() or not path.name.endswith(".tar.gz"):
        raise ValueError(f"Expected an existing .tar.gz file: {path}")

    try:
        tar_payload = gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as error:
        raise ValueError(f"Invalid gzip source distribution: {path}") from error
    canonical_payload = _canonical_tar_payload(tar_payload, source_date_epoch)

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as raw_file:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=9,
                fileobj=raw_file,
                mtime=source_date_epoch,
            ) as gzip_file:
                gzip_file.write(canonical_payload)
            raw_file.flush()
            os.fsync(raw_file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """Build and canonically normalize an sdist when an epoch is supplied."""
    filename = _setuptools_backend().build_sdist(sdist_directory, config_settings)
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is not None:
        try:
            epoch = int(source_date_epoch)
        except ValueError as error:
            raise ValueError("SOURCE_DATE_EPOCH must be an integer.") from error
        normalize_sdist(Path(sdist_directory) / filename, epoch)
    return filename


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _setuptools_backend().build_wheel(
        wheel_directory,
        config_settings,
        metadata_directory,
    )


def build_editable(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    return _setuptools_backend().build_editable(
        wheel_directory,
        config_settings,
        metadata_directory,
    )


def get_requires_for_build_wheel(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    return list(_setuptools_backend().get_requires_for_build_wheel(config_settings))


def get_requires_for_build_sdist(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    return list(_setuptools_backend().get_requires_for_build_sdist(config_settings))


def get_requires_for_build_editable(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    return list(_setuptools_backend().get_requires_for_build_editable(config_settings))


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    return _setuptools_backend().prepare_metadata_for_build_wheel(
        metadata_directory,
        config_settings,
    )


def prepare_metadata_for_build_editable(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    return _setuptools_backend().prepare_metadata_for_build_editable(
        metadata_directory,
        config_settings,
    )
