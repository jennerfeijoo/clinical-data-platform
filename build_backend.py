"""Setuptools build backend with deterministic gzip normalization for sdists."""

from __future__ import annotations

import gzip
import os
import tempfile
from pathlib import Path
from typing import Any

from setuptools import build_meta as _setuptools_backend


def normalize_sdist(path: Path, source_date_epoch: int) -> None:
    """Rewrite one .tar.gz with a deterministic gzip header and payload."""
    if source_date_epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH cannot be negative.")
    if not path.is_file() or not path.name.endswith(".tar.gz"):
        raise ValueError(f"Expected an existing .tar.gz file: {path}")

    try:
        tar_payload = gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as error:
        raise ValueError(f"Invalid gzip source distribution: {path}") from error

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
                gzip_file.write(tar_payload)
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
    """Build an sdist and normalize its gzip timestamp when an epoch is supplied."""
    filename = _setuptools_backend.build_sdist(sdist_directory, config_settings)
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is not None:
        try:
            epoch = int(source_date_epoch)
        except ValueError as error:
            raise ValueError("SOURCE_DATE_EPOCH must be an integer.") from error
        normalize_sdist(Path(sdist_directory) / filename, epoch)
    return filename


build_wheel = _setuptools_backend.build_wheel
build_editable = _setuptools_backend.build_editable
get_requires_for_build_wheel = _setuptools_backend.get_requires_for_build_wheel
get_requires_for_build_sdist = _setuptools_backend.get_requires_for_build_sdist
get_requires_for_build_editable = _setuptools_backend.get_requires_for_build_editable
prepare_metadata_for_build_wheel = _setuptools_backend.prepare_metadata_for_build_wheel
prepare_metadata_for_build_editable = _setuptools_backend.prepare_metadata_for_build_editable
