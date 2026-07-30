#!/usr/bin/env python3
"""Normalize gzip-compressed source distributions to a fixed timestamp."""

from __future__ import annotations

import argparse
from pathlib import Path

from build_backend import normalize_sdist


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
    except ValueError as error:
        raise SystemExit(f"Sdist normalization failed: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
