#!/usr/bin/env python3
"""Normalize a gzip-compressed source distribution to a fixed timestamp."""

from __future__ import annotations

import argparse
import gzip
import os
import tempfile
from pathlib import Path


class SdistNormalizationError(RuntimeError):
    """Raised when an sdist cannot be normalized safely."""


def normalize_sdist(path: Path, source_date_epoch: int) -> None:
    """Rewrite one .tar.gz with a deterministic gzip header and payload."""
    if source_date_epoch < 0:
        raise SdistNormalizationError("SOURCE_DATE_EPOCH cannot be negative.")
    if not path.is_file() or not path.name.endswith(".tar.gz"):
        raise SdistNormalizationError(f"Expected an existing .tar.gz file: {path}")

    try:
        tar_payload = gzip.decompress(path.read_bytes())
    except (OSError, EOFError) as error:
        raise SdistNormalizationError(f"Invalid gzip source distribution: {path}") from error

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdists", type=Path, nargs="+")
    parser.add_argument("--source-date-epoch", type=int, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        for path in args.sdists:
            normalize_sdist(path, args.source_date_epoch)
    except SdistNormalizationError as error:
        raise SystemExit(f"Sdist normalization failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
