"""Bounded, injected-transport read connectors.

The public core intentionally ships no network or credential transport.  A
caller must inject a semantic read transport and an active, provider-bound
``ConnectorConnection`` before any provider response can be decoded.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol, cast, runtime_checkable

from accounting_agent.connector_contract import (
    WRITE_CAPABILITIES,
    ConnectorBinding,
    ConnectorCapability,
    ConnectorContractError,
    ConnectorAdapter,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorPage,
    ConnectorReadRequest,
    HealthStatus,
    RetryMetadata,
    get_connector_manifest,
    raw_snapshot_sha256,
    require_guarded_read_request,
)
from accounting_agent.contracts.sync import ConnectorConnection, ConnectorConnectionStatus


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_INTEROPERABLE_JSON_NUMBER = (1 << 53) - 1
_FORBIDDEN_PARAMETER_NAMES = frozenset(
    {
        "authorization",
        "credential",
        "endpoint",
        "headers",
        "password",
        "query",
        "sql",
        "token",
        "uri",
        "url",
    }
)


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a single-line opaque identifier")
    return value


class StrictReadDecodeError(ConnectorContractError):
    """Raised when raw provider bytes do not satisfy the strict read schema."""


@dataclass(frozen=True)
class SemanticReadRequest:
    """A provider operation identifier with no URL or generic-query surface."""

    connection_id: str
    connection_revision: int
    connection_sha256: str
    provider_id: str
    binding: ConnectorBinding
    resource: str
    capability: ConnectorCapability
    operation_id: str
    parameters: tuple[tuple[str, str | int], ...]

    def __post_init__(self) -> None:
        for field_name in ("connection_id", "provider_id", "resource", "operation_id"):
            object.__setattr__(
                self,
                field_name,
                _require_identifier(getattr(self, field_name), field_name),
            )
        if (
            isinstance(self.connection_revision, bool)
            or not isinstance(self.connection_revision, int)
            or self.connection_revision < 1
        ):
            raise ValueError("connection_revision must be a positive integer")
        if (
            not isinstance(self.connection_sha256, str)
            or not _SHA256_PATTERN.fullmatch(self.connection_sha256)
        ):
            raise ValueError("connection_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.binding, ConnectorBinding):
            raise TypeError("binding must be a ConnectorBinding")
        try:
            capability = ConnectorCapability(self.capability)
        except (TypeError, ValueError) as error:
            raise ValueError("unknown connector capability") from error
        if capability in WRITE_CAPABILITIES:
            raise ValueError("semantic read requests cannot carry a write capability")
        object.__setattr__(self, "capability", capability)
        if not isinstance(self.parameters, tuple):
            raise TypeError("parameters must be an immutable tuple")
        seen: set[str] = set()
        for item in self.parameters:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("each semantic parameter must be a name/value tuple")
            name, value = item
            _require_identifier(name, "parameter name")
            if name.lower() in _FORBIDDEN_PARAMETER_NAMES:
                raise ValueError(f"semantic parameter {name!r} is forbidden")
            if name in seen:
                raise ValueError("semantic parameter names must be unique")
            seen.add(name)
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise TypeError("semantic parameter values must be text or integers")
            if isinstance(value, str) and (not value or value != value.strip()):
                raise ValueError("semantic text parameters must be non-blank and trimmed")

    @property
    def parameter_map(self) -> Mapping[str, str | int]:
        return MappingProxyType(dict(self.parameters))

    def canonical_sha256(self) -> str:
        payload = {
            "schema": "accounting-agent-semantic-read-request-v1",
            "connection_id": self.connection_id,
            "connection_revision": self.connection_revision,
            "connection_sha256": self.connection_sha256,
            "provider_id": self.provider_id,
            "binding": self.binding.to_dict(),
            "resource": self.resource,
            "capability": self.capability.value,
            "operation_id": self.operation_id,
            "parameters": [list(item) for item in self.parameters],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RawReadResponse:
    """Exact raw response bytes returned by an injected semantic transport."""

    provider_id: str
    operation_id: str
    request_sha256: str
    status_code: int
    content_type: str
    body: bytes
    retry: RetryMetadata

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "operation_id"):
            object.__setattr__(
                self,
                field_name,
                _require_identifier(getattr(self, field_name), field_name),
            )
        if (
            not isinstance(self.request_sha256, str)
            or not _SHA256_PATTERN.fullmatch(self.request_sha256)
        ):
            raise ValueError("request_sha256 must be a lowercase SHA-256 digest")
        if (
            isinstance(self.status_code, bool)
            or not isinstance(self.status_code, int)
            or not 100 <= self.status_code <= 599
        ):
            raise ValueError("status_code must be an HTTP status integer")
        if (
            not isinstance(self.content_type, str)
            or not self.content_type
            or self.content_type != self.content_type.strip()
        ):
            raise ValueError("content_type must be non-blank and trimmed")
        if not isinstance(self.body, bytes):
            raise TypeError("body must be exact immutable bytes")
        if not isinstance(self.retry, RetryMetadata):
            raise TypeError("retry must be RetryMetadata")


@dataclass(frozen=True)
class SemanticTransportIdentity:
    """Immutable provider and connection scope owned by an injected transport."""

    provider_id: str
    connection_id: str
    connection_revision: int
    connection_sha256: str
    binding: ConnectorBinding

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "connection_id"):
            object.__setattr__(
                self,
                field_name,
                _require_identifier(getattr(self, field_name), field_name),
            )
        if (
            isinstance(self.connection_revision, bool)
            or not isinstance(self.connection_revision, int)
            or self.connection_revision < 1
        ):
            raise ValueError("connection_revision must be a positive integer")
        if (
            not isinstance(self.connection_sha256, str)
            or not _SHA256_PATTERN.fullmatch(self.connection_sha256)
        ):
            raise ValueError("connection_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(self.binding, ConnectorBinding):
            raise TypeError("binding must be a ConnectorBinding")


@runtime_checkable
class SemanticReadTransport(Protocol):
    """Injected boundary; the public core supplies no implementation."""

    @property
    def identity(self) -> SemanticTransportIdentity:
        ...

    def read(self, request: SemanticReadRequest) -> RawReadResponse:
        ...


def decode_raw_json_object(
    response: RawReadResponse,
    *,
    expected_provider_id: str,
    expected_operation_id: str,
    expected_request_sha256: str,
    max_bytes: int = 4 * 1024 * 1024,
) -> dict[str, object]:
    """Decode one strict provider response."""

    if not isinstance(response, RawReadResponse):
        raise TypeError("response must be a RawReadResponse")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if (
        not isinstance(expected_request_sha256, str)
        or not _SHA256_PATTERN.fullmatch(expected_request_sha256)
    ):
        raise ValueError("expected_request_sha256 must be a lowercase SHA-256 digest")
    if response.provider_id != expected_provider_id:
        raise StrictReadDecodeError("raw response provider does not match the read request")
    if response.operation_id != expected_operation_id:
        raise StrictReadDecodeError("raw response operation does not match the read request")
    if response.request_sha256 != expected_request_sha256:
        raise StrictReadDecodeError("raw response request binding does not match the read request")
    if response.status_code != 200:
        raise StrictReadDecodeError("raw response status is not a successful read")
    media_parts = [part.strip().lower() for part in response.content_type.split(";")]
    if media_parts[0] != "application/json" or any(
        part != "charset=utf-8" for part in media_parts[1:]
    ):
        raise StrictReadDecodeError("raw response must be UTF-8 application/json")
    if len(response.body) > max_bytes:
        raise StrictReadDecodeError("raw response exceeds the bounded payload size")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        decoded: dict[str, object] = {}
        for key, value in pairs:
            if key in decoded:
                raise StrictReadDecodeError(f"duplicate JSON object key: {key}")
            decoded[key] = value
        return decoded

    def reject_constant(value: str) -> object:
        raise StrictReadDecodeError(f"non-standard JSON constant is forbidden: {value}")

    def parse_bounded_integer(value: str) -> int:
        decoded = int(value)
        if abs(decoded) > _MAX_INTEROPERABLE_JSON_NUMBER:
            raise StrictReadDecodeError("JSON integer exceeds the interoperable range")
        return decoded

    def parse_bounded_float(value: str) -> float:
        decoded = float(value)
        if (
            not math.isfinite(decoded)
            or abs(decoded) > _MAX_INTEROPERABLE_JSON_NUMBER
        ):
            raise StrictReadDecodeError("JSON float is non-finite or exceeds the bounded range")
        return decoded

    try:
        text = response.body.decode("utf-8", errors="strict")
        decoded = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
            parse_float=parse_bounded_float,
            parse_int=parse_bounded_integer,
        )
    except StrictReadDecodeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StrictReadDecodeError("raw response is not strict UTF-8 JSON") from error
    if not isinstance(decoded, dict):
        raise StrictReadDecodeError("raw response JSON root must be an object")
    return decoded


@dataclass(frozen=True)
class _ResourceReadSpec:
    capability: ConnectorCapability
    operation_id: str
    record_field: str


_FORTNOX_SPECS = MappingProxyType(
    {
        "accounts": _ResourceReadSpec(
            ConnectorCapability.READ_MASTER_DATA,
            "fortnox.accounts.v1",
            "Accounts",
        ),
        "suppliers": _ResourceReadSpec(
            ConnectorCapability.READ_MASTER_DATA,
            "fortnox.suppliers.v1",
            "Suppliers",
        ),
        "financial_years": _ResourceReadSpec(
            ConnectorCapability.READ_MASTER_DATA,
            "fortnox.financial_years.v1",
            "FinancialYears",
        ),
    }
)
_NETSUITE_SPECS = MappingProxyType(
    {
        "subsidiaries": _ResourceReadSpec(
            ConnectorCapability.READ_MASTER_DATA,
            "netsuite.suiteql.subsidiaries.v1",
            "items",
        ),
        "accounts": _ResourceReadSpec(
            ConnectorCapability.READ_MASTER_DATA,
            "netsuite.suiteql.accounts.v1",
            "items",
        ),
        "vendors": _ResourceReadSpec(
            ConnectorCapability.READ_MASTER_DATA,
            "netsuite.suiteql.vendors.v1",
            "items",
        ),
        "accounting_periods": _ResourceReadSpec(
            ConnectorCapability.READ_PERIOD_LOCKS,
            "netsuite.suiteql.accounting_periods.v1",
            "items",
        ),
    }
)


def _immutable_projection(
    specs: Mapping[str, _ResourceReadSpec],
    attribute: str,
) -> Mapping[str, Any]:
    return MappingProxyType(
        {resource: getattr(spec, attribute) for resource, spec in specs.items()}
    )


def _require_non_negative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StrictReadDecodeError(f"{label} must be a non-negative integer")
    return value


def _require_positive_integer(value: object, label: str) -> int:
    result = _require_non_negative_integer(value, label)
    if result < 1:
        raise StrictReadDecodeError(f"{label} must be a positive integer")
    return result


def _require_record_list(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise StrictReadDecodeError(f"{label} must be an array of JSON objects")
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _without_provider_links(record: Mapping[str, object]) -> Mapping[str, object]:
    """Drop provider navigation metadata without interpreting or following it."""

    return MappingProxyType(
        {
            key: _freeze_json(value)
            for key, value in record.items()
            if key not in {"links", "nextLink", "@odata.nextLink"}
        }
    )


class _BoundedReadConnector:
    __slots__ = ("_connection", "_transport", "_transport_identity")

    _provider_id: str
    _specs: Mapping[str, _ResourceReadSpec]

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise FrozenInstanceError(f"cannot assign to field {name!r}")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        connection: ConnectorConnection,
        transport: SemanticReadTransport,
    ) -> None:
        if not isinstance(connection, ConnectorConnection):
            raise TypeError("connection must be a ConnectorConnection")
        if connection.provider_id != self._provider_id:
            raise ConnectorContractError(
                f"{self._provider_id} connector requires a provider-matching connection"
            )
        if connection.status is not ConnectorConnectionStatus.ACTIVE:
            raise ConnectorContractError("connector connection must be active")
        if not isinstance(transport, SemanticReadTransport):
            raise TypeError("transport must satisfy SemanticReadTransport")
        expected_transport_identity = SemanticTransportIdentity(
            provider_id=connection.provider_id,
            connection_id=connection.connection_id,
            connection_revision=connection.revision,
            connection_sha256=connection.canonical_sha256(),
            binding=connection.binding,
        )
        if (
            not isinstance(transport.identity, SemanticTransportIdentity)
            or transport.identity != expected_transport_identity
        ):
            raise ConnectorContractError(
                "transport identity does not match the exact connector connection"
            )
        self._connection = connection
        self._transport = transport
        self._transport_identity = expected_transport_identity

    def _require_transport_identity(self) -> None:
        if self._transport.identity != self._transport_identity:
            raise ConnectorContractError(
                "transport identity changed after connector construction"
            )

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def binding(self) -> ConnectorBinding:
        return self._connection.binding

    @property
    def manifest(self) -> ConnectorManifest:
        return get_connector_manifest(self._provider_id)

    @property
    def resource_capabilities(self) -> Mapping[str, ConnectorCapability]:
        return _immutable_projection(self._specs, "capability")

    @property
    def operation_ids(self) -> Mapping[str, str]:
        return _immutable_projection(self._specs, "operation_id")

    def check_health(self) -> ConnectorHealth:
        return ConnectorHealth(
            provider_id=self.provider_id,
            binding=self.binding,
            status=HealthStatus.NOT_CONFIGURED,
            checked_at=datetime.now(UTC),
            detail_code="offline_transport_health_unavailable",
        )

    def _preflight(
        self,
        request: ConnectorReadRequest,
    ) -> _ResourceReadSpec:
        if not isinstance(request, ConnectorReadRequest):
            raise TypeError("request must be a ConnectorReadRequest")
        self._require_transport_identity()
        try:
            spec = self._specs[request.resource]
        except KeyError as error:
            raise ConnectorContractError(
                f"unsupported {self._provider_id} read resource: {request.resource}"
            ) from error
        if spec.capability not in self._connection.capabilities:
            raise ConnectorContractError(
                f"connection does not grant {spec.capability.value} for {request.resource}"
            )
        require_guarded_read_request(
            cast(ConnectorAdapter, self),
            request,
            capability=spec.capability,
        )
        return spec

    def _semantic_request(
        self,
        request: ConnectorReadRequest,
        spec: _ResourceReadSpec,
        parameters: tuple[tuple[str, str | int], ...],
    ) -> SemanticReadRequest:
        return SemanticReadRequest(
            connection_id=self._connection.connection_id,
            connection_revision=self._connection.revision,
            connection_sha256=self._connection.canonical_sha256(),
            provider_id=self.provider_id,
            binding=self.binding,
            resource=request.resource,
            capability=spec.capability,
            operation_id=spec.operation_id,
            parameters=parameters,
        )


class FortnoxReadConnector(_BoundedReadConnector):
    """Fortnox accounts, suppliers and financial-year reads with no transport default."""

    _provider_id = "fortnox"
    _specs = _FORTNOX_SPECS
    __slots__ = ()

    @staticmethod
    def _page_number(cursor: str | None) -> int:
        if cursor is None:
            return 1
        match = re.fullmatch(r"page:([1-9][0-9]*)", cursor)
        if match is None:
            raise ConnectorContractError("Fortnox cursor must be page:<positive-int>")
        return int(match.group(1))

    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        spec = self._preflight(request)
        page_number = self._page_number(request.cursor)
        semantic_request = self._semantic_request(
            request,
            spec,
            (("page", page_number), ("page_size", request.page_size)),
        )
        response = self._transport.read(semantic_request)
        self._require_transport_identity()
        decoded = decode_raw_json_object(
            response,
            expected_provider_id=self.provider_id,
            expected_operation_id=spec.operation_id,
            expected_request_sha256=semantic_request.canonical_sha256(),
        )
        allowed_root_keys = {spec.record_field, "MetaInformation"}
        if set(decoded) - {"links"} != allowed_root_keys:
            raise StrictReadDecodeError(
                "Fortnox response fields do not match the fixed resource schema"
            )
        records = _require_record_list(decoded[spec.record_field], spec.record_field)
        if len(records) > request.page_size:
            raise StrictReadDecodeError("Fortnox response exceeds the requested page size")
        metadata = decoded["MetaInformation"]
        if not isinstance(metadata, dict) or set(metadata) != {
            "@CurrentPage",
            "@TotalPages",
            "@TotalResources",
        }:
            raise StrictReadDecodeError("Fortnox MetaInformation schema is incomplete")
        current_page = _require_positive_integer(metadata["@CurrentPage"], "@CurrentPage")
        total_pages = _require_positive_integer(metadata["@TotalPages"], "@TotalPages")
        total_resources = _require_non_negative_integer(
            metadata["@TotalResources"],
            "@TotalResources",
        )
        if total_resources < len(records):
            raise StrictReadDecodeError(
                "Fortnox total resources cannot be smaller than the returned page"
            )
        if current_page != page_number:
            raise StrictReadDecodeError(
                "Fortnox response page does not match the requested page"
            )
        if total_pages < current_page:
            raise StrictReadDecodeError("Fortnox total pages cannot precede current page")
        next_cursor = f"page:{current_page + 1}" if current_page < total_pages else None
        return ConnectorPage(
            provider_id=self.provider_id,
            binding=self.binding,
            resource=request.resource,
            schema_version=self.manifest.schema_version,
            mapping_version=self.manifest.mapping_version,
            raw_snapshot_hash=raw_snapshot_sha256(response.body),
            records=tuple(_without_provider_links(record) for record in records),
            source_cursor=request.cursor,
            next_cursor=next_cursor,
            retry=response.retry,
        )


class NetSuiteSuiteQLReadConnector(_BoundedReadConnector):
    """NetSuite reads limited to four fixed, versioned SuiteQL operation IDs."""

    _provider_id = "netsuite"
    _specs = _NETSUITE_SPECS
    __slots__ = ()

    @staticmethod
    def _offset(cursor: str | None) -> int:
        if cursor is None:
            return 0
        match = re.fullmatch(r"offset:(0|[1-9][0-9]*)", cursor)
        if match is None:
            raise ConnectorContractError(
                "NetSuite cursor must be offset:<non-negative-int>"
            )
        return int(match.group(1))

    def read_page(self, request: ConnectorReadRequest) -> ConnectorPage:
        spec = self._preflight(request)
        offset = self._offset(request.cursor)
        if offset % request.page_size != 0:
            raise ConnectorContractError(
                "NetSuite offset must be divisible by page_size"
            )
        semantic_request = self._semantic_request(
            request,
            spec,
            (("offset", offset), ("page_size", request.page_size)),
        )
        response = self._transport.read(semantic_request)
        self._require_transport_identity()
        decoded = decode_raw_json_object(
            response,
            expected_provider_id=self.provider_id,
            expected_operation_id=spec.operation_id,
            expected_request_sha256=semantic_request.canonical_sha256(),
        )
        expected_fields = {"links", "count", "hasMore", "items", "offset", "totalResults"}
        if set(decoded) != expected_fields:
            raise StrictReadDecodeError(
                "NetSuite SuiteQL response fields do not match the fixed envelope"
            )
        records = _require_record_list(decoded["items"], "items")
        count = _require_non_negative_integer(decoded["count"], "count")
        observed_offset = _require_non_negative_integer(decoded["offset"], "offset")
        total_results = _require_non_negative_integer(
            decoded["totalResults"],
            "totalResults",
        )
        has_more = decoded["hasMore"]
        if not isinstance(has_more, bool):
            raise StrictReadDecodeError("hasMore must be a boolean")
        if count != len(records):
            raise StrictReadDecodeError("NetSuite count does not match the item array")
        if count > request.page_size:
            raise StrictReadDecodeError("NetSuite response exceeds the requested page size")
        if observed_offset != offset:
            raise StrictReadDecodeError(
                "NetSuite response offset does not match the requested offset"
            )
        next_offset = offset + count
        if next_offset > total_results:
            raise StrictReadDecodeError("NetSuite page exceeds totalResults")
        expected_has_more = next_offset < total_results
        if has_more != expected_has_more:
            raise StrictReadDecodeError(
                "NetSuite hasMore is inconsistent with offset, count and totalResults"
            )
        if has_more and count == 0:
            raise StrictReadDecodeError("NetSuite pagination must make forward progress")
        if has_more and count != request.page_size:
            raise StrictReadDecodeError("NetSuite nonterminal responses must return a full page")
        next_cursor = f"offset:{offset + request.page_size}" if has_more else None
        return ConnectorPage(
            provider_id=self.provider_id,
            binding=self.binding,
            resource=request.resource,
            schema_version=self.manifest.schema_version,
            mapping_version=self.manifest.mapping_version,
            raw_snapshot_hash=raw_snapshot_sha256(response.body),
            records=tuple(_without_provider_links(record) for record in records),
            source_cursor=request.cursor,
            next_cursor=next_cursor,
            retry=response.retry,
        )


__all__ = [
    "FortnoxReadConnector",
    "NetSuiteSuiteQLReadConnector",
    "RawReadResponse",
    "SemanticReadRequest",
    "SemanticReadTransport",
    "SemanticTransportIdentity",
    "StrictReadDecodeError",
    "decode_raw_json_object",
]
