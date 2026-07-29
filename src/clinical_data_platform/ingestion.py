"""Utilities for reading source datasets."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


class DatasetReadError(ValueError):
    """Raised when a source dataset cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class CsvInspection:
    """Header and row-count evidence collected without retaining all records."""

    columns: tuple[str, ...]
    row_count: int


def _validate_csv_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    if not path.is_file():
        raise DatasetReadError(f"Dataset path is not a file: {path}")
    if path.suffix.lower() != ".csv":
        raise DatasetReadError(f"Expected a CSV file, received: {path.suffix or '<none>'}")


def _validated_columns(fieldnames: list[str] | None) -> tuple[str, ...]:
    if fieldnames is None:
        raise DatasetReadError("The CSV file does not contain a header row.")
    columns = tuple(field.strip() for field in fieldnames)
    if not all(columns):
        raise DatasetReadError("The CSV header contains an empty column name.")
    if len(columns) != len(set(columns)):
        raise DatasetReadError("The CSV header contains duplicate column names.")
    return columns


def _normalized_row(row_number: int, row: dict[str | None, str | None]) -> dict[str, str]:
    if None in row:
        raise DatasetReadError(
            f"Row {row_number} contains more values than the header defines."
        )
    return {
        key.strip(): "" if value is None else value
        for key, value in row.items()
        if key is not None
    }


def iter_csv_records(path: Path) -> Iterator[dict[str, str]]:
    """Yield validated UTF-8 CSV records without retaining the complete file."""
    _validate_csv_path(path)
    with path.open(mode="r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        _validated_columns(reader.fieldnames)
        for row_number, row in enumerate(reader, start=2):
            yield _normalized_row(row_number, row)


def inspect_csv_records(path: Path) -> CsvInspection:
    """Validate CSV structure and count records with bounded memory use."""
    _validate_csv_path(path)
    with path.open(mode="r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = _validated_columns(reader.fieldnames)
        row_count = 0
        for row_number, row in enumerate(reader, start=2):
            _normalized_row(row_number, row)
            row_count += 1
    return CsvInspection(columns=columns, row_count=row_count)


def read_csv_records(path: Path) -> list[dict[str, str]]:
    """Read a validated UTF-8 CSV file into a list of string dictionaries.

    Use :func:`iter_csv_records` for persistence paths that must remain bounded
    in memory. This list-returning helper remains appropriate for validation,
    where the contract engine currently evaluates the complete dataset.
    """
    return list(iter_csv_records(path))
