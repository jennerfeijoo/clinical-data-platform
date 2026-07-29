"""Utilities for reading source datasets."""

from __future__ import annotations

import csv
from pathlib import Path


class DatasetReadError(ValueError):
    """Raised when a source dataset cannot be interpreted safely."""


def read_csv_records(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file into a list of string dictionaries.

    UTF-8 with an optional byte-order mark is accepted because spreadsheet
    applications on Windows may add one. Malformed rows with additional
    unnamed columns are rejected instead of being silently truncated.
    """
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    if not path.is_file():
        raise DatasetReadError(f"Dataset path is not a file: {path}")

    if path.suffix.lower() != ".csv":
        raise DatasetReadError(f"Expected a CSV file, received: {path.suffix or '<none>'}")

    with path.open(mode="r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise DatasetReadError("The CSV file does not contain a header row.")

        fieldnames = [field.strip() for field in reader.fieldnames]
        if not all(fieldnames):
            raise DatasetReadError("The CSV header contains an empty column name.")

        if len(fieldnames) != len(set(fieldnames)):
            raise DatasetReadError("The CSV header contains duplicate column names.")

        records: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise DatasetReadError(
                    f"Row {row_number} contains more values than the header defines."
                )

            normalized_row = {
                key.strip(): "" if value is None else value
                for key, value in row.items()
            }
            records.append(normalized_row)

    return records
