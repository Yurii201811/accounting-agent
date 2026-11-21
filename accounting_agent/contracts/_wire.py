"""Private validators for canonical contract values and JSON-shaped wire data."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from base64 import b64decode, b64encode
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from enum import Enum
from typing import Any, TypeVar

from accounting_agent.client_identity import canonical_client_id

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WEAK_IDENTIFIERS = frozenset({"n/a", "none", "null", "unknown", "unset"})
_MAX_INTEROPERABLE_INTEGER = 9_007_199_254_740_991
_EnumT = TypeVar("_EnumT", bound=Enum)


def require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    try:
        canonical = canonical_client_id(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a canonical opaque identifier") from error
    if canonical.casefold() in _WEAK_IDENTIFIERS or canonical in {".", ".."}:
        raise ValueError(f"{field_name} must not be a placeholder identifier")
    return canonical


def parse_enum(value: object, enum_type: type[_EnumT], field_name: str) -> _EnumT:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"unknown {field_name}") from error


def require_wire_object(
    value: object,
    *,
    contract_name: str,
    expected_fields: frozenset[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{contract_name} must be a wire object")
    if any(not isinstance(field, str) for field in value):
        raise ValueError(f"{contract_name} field names must be strings")
    actual_fields = set(value)
    missing = expected_fields - actual_fields
    unexpected = actual_fields - expected_fields
    if missing:
        raise ValueError(f"{contract_name} missing fields: {', '.join(sorted(missing))}")
    if unexpected:
        raise ValueError(f"{contract_name} has unexpected fields: {', '.join(sorted(unexpected))}")
    return value


def require_wire_version(value: object) -> None:
    if value != "v1":
        raise ValueError("unsupported schema_version")


def require_wire_array(value: object, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a wire array")
    return value


def require_nonempty_text(value: object, field_name: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


def require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def require_positive_integer(value: object, field_name: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > _MAX_INTEROPERABLE_INTEGER
    ):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(
            f"{field_name} must be a {qualifier} interoperable integer"
        )
    return value


def require_tuple(value: object, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be a tuple")
    return value


def require_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return value


def datetime_to_wire(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_wire_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{6})?Z",
        value,
    ):
        raise ValueError(f"{field_name} must be an ISO 8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO 8601 UTC timestamp") from error
    parsed = require_utc_datetime(parsed, field_name)
    if datetime_to_wire(parsed) != value:
        raise ValueError(f"{field_name} must be a canonical ISO 8601 UTC timestamp")
    return parsed


def require_date(value: object, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date")
    return value


def parse_wire_date(value: object, field_name: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{field_name} must be an ISO 8601 date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO 8601 date") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be a canonical ISO 8601 date")
    return parsed


def require_base64(value: object, field_name: str, *, minimum_bytes: int = 1) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be canonical base64")
    try:
        decoded = b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{field_name} must be canonical base64") from error
    if len(decoded) < minimum_bytes or b64encode(decoded).decode("ascii") != value:
        raise ValueError(f"{field_name} must be canonical base64")
    return value


class DuplicateWireKey(ValueError):
    """Raised when raw JSON attempts to replace an earlier object member."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            raise DuplicateWireKey(f"duplicate JSON key: {key}")
        result[key] = item
    return result


def parse_json_object(value: object, contract_name: str) -> Mapping[str, Any]:
    if not isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{contract_name} JSON must be text or bytes")
    try:
        parsed = json.loads(value, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, DuplicateWireKey) as error:
        raise ValueError(f"{contract_name} JSON is invalid: {error}") from error
    if not isinstance(parsed, Mapping):
        raise ValueError(f"{contract_name} JSON must contain an object")
    return parsed


def canonical_json_sha256(value: object, field_name: str) -> str:
    _require_restricted_json(value, field_name)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError(f"{field_name} must be canonical restricted JSON") from error
    return hashlib.sha256(encoded).hexdigest()


def _require_restricted_json(value: object, field_name: str) -> None:
    if value is None or type(value) is bool:
        return
    if isinstance(value, str):
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError(f"{field_name} must not contain control or format characters")
        return
    if type(value) is int:
        if abs(value) > _MAX_INTEROPERABLE_INTEGER:
            raise ValueError(
                f"{field_name} integers must stay within the interoperable JSON range"
            )
        return
    if isinstance(value, list):
        for item in value:
            _require_restricted_json(item, field_name)
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{field_name} object keys must be strings")
        for key, item in value.items():
            _require_restricted_json(key, field_name)
            _require_restricted_json(item, field_name)
        return
    raise ValueError(
        f"{field_name} permits only objects, arrays, strings, integers, booleans, and null"
    )
