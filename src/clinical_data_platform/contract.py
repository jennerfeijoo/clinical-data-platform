"""Load, validate, and execute versioned dataset contracts."""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any, Final, cast

from clinical_data_platform.models import ClinicalRecord, ValidationError, ValidationResult

CONTRACT_PACKAGE: Final = "clinical_data_platform.contracts"
SEMANTIC_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SUPPORTED_COLUMN_TYPES = frozenset({"string", "date", "datetime", "number"})


class ContractDefinitionError(ValueError):
    """Raised when a contract file is malformed or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ColumnContract:
    """Declarative rules for one source column."""

    name: str
    data_type: str
    required: bool
    unique: bool
    allowed_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrderRule:
    """Require one temporal field to be less than or equal to another."""

    earlier_field: str
    later_field: str


@dataclass(frozen=True, slots=True)
class MeasurementProfile:
    """Unit and plausible range for one measurement code."""

    code: str
    unit: str
    minimum: float
    maximum: float


@dataclass(frozen=True, slots=True)
class MeasurementRule:
    """Conditional measurement validation configured by the contract."""

    code_field: str
    value_field: str
    unit_field: str
    profiles: Mapping[str, MeasurementProfile]


@dataclass(frozen=True, slots=True)
class DatasetContract:
    """Parsed, validated, and executable dataset contract."""

    name: str
    version: str
    primary_key: str
    patient_id_column: str
    allow_extra_columns: bool
    columns: tuple[ColumnContract, ...]
    not_future_fields: tuple[str, ...]
    order_rules: tuple[OrderRule, ...]
    measurement_rule: MeasurementRule | None
    resource_path: str
    sha256: str

    @property
    def column_names(self) -> tuple[str, ...]:
        """Return source columns in their declared output order."""
        return tuple(column.name for column in self.columns)


@dataclass(frozen=True, slots=True)
class ContractManifest:
    """Mapping from dataset names to their active contract resources."""

    schema_version: str
    contracts: Mapping[str, str]


def _mapping(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractDefinitionError(f"{context} must be a TOML table.")
    return cast(dict[str, Any], value)


def _list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractDefinitionError(f"{context} must be a TOML array.")
    return cast(list[Any], value)


def _non_empty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractDefinitionError(f"{context} must be a non-empty string.")
    return value.strip()


def _boolean(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise ContractDefinitionError(f"{context} must be a boolean.")
    return value


def _number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractDefinitionError(f"{context} must be numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise ContractDefinitionError(f"{context} must be finite.")
    return result


def _resource_bytes(relative_path: str) -> bytes:
    resource = files(CONTRACT_PACKAGE).joinpath(relative_path)
    if not resource.is_file():
        raise ContractDefinitionError(f"Contract resource not found: {relative_path}")
    return resource.read_bytes()


@lru_cache(maxsize=1)
def load_contract_manifest() -> ContractManifest:
    """Load the manifest that selects the active version of every contract."""
    raw = tomllib.loads(_resource_bytes("manifest.toml").decode("utf-8"))
    schema_version = _non_empty_string(raw.get("schema_version"), "schema_version")
    if SEMANTIC_VERSION.fullmatch(schema_version) is None:
        raise ContractDefinitionError("schema_version must follow semantic versioning.")

    contract_table = _mapping(raw.get("contracts"), "contracts")
    contracts: dict[str, str] = {}
    for dataset, path_value in contract_table.items():
        if not isinstance(dataset, str) or not dataset.strip():
            raise ContractDefinitionError("Contract manifest keys must be dataset names.")
        contracts[dataset] = _non_empty_string(path_value, f"contracts.{dataset}")

    if not contracts:
        raise ContractDefinitionError("The contract manifest cannot be empty.")
    return ContractManifest(schema_version=schema_version, contracts=contracts)


def _parse_column(raw_value: object, position: int) -> ColumnContract:
    raw = _mapping(raw_value, f"columns[{position}]")
    name = _non_empty_string(raw.get("name"), f"columns[{position}].name")
    data_type = _non_empty_string(raw.get("type"), f"columns[{position}].type")
    if data_type not in SUPPORTED_COLUMN_TYPES:
        supported = ", ".join(sorted(SUPPORTED_COLUMN_TYPES))
        raise ContractDefinitionError(
            f"Column {name!r} uses unsupported type {data_type!r}; expected: {supported}."
        )

    allowed_raw = raw.get("allowed_values", [])
    allowed_values = tuple(
        _non_empty_string(value, f"columns[{position}].allowed_values")
        for value in _list(allowed_raw, f"columns[{position}].allowed_values")
    )
    if len(allowed_values) != len(set(allowed_values)):
        raise ContractDefinitionError(f"Column {name!r} contains duplicate allowed values.")

    return ColumnContract(
        name=name,
        data_type=data_type,
        required=_boolean(raw.get("required", False), f"columns[{position}].required"),
        unique=_boolean(raw.get("unique", False), f"columns[{position}].unique"),
        allowed_values=allowed_values,
    )


def _parse_order_rules(raw_value: object) -> tuple[OrderRule, ...]:
    rules: list[OrderRule] = []
    for position, value in enumerate(_list(raw_value, "order_rules")):
        raw = _mapping(value, f"order_rules[{position}]")
        rules.append(
            OrderRule(
                earlier_field=_non_empty_string(
                    raw.get("earlier_field"), f"order_rules[{position}].earlier_field"
                ),
                later_field=_non_empty_string(
                    raw.get("later_field"), f"order_rules[{position}].later_field"
                ),
            )
        )
    return tuple(rules)


def _parse_measurement_rule(raw_value: object) -> MeasurementRule | None:
    if raw_value is None:
        return None
    raw = _mapping(raw_value, "measurement")
    profiles: dict[str, MeasurementProfile] = {}
    for position, profile_value in enumerate(_list(raw.get("profiles", []), "measurement.profiles")):
        profile = _mapping(profile_value, f"measurement.profiles[{position}]")
        code = _non_empty_string(profile.get("code"), f"measurement.profiles[{position}].code")
        minimum = _number(profile.get("minimum"), f"measurement.profiles[{position}].minimum")
        maximum = _number(profile.get("maximum"), f"measurement.profiles[{position}].maximum")
        if maximum < minimum:
            raise ContractDefinitionError(
                f"Measurement profile {code!r} has maximum below minimum."
            )
        if code in profiles:
            raise ContractDefinitionError(f"Duplicate measurement profile: {code}")
        profiles[code] = MeasurementProfile(
            code=code,
            unit=_non_empty_string(
                profile.get("unit"), f"measurement.profiles[{position}].unit"
            ),
            minimum=minimum,
            maximum=maximum,
        )

    if not profiles:
        raise ContractDefinitionError("A measurement rule requires at least one profile.")
    return MeasurementRule(
        code_field=_non_empty_string(raw.get("code_field"), "measurement.code_field"),
        value_field=_non_empty_string(raw.get("value_field"), "measurement.value_field"),
        unit_field=_non_empty_string(raw.get("unit_field"), "measurement.unit_field"),
        profiles=profiles,
    )


def _validate_contract_consistency(contract: DatasetContract) -> None:
    column_names = contract.column_names
    if len(column_names) != len(set(column_names)):
        raise ContractDefinitionError(f"Contract {contract.name!r} contains duplicate columns.")
    if contract.primary_key not in column_names:
        raise ContractDefinitionError("primary_key must reference a declared column.")
    primary_key = next(column for column in contract.columns if column.name == contract.primary_key)
    if not primary_key.required or not primary_key.unique:
        raise ContractDefinitionError("primary_key must be required and unique.")
    if contract.patient_id_column not in column_names:
        raise ContractDefinitionError("patient_id_column must reference a declared column.")

    for field in contract.not_future_fields:
        if field not in column_names:
            raise ContractDefinitionError(f"not_future_fields references unknown column: {field}")
        data_type = next(column.data_type for column in contract.columns if column.name == field)
        if data_type not in {"date", "datetime"}:
            raise ContractDefinitionError(f"not_future field {field!r} must be date or datetime.")

    for rule in contract.order_rules:
        if rule.earlier_field not in column_names or rule.later_field not in column_names:
            raise ContractDefinitionError("order_rules must reference declared columns.")

    measurement = contract.measurement_rule
    if measurement is not None:
        required_fields = {measurement.code_field, measurement.value_field, measurement.unit_field}
        if not required_fields.issubset(column_names):
            raise ContractDefinitionError("measurement fields must reference declared columns.")
        code_column = next(
            column for column in contract.columns if column.name == measurement.code_field
        )
        profile_codes = set(measurement.profiles)
        if code_column.allowed_values and set(code_column.allowed_values) != profile_codes:
            raise ContractDefinitionError(
                "measurement profile codes must match the code column allowed_values."
            )


@lru_cache(maxsize=None)
def load_contract_by_resource(relative_path: str) -> DatasetContract:
    """Load and validate one versioned contract resource."""
    content = _resource_bytes(relative_path)
    raw = tomllib.loads(content.decode("utf-8"))
    dataset = _mapping(raw.get("dataset"), "dataset")
    name = _non_empty_string(dataset.get("name"), "dataset.name")
    version = _non_empty_string(dataset.get("version"), "dataset.version")
    if SEMANTIC_VERSION.fullmatch(version) is None:
        raise ContractDefinitionError("dataset.version must follow semantic versioning.")

    columns = tuple(
        _parse_column(value, position)
        for position, value in enumerate(_list(raw.get("columns"), "columns"))
    )
    if not columns:
        raise ContractDefinitionError("A dataset contract requires at least one column.")

    not_future_fields = tuple(
        _non_empty_string(value, "not_future_fields")
        for value in _list(raw.get("not_future_fields", []), "not_future_fields")
    )
    contract = DatasetContract(
        name=name,
        version=version,
        primary_key=_non_empty_string(dataset.get("primary_key"), "dataset.primary_key"),
        patient_id_column=_non_empty_string(
            dataset.get("patient_id_column"), "dataset.patient_id_column"
        ),
        allow_extra_columns=_boolean(
            dataset.get("allow_extra_columns", False), "dataset.allow_extra_columns"
        ),
        columns=columns,
        not_future_fields=not_future_fields,
        order_rules=_parse_order_rules(raw.get("order_rules", [])),
        measurement_rule=_parse_measurement_rule(raw.get("measurement")),
        resource_path=relative_path,
        sha256=hashlib.sha256(content).hexdigest(),
    )
    _validate_contract_consistency(contract)
    return contract


def contract_names() -> tuple[str, ...]:
    """Return datasets with an active contract in deterministic manifest order."""
    return tuple(load_contract_manifest().contracts)


def load_contract(dataset: str) -> DatasetContract:
    """Load the active contract version selected for a dataset."""
    manifest = load_contract_manifest()
    try:
        relative_path = manifest.contracts[dataset]
    except KeyError as exc:
        supported = ", ".join(contract_names())
        raise ValueError(
            f"Unsupported dataset {dataset!r}; expected one of: {supported}"
        ) from exc
    contract = load_contract_by_resource(relative_path)
    if contract.name != dataset:
        raise ContractDefinitionError(
            f"Manifest dataset {dataset!r} points to contract {contract.name!r}."
        )
    return contract


def validate_all_contracts() -> tuple[DatasetContract, ...]:
    """Load every active contract, failing on the first invalid definition."""
    return tuple(load_contract(dataset) for dataset in contract_names())


def _parse_typed_value(column: ColumnContract, value: str) -> object:
    if column.data_type == "string":
        return value
    if column.data_type == "date":
        return datetime.strptime(value, "%Y-%m-%d").date()
    if column.data_type == "datetime":
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone offset is required")
        return parsed
    if column.data_type == "number":
        parsed_number = float(value)
        if not math.isfinite(parsed_number):
            raise ValueError("number must be finite")
        return parsed_number
    raise AssertionError(f"Unhandled column type: {column.data_type}")


def _type_error(column: ColumnContract) -> tuple[str, str]:
    if column.data_type == "date":
        return "iso_date", f"{column.name} must use YYYY-MM-DD format"
    if column.data_type == "datetime":
        return "iso_datetime", f"{column.name} must be an ISO 8601 datetime with timezone"
    if column.data_type == "number":
        return "numeric", f"{column.name} must be a finite number"
    return "type", f"{column.name} must be a string"


def _error(
    *,
    row_number: int,
    entity_id: str,
    patient_id: str,
    field: str,
    rule: str,
    message: str,
    value: str,
) -> ValidationError:
    return ValidationError(
        row_number=row_number,
        entity_id=entity_id,
        patient_id=patient_id,
        field=field,
        rule=rule,
        message=message,
        value=value,
    )


def validate_records_against_contract(
    records: Sequence[Mapping[str, str]],
    contract: DatasetContract,
    *,
    reference_date: date | None = None,
) -> ValidationResult:
    """Execute structural, categorical, type, temporal, and measurement rules."""
    effective_reference_date = reference_date or date.today()
    valid_records: list[ClinicalRecord] = []
    invalid_records: list[ClinicalRecord] = []
    errors: list[ValidationError] = []
    seen_values = {column.name: set() for column in contract.columns if column.unique}
    declared_columns = set(contract.column_names)

    for row_number, source_record in enumerate(records, start=2):
        record = dict(source_record)
        normalized = {key: value.strip() for key, value in record.items()}
        entity_id = normalized.get(contract.primary_key, "")
        patient_id = normalized.get(contract.patient_id_column, "")
        row_errors: list[ValidationError] = []
        parsed_values: dict[str, object] = {}

        missing_columns = [name for name in contract.column_names if name not in record]
        for field in missing_columns:
            row_errors.append(
                _error(
                    row_number=row_number,
                    entity_id=entity_id,
                    patient_id=patient_id,
                    field=field,
                    rule="required_column",
                    message=f"Required column is missing: {field}",
                    value="",
                )
            )

        if not contract.allow_extra_columns:
            for field in sorted(set(record) - declared_columns):
                row_errors.append(
                    _error(
                        row_number=row_number,
                        entity_id=entity_id,
                        patient_id=patient_id,
                        field=field,
                        rule="unexpected_column",
                        message=f"Column is not declared by contract {contract.version}: {field}",
                        value=normalized.get(field, ""),
                    )
                )

        for column in contract.columns:
            value = normalized.get(column.name, "")
            if not value:
                if column.required:
                    row_errors.append(
                        _error(
                            row_number=row_number,
                            entity_id=entity_id,
                            patient_id=patient_id,
                            field=column.name,
                            rule="required_value",
                            message=f"{column.name} cannot be empty",
                            value=value,
                        )
                    )
                continue

            if column.unique:
                if value in seen_values[column.name]:
                    row_errors.append(
                        _error(
                            row_number=row_number,
                            entity_id=entity_id,
                            patient_id=patient_id,
                            field=column.name,
                            rule="unique",
                            message=f"Duplicate {column.name}: {value}",
                            value=value,
                        )
                    )
                else:
                    seen_values[column.name].add(value)

            if column.allowed_values and value not in column.allowed_values:
                allowed = ", ".join(column.allowed_values)
                row_errors.append(
                    _error(
                        row_number=row_number,
                        entity_id=entity_id,
                        patient_id=patient_id,
                        field=column.name,
                        rule="allowed_values",
                        message=f"{column.name} must be one of: {allowed}",
                        value=value,
                    )
                )

            try:
                parsed_values[column.name] = _parse_typed_value(column, value)
            except ValueError:
                rule, message = _type_error(column)
                row_errors.append(
                    _error(
                        row_number=row_number,
                        entity_id=entity_id,
                        patient_id=patient_id,
                        field=column.name,
                        rule=rule,
                        message=message,
                        value=value,
                    )
                )

        for field in contract.not_future_fields:
            parsed = parsed_values.get(field)
            parsed_date = parsed.date() if isinstance(parsed, datetime) else parsed
            if isinstance(parsed_date, date) and parsed_date > effective_reference_date:
                row_errors.append(
                    _error(
                        row_number=row_number,
                        entity_id=entity_id,
                        patient_id=patient_id,
                        field=field,
                        rule="not_in_future",
                        message=f"{field} cannot be in the future",
                        value=normalized.get(field, ""),
                    )
                )

        for rule in contract.order_rules:
            earlier = parsed_values.get(rule.earlier_field)
            later = parsed_values.get(rule.later_field)
            if earlier is not None and later is not None and later < earlier:
                row_errors.append(
                    _error(
                        row_number=row_number,
                        entity_id=entity_id,
                        patient_id=patient_id,
                        field=rule.later_field,
                        rule="temporal_consistency",
                        message=f"{rule.later_field} cannot precede {rule.earlier_field}",
                        value=normalized.get(rule.later_field, ""),
                    )
                )

        measurement = contract.measurement_rule
        if measurement is not None:
            code = normalized.get(measurement.code_field, "")
            profile = measurement.profiles.get(code)
            numeric_value = parsed_values.get(measurement.value_field)
            unit = normalized.get(measurement.unit_field, "")
            if profile is not None:
                if unit and unit != profile.unit:
                    row_errors.append(
                        _error(
                            row_number=row_number,
                            entity_id=entity_id,
                            patient_id=patient_id,
                            field=measurement.unit_field,
                            rule="unit_consistency",
                            message=f"{code} must use {profile.unit}",
                            value=unit,
                        )
                    )
                if isinstance(numeric_value, float) and not (
                    profile.minimum <= numeric_value <= profile.maximum
                ):
                    row_errors.append(
                        _error(
                            row_number=row_number,
                            entity_id=entity_id,
                            patient_id=patient_id,
                            field=measurement.value_field,
                            rule="plausible_range",
                            message=(
                                f"{code} must be between "
                                f"{profile.minimum:g} and {profile.maximum:g}"
                            ),
                            value=normalized.get(measurement.value_field, ""),
                        )
                    )

        if row_errors:
            invalid_records.append(record)
            errors.extend(row_errors)
        else:
            valid_records.append(normalized)

    return ValidationResult(
        valid_records=tuple(valid_records),
        invalid_records=tuple(invalid_records),
        errors=tuple(errors),
    )
