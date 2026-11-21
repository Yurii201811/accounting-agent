"""Immutable connector-connection and read-only synchronization contracts.

The records in this module carry opaque references, canonical identifiers,
counts, and hashes only. They deliberately implement no transport, OAuth
exchange, provider call, or external-write capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from accounting_agent.connector_contract import (
    WRITE_CAPABILITIES,
    AuthReference,
    ConnectorBinding,
    ConnectorCapability,
    ConnectorEnvironment,
)

from ._wire import (
    canonical_json_sha256,
    datetime_to_wire,
    parse_enum,
    parse_json_object,
    parse_wire_datetime,
    require_identifier,
    require_nonempty_text,
    require_positive_integer,
    require_sha256,
    require_tuple,
    require_utc_datetime,
    require_wire_array,
    require_wire_object,
    require_wire_version,
)


class ConnectorConnectionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class SyncRunStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReconciliationStatus(str, Enum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNSUPPORTED = "unsupported"


_CONNECTION_FIELDS = frozenset(
    {
        "schema_version",
        "connection_id",
        "revision",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "provider_id",
        "source_company_id",
        "environment",
        "auth_reference",
        "capabilities",
        "status",
        "recorded_at",
    }
)

_CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "checkpoint_id",
        "sync_run_id",
        "connection_id",
        "connection_revision",
        "connection_sha256",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "provider_id",
        "source_company_id",
        "environment",
        "resource",
        "sequence",
        "source_cursor",
        "next_cursor",
        "record_count",
        "raw_snapshot_sha256",
        "canonical_record_set_sha256",
        "captured_at",
    }
)

_RECONCILIATION_FIELDS = frozenset(
    {
        "schema_version",
        "reconciliation_id",
        "sync_run_id",
        "connection_id",
        "connection_revision",
        "connection_sha256",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "provider_id",
        "source_company_id",
        "environment",
        "resource",
        "source_count",
        "observed_count",
        "source_sha256",
        "observed_sha256",
        "checkpoint_chain_sha256",
        "status",
        "recorded_at",
    }
)

_SYNC_RUN_FIELDS = frozenset(
    {
        "schema_version",
        "sync_run_id",
        "revision",
        "connection_id",
        "connection_revision",
        "connection_sha256",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "provider_id",
        "source_company_id",
        "environment",
        "requested_resources",
        "status",
        "checkpoints",
        "reconciliations",
        "created_at",
        "updated_at",
    }
)

_SCOPE_FIELDS = (
    "tenant_id",
    "client_id",
    "legal_entity_id",
    "provider_id",
    "source_company_id",
    "environment",
)


def _validate_scope(record: object) -> None:
    for field_name in _SCOPE_FIELDS[:-1]:
        object.__setattr__(
            record,
            field_name,
            require_identifier(getattr(record, field_name), field_name),
        )
    try:
        environment = ConnectorEnvironment(getattr(record, "environment"))
    except (TypeError, ValueError) as error:
        raise ValueError("unknown connector environment") from error
    object.__setattr__(record, "environment", environment)
    # Preserve the stricter v1 binding rules for the provider's company key.
    try:
        ConnectorBinding(
            tenant_id=getattr(record, "tenant_id"),
            company_id=getattr(record, "source_company_id"),
            environment=environment,
        )
    except ValueError as error:
        raise ValueError("invalid connector tenant/source-company scope") from error


def _scope_tuple(record: object) -> tuple[object, ...]:
    return tuple(getattr(record, field_name) for field_name in _SCOPE_FIELDS)


def _require_optional_count(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return require_positive_integer(value, field_name, allow_zero=True)


def _require_optional_sha256(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return require_sha256(value, field_name)


@dataclass(frozen=True)
class ConnectorConnection:
    """A revisioned, exact provider scope with read-only capabilities."""

    connection_id: str
    revision: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    provider_id: str
    source_company_id: str
    environment: ConnectorEnvironment
    auth_reference: AuthReference
    capabilities: tuple[ConnectorCapability, ...]
    status: ConnectorConnectionStatus
    recorded_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connection_id",
            require_identifier(self.connection_id, "connection_id"),
        )
        require_positive_integer(self.revision, "revision")
        _validate_scope(self)
        if not isinstance(self.auth_reference, AuthReference):
            raise ValueError("auth_reference must be an AuthReference")
        capabilities = require_tuple(self.capabilities, "capabilities")
        if not capabilities:
            raise ValueError("capabilities must not be empty")
        parsed_capabilities: list[ConnectorCapability] = []
        for capability in capabilities:
            parsed = parse_enum(capability, ConnectorCapability, "connector capability")
            if parsed in WRITE_CAPABILITIES:
                raise ValueError(f"write capability {parsed.value} is forbidden")
            parsed_capabilities.append(parsed)
        if len(parsed_capabilities) != len(set(parsed_capabilities)):
            raise ValueError("capabilities must not contain duplicates")
        object.__setattr__(
            self,
            "capabilities",
            tuple(sorted(parsed_capabilities, key=lambda capability: capability.value)),
        )
        object.__setattr__(
            self,
            "status",
            parse_enum(self.status, ConnectorConnectionStatus, "connection status"),
        )
        require_utc_datetime(self.recorded_at, "recorded_at")

    @property
    def binding(self) -> ConnectorBinding:
        return ConnectorBinding(
            tenant_id=self.tenant_id,
            company_id=self.source_company_id,
            environment=self.environment,
            auth_reference=self.auth_reference,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "connection_id": self.connection_id,
            "revision": self.revision,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "provider_id": self.provider_id,
            "source_company_id": self.source_company_id,
            "environment": self.environment.value,
            "auth_reference": self.auth_reference.reference_id,
            "capabilities": [capability.value for capability in self.capabilities],
            "status": self.status.value,
            "recorded_at": datetime_to_wire(self.recorded_at),
        }

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "ConnectorConnection")

    @classmethod
    def from_dict(cls, value: object) -> ConnectorConnection:
        payload = require_wire_object(
            value,
            contract_name="ConnectorConnection",
            expected_fields=_CONNECTION_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        capabilities = require_wire_array(payload["capabilities"], "capabilities")
        return cls(
            connection_id=payload["connection_id"],
            revision=payload["revision"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            provider_id=payload["provider_id"],
            source_company_id=payload["source_company_id"],
            environment=payload["environment"],
            auth_reference=AuthReference(payload["auth_reference"]),
            capabilities=tuple(capabilities),
            status=payload["status"],
            recorded_at=parse_wire_datetime(payload["recorded_at"], "recorded_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> ConnectorConnection:
        return cls.from_dict(parse_json_object(value, "ConnectorConnection"))

    def assert_successor_of(self, previous: ConnectorConnection) -> None:
        if not isinstance(previous, ConnectorConnection):
            raise ValueError("previous must be a ConnectorConnection")
        if self.revision != previous.revision + 1:
            raise ValueError("connection revision must advance by exactly one")
        immutable_fields = (
            "connection_id",
            *_SCOPE_FIELDS,
            "capabilities",
        )
        for field_name in immutable_fields:
            if getattr(self, field_name) != getattr(previous, field_name):
                raise ValueError(f"connection {field_name} is immutable")
        if self.recorded_at < previous.recorded_at:
            raise ValueError("connection recorded_at cannot move backwards")
        if previous.status is ConnectorConnectionStatus.REVOKED:
            raise ValueError("revoked connection is terminal and cannot reactivate")
        allowed = {
            ConnectorConnectionStatus.PENDING: {
                ConnectorConnectionStatus.PENDING,
                ConnectorConnectionStatus.ACTIVE,
                ConnectorConnectionStatus.SUSPENDED,
                ConnectorConnectionStatus.REVOKED,
            },
            ConnectorConnectionStatus.ACTIVE: {
                ConnectorConnectionStatus.ACTIVE,
                ConnectorConnectionStatus.SUSPENDED,
                ConnectorConnectionStatus.REVOKED,
            },
            ConnectorConnectionStatus.SUSPENDED: {
                ConnectorConnectionStatus.ACTIVE,
                ConnectorConnectionStatus.SUSPENDED,
                ConnectorConnectionStatus.REVOKED,
            },
        }
        if self.status not in allowed[previous.status]:
            raise ValueError(
                f"invalid connection transition {previous.status.value}->{self.status.value}"
            )


@dataclass(frozen=True)
class SyncCheckpoint:
    """One cumulative, hash-bound read checkpoint within an exact sync scope."""

    checkpoint_id: str
    sync_run_id: str
    connection_id: str
    connection_revision: int
    connection_sha256: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    provider_id: str
    source_company_id: str
    environment: ConnectorEnvironment
    resource: str
    sequence: int
    source_cursor: str | None
    next_cursor: str | None
    record_count: int
    raw_snapshot_sha256: str
    canonical_record_set_sha256: str
    captured_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("checkpoint_id", "sync_run_id", "connection_id", "resource"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_positive_integer(self.connection_revision, "connection_revision")
        require_sha256(self.connection_sha256, "connection_sha256")
        require_positive_integer(self.sequence, "sequence")
        _validate_scope(self)
        for field_name in ("source_cursor", "next_cursor"):
            value = getattr(self, field_name)
            if value is not None:
                require_nonempty_text(value, field_name, maximum=4096)
        require_positive_integer(self.record_count, "record_count", allow_zero=True)
        require_sha256(self.raw_snapshot_sha256, "raw_snapshot_sha256")
        require_sha256(
            self.canonical_record_set_sha256,
            "canonical_record_set_sha256",
        )
        require_utc_datetime(self.captured_at, "captured_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "checkpoint_id": self.checkpoint_id,
            "sync_run_id": self.sync_run_id,
            "connection_id": self.connection_id,
            "connection_revision": self.connection_revision,
            "connection_sha256": self.connection_sha256,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "provider_id": self.provider_id,
            "source_company_id": self.source_company_id,
            "environment": self.environment.value,
            "resource": self.resource,
            "sequence": self.sequence,
            "source_cursor": self.source_cursor,
            "next_cursor": self.next_cursor,
            "record_count": self.record_count,
            "raw_snapshot_sha256": self.raw_snapshot_sha256,
            "canonical_record_set_sha256": self.canonical_record_set_sha256,
            "captured_at": datetime_to_wire(self.captured_at),
        }

    @classmethod
    def from_dict(cls, value: object) -> SyncCheckpoint:
        payload = require_wire_object(
            value,
            contract_name="SyncCheckpoint",
            expected_fields=_CHECKPOINT_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            checkpoint_id=payload["checkpoint_id"],
            sync_run_id=payload["sync_run_id"],
            connection_id=payload["connection_id"],
            connection_revision=payload["connection_revision"],
            connection_sha256=payload["connection_sha256"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            provider_id=payload["provider_id"],
            source_company_id=payload["source_company_id"],
            environment=payload["environment"],
            resource=payload["resource"],
            sequence=payload["sequence"],
            source_cursor=payload["source_cursor"],
            next_cursor=payload["next_cursor"],
            record_count=payload["record_count"],
            raw_snapshot_sha256=payload["raw_snapshot_sha256"],
            canonical_record_set_sha256=payload["canonical_record_set_sha256"],
            captured_at=parse_wire_datetime(payload["captured_at"], "captured_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> SyncCheckpoint:
        return cls.from_dict(parse_json_object(value, "SyncCheckpoint"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "SyncCheckpoint")

    @staticmethod
    def chain_sha256(checkpoints: tuple[SyncCheckpoint, ...]) -> str:
        values = require_tuple(checkpoints, "checkpoints")
        if not values or not all(isinstance(item, SyncCheckpoint) for item in values):
            raise ValueError("checkpoint chain requires typed checkpoints")
        first = values[0]
        expected_scope = (
            first.sync_run_id,
            first.connection_id,
            first.connection_revision,
            first.connection_sha256,
            _scope_tuple(first),
            first.resource,
        )
        if any(
            (
                item.sync_run_id,
                item.connection_id,
                item.connection_revision,
                item.connection_sha256,
                _scope_tuple(item),
                item.resource,
            )
            != expected_scope
            for item in values
        ):
            raise ValueError("checkpoint chain must bind one resource and exact scope")
        if any(
            current.sequence <= previous.sequence
            for previous, current in zip(values, values[1:], strict=False)
        ):
            raise ValueError("checkpoint chain must be ordered by increasing sequence")
        previous: SyncCheckpoint | None = None
        seen_next_cursors: set[str] = set()
        for checkpoint in values:
            if previous is None:
                if checkpoint.source_cursor is not None:
                    raise ValueError("checkpoint chain first source cursor must be empty")
            else:
                if checkpoint.captured_at < previous.captured_at:
                    raise ValueError("checkpoint chain must be ordered by capture time")
                if checkpoint.record_count < previous.record_count:
                    raise ValueError("checkpoint chain record_count cannot decrease")
                if (
                    previous.next_cursor is None
                    or checkpoint.source_cursor != previous.next_cursor
                ):
                    raise ValueError("checkpoint chain cursor is not continuous")
            if checkpoint.next_cursor is not None:
                if checkpoint.next_cursor in seen_next_cursors:
                    raise ValueError("checkpoint chain cursor cannot repeat")
                seen_next_cursors.add(checkpoint.next_cursor)
            previous = checkpoint
        return canonical_json_sha256(
            {
                "schema_version": "v1",
                "checkpoint_sha256": [item.canonical_sha256() for item in values],
            },
            "SyncCheckpoint chain",
        )

    def assert_matches_connection(self, connection: ConnectorConnection) -> None:
        if not isinstance(connection, ConnectorConnection):
            raise ValueError("connection must be a ConnectorConnection")
        if (
            self.connection_id != connection.connection_id
            or self.connection_revision != connection.revision
            or self.connection_sha256 != connection.canonical_sha256()
            or _scope_tuple(self) != _scope_tuple(connection)
        ):
            raise ValueError("checkpoint does not match exact connection scope")

    def assert_matches_run(self, run: SyncRun) -> None:
        if not isinstance(run, SyncRun):
            raise ValueError("run must be a SyncRun")
        if (
            self.sync_run_id != run.sync_run_id
            or self.connection_id != run.connection_id
            or self.connection_revision != run.connection_revision
            or self.connection_sha256 != run.connection_sha256
            or _scope_tuple(self) != _scope_tuple(run)
            or self.resource not in run.requested_resources
        ):
            raise ValueError("checkpoint does not match exact sync run scope")


@dataclass(frozen=True)
class SourceReconciliation:
    """Source/observed count and hash evidence for one requested resource."""

    reconciliation_id: str
    sync_run_id: str
    connection_id: str
    connection_revision: int
    connection_sha256: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    provider_id: str
    source_company_id: str
    environment: ConnectorEnvironment
    resource: str
    source_count: int | None
    observed_count: int | None
    source_sha256: str | None
    observed_sha256: str | None
    checkpoint_chain_sha256: str
    status: ReconciliationStatus
    recorded_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "reconciliation_id",
            "sync_run_id",
            "connection_id",
            "resource",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_positive_integer(self.connection_revision, "connection_revision")
        require_sha256(self.connection_sha256, "connection_sha256")
        _validate_scope(self)
        source_count = _require_optional_count(self.source_count, "source_count")
        observed_count = _require_optional_count(self.observed_count, "observed_count")
        source_sha256 = _require_optional_sha256(self.source_sha256, "source_sha256")
        observed_sha256 = _require_optional_sha256(self.observed_sha256, "observed_sha256")
        require_sha256(self.checkpoint_chain_sha256, "checkpoint_chain_sha256")
        object.__setattr__(self, "source_count", source_count)
        object.__setattr__(self, "observed_count", observed_count)
        object.__setattr__(self, "source_sha256", source_sha256)
        object.__setattr__(self, "observed_sha256", observed_sha256)
        status = parse_enum(self.status, ReconciliationStatus, "reconciliation status")
        object.__setattr__(self, "status", status)
        require_utc_datetime(self.recorded_at, "recorded_at")

        observed_pair = (observed_count, observed_sha256)
        if (observed_count is None) != (observed_sha256 is None):
            raise ValueError("observed reconciliation count and hash must appear together")
        if status is ReconciliationStatus.UNSUPPORTED:
            if source_count is not None or source_sha256 is not None:
                raise ValueError("unsupported reconciliation cannot claim source evidence")
            return
        if None in (source_count, observed_count, source_sha256, observed_sha256):
            raise ValueError(f"{status.value} reconciliation requires complete evidence")
        exact_match = (source_count, source_sha256) == observed_pair
        if status is ReconciliationStatus.VERIFIED and not exact_match:
            raise ValueError("verified reconciliation requires exact count and hash equality")
        if status is ReconciliationStatus.MISMATCH and exact_match:
            raise ValueError("mismatch reconciliation evidence must differ")

    @property
    def is_verified(self) -> bool:
        return self.status is ReconciliationStatus.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "reconciliation_id": self.reconciliation_id,
            "sync_run_id": self.sync_run_id,
            "connection_id": self.connection_id,
            "connection_revision": self.connection_revision,
            "connection_sha256": self.connection_sha256,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "provider_id": self.provider_id,
            "source_company_id": self.source_company_id,
            "environment": self.environment.value,
            "resource": self.resource,
            "source_count": self.source_count,
            "observed_count": self.observed_count,
            "source_sha256": self.source_sha256,
            "observed_sha256": self.observed_sha256,
            "checkpoint_chain_sha256": self.checkpoint_chain_sha256,
            "status": self.status.value,
            "recorded_at": datetime_to_wire(self.recorded_at),
        }

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "SourceReconciliation")

    @classmethod
    def from_dict(cls, value: object) -> SourceReconciliation:
        payload = require_wire_object(
            value,
            contract_name="SourceReconciliation",
            expected_fields=_RECONCILIATION_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            reconciliation_id=payload["reconciliation_id"],
            sync_run_id=payload["sync_run_id"],
            connection_id=payload["connection_id"],
            connection_revision=payload["connection_revision"],
            connection_sha256=payload["connection_sha256"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            provider_id=payload["provider_id"],
            source_company_id=payload["source_company_id"],
            environment=payload["environment"],
            resource=payload["resource"],
            source_count=payload["source_count"],
            observed_count=payload["observed_count"],
            source_sha256=payload["source_sha256"],
            observed_sha256=payload["observed_sha256"],
            checkpoint_chain_sha256=payload["checkpoint_chain_sha256"],
            status=payload["status"],
            recorded_at=parse_wire_datetime(payload["recorded_at"], "recorded_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> SourceReconciliation:
        return cls.from_dict(parse_json_object(value, "SourceReconciliation"))

    def assert_matches_connection(self, connection: ConnectorConnection) -> None:
        if not isinstance(connection, ConnectorConnection):
            raise ValueError("connection must be a ConnectorConnection")
        if (
            self.connection_id != connection.connection_id
            or self.connection_revision != connection.revision
            or self.connection_sha256 != connection.canonical_sha256()
            or _scope_tuple(self) != _scope_tuple(connection)
        ):
            raise ValueError("reconciliation does not match exact connection scope")

    def assert_matches_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        if not isinstance(checkpoint, SyncCheckpoint):
            raise ValueError("checkpoint must be a SyncCheckpoint")
        if (
            self.sync_run_id != checkpoint.sync_run_id
            or self.connection_id != checkpoint.connection_id
            or self.connection_revision != checkpoint.connection_revision
            or self.connection_sha256 != checkpoint.connection_sha256
            or _scope_tuple(self) != _scope_tuple(checkpoint)
            or self.resource != checkpoint.resource
            or self.observed_count != checkpoint.record_count
            or self.observed_sha256 != checkpoint.canonical_record_set_sha256
        ):
            raise ValueError("reconciliation does not match latest checkpoint")

    def assert_matches_run(self, run: SyncRun) -> None:
        if not isinstance(run, SyncRun):
            raise ValueError("run must be a SyncRun")
        if (
            self.sync_run_id != run.sync_run_id
            or self.connection_id != run.connection_id
            or self.connection_revision != run.connection_revision
            or self.connection_sha256 != run.connection_sha256
            or _scope_tuple(self) != _scope_tuple(run)
            or self.resource not in run.requested_resources
        ):
            raise ValueError("reconciliation does not match exact sync run scope")


@dataclass(frozen=True)
class SyncRun:
    """A revisioned read-sync lifecycle with append-only integrity evidence."""

    sync_run_id: str
    revision: int
    connection_id: str
    connection_revision: int
    connection_sha256: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    provider_id: str
    source_company_id: str
    environment: ConnectorEnvironment
    requested_resources: tuple[str, ...]
    status: SyncRunStatus
    checkpoints: tuple[SyncCheckpoint, ...]
    reconciliations: tuple[SourceReconciliation, ...]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("sync_run_id", "connection_id"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_positive_integer(self.revision, "revision")
        require_positive_integer(self.connection_revision, "connection_revision")
        require_sha256(self.connection_sha256, "connection_sha256")
        _validate_scope(self)
        requested_resources = require_tuple(self.requested_resources, "requested_resources")
        if not requested_resources:
            raise ValueError("requested_resources must not be empty")
        canonical_resources = tuple(
            require_identifier(resource, "requested resource") for resource in requested_resources
        )
        if len(canonical_resources) != len(set(canonical_resources)):
            raise ValueError("requested_resources must not contain duplicates")
        object.__setattr__(self, "requested_resources", canonical_resources)
        status = parse_enum(self.status, SyncRunStatus, "sync run status")
        object.__setattr__(self, "status", status)
        checkpoints = require_tuple(self.checkpoints, "checkpoints")
        reconciliations = require_tuple(self.reconciliations, "reconciliations")
        if not all(isinstance(item, SyncCheckpoint) for item in checkpoints):
            raise ValueError("checkpoints contains an invalid typed record")
        if not all(isinstance(item, SourceReconciliation) for item in reconciliations):
            raise ValueError("reconciliations contains an invalid typed record")
        require_utc_datetime(self.created_at, "created_at")
        require_utc_datetime(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if status is SyncRunStatus.PLANNED and (checkpoints or reconciliations):
            raise ValueError("planned sync run cannot contain observed evidence")
        self._validate_checkpoints(checkpoints)
        self._validate_reconciliations(checkpoints, reconciliations)
        if status is SyncRunStatus.COMPLETED:
            self._validate_completion(checkpoints, reconciliations)

    def _validate_checkpoints(self, checkpoints: tuple[object, ...]) -> None:
        checkpoint_ids: set[str] = set()
        previous_time: datetime | None = None
        counts_by_resource: dict[str, int] = {}
        previous_by_resource: dict[str, SyncCheckpoint] = {}
        cursors_by_resource: dict[str, set[str]] = {}
        for expected_sequence, untyped_checkpoint in enumerate(checkpoints, start=1):
            if not isinstance(untyped_checkpoint, SyncCheckpoint):
                raise ValueError("checkpoints contains an invalid typed record")
            checkpoint = untyped_checkpoint
            checkpoint.assert_matches_run(self)
            if checkpoint.checkpoint_id in checkpoint_ids:
                raise ValueError("checkpoint identifiers must be unique")
            checkpoint_ids.add(checkpoint.checkpoint_id)
            if checkpoint.sequence != expected_sequence:
                raise ValueError("checkpoint sequence must be contiguous and one-based")
            if previous_time is not None and checkpoint.captured_at < previous_time:
                raise ValueError("checkpoint timestamps cannot move backwards")
            if checkpoint.captured_at > self.updated_at:
                raise ValueError("checkpoint cannot be captured after run updated_at")
            if checkpoint.captured_at < self.created_at:
                raise ValueError("checkpoint cannot precede run created_at")
            prior_checkpoint = previous_by_resource.get(checkpoint.resource)
            if prior_checkpoint is None:
                if checkpoint.source_cursor is not None:
                    raise ValueError("first checkpoint source cursor must be empty")
            elif (
                prior_checkpoint.next_cursor is None
                or checkpoint.source_cursor != prior_checkpoint.next_cursor
            ):
                raise ValueError("checkpoint cursor chain is not continuous")
            prior_count = counts_by_resource.get(checkpoint.resource)
            if prior_count is not None and checkpoint.record_count < prior_count:
                raise ValueError("checkpoint record_count cannot decrease for a resource")
            counts_by_resource[checkpoint.resource] = checkpoint.record_count
            if checkpoint.next_cursor is not None:
                seen_cursors = cursors_by_resource.setdefault(checkpoint.resource, set())
                if checkpoint.next_cursor in seen_cursors:
                    raise ValueError("checkpoint cursor cannot repeat for a resource")
                seen_cursors.add(checkpoint.next_cursor)
            previous_by_resource[checkpoint.resource] = checkpoint
            previous_time = checkpoint.captured_at

    def _validate_reconciliations(
        self,
        checkpoints: tuple[object, ...],
        reconciliations: tuple[object, ...],
    ) -> None:
        resources: set[str] = set()
        identifiers: set[str] = set()
        checkpoints_by_resource: dict[str, list[SyncCheckpoint]] = {}
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, SyncCheckpoint):
                raise ValueError("checkpoints contains an invalid typed record")
            checkpoints_by_resource.setdefault(checkpoint.resource, []).append(checkpoint)
        for untyped_reconciliation in reconciliations:
            if not isinstance(untyped_reconciliation, SourceReconciliation):
                raise ValueError("reconciliations contains an invalid typed record")
            reconciliation = untyped_reconciliation
            reconciliation.assert_matches_run(self)
            if reconciliation.resource in resources:
                raise ValueError("each resource can have at most one reconciliation")
            if reconciliation.reconciliation_id in identifiers:
                raise ValueError("reconciliation identifiers must be unique")
            if reconciliation.recorded_at > self.updated_at:
                raise ValueError("reconciliation cannot be recorded after run updated_at")
            resource_checkpoints = checkpoints_by_resource.get(reconciliation.resource)
            if not resource_checkpoints:
                raise ValueError("reconciliation requires checkpoint evidence")
            latest = resource_checkpoints[-1]
            if reconciliation.recorded_at < latest.captured_at:
                raise ValueError("reconciliation cannot precede its latest checkpoint")
            reconciliation.assert_matches_checkpoint(latest)
            expected_chain = SyncCheckpoint.chain_sha256(tuple(resource_checkpoints))
            if reconciliation.checkpoint_chain_sha256 != expected_chain:
                raise ValueError("reconciliation checkpoint chain hash does not match")
            resources.add(reconciliation.resource)
            identifiers.add(reconciliation.reconciliation_id)

    def _validate_completion(
        self,
        checkpoints: tuple[object, ...],
        reconciliations: tuple[object, ...],
    ) -> None:
        typed_checkpoints = tuple(
            checkpoint for checkpoint in checkpoints if isinstance(checkpoint, SyncCheckpoint)
        )
        typed_reconciliations = tuple(
            reconciliation
            for reconciliation in reconciliations
            if isinstance(reconciliation, SourceReconciliation)
        )
        if not typed_checkpoints:
            raise ValueError("completed sync run requires checkpoint evidence")
        checkpoint_resources = {checkpoint.resource for checkpoint in typed_checkpoints}
        if checkpoint_resources != set(self.requested_resources):
            raise ValueError("completed sync run requires checkpoints for every requested resource")
        if len(typed_reconciliations) != len(self.requested_resources) or {
            item.resource for item in typed_reconciliations
        } != set(self.requested_resources):
            raise ValueError(
                "completed sync run requires exactly one reconciliation per requested resource"
            )
        if any(not reconciliation.is_verified for reconciliation in typed_reconciliations):
            raise ValueError("completed sync run requires verified reconciliations")
        latest_by_resource: dict[str, SyncCheckpoint] = {}
        chains_by_resource: dict[str, list[SyncCheckpoint]] = {}
        for checkpoint in typed_checkpoints:
            latest_by_resource[checkpoint.resource] = checkpoint
            chains_by_resource.setdefault(checkpoint.resource, []).append(checkpoint)
        for reconciliation in typed_reconciliations:
            resource = reconciliation.resource
            latest = latest_by_resource[resource]
            if latest.next_cursor is not None:
                raise ValueError("completed resource must not retain a next cursor")
            reconciliation.assert_matches_checkpoint(latest)
            expected_chain = SyncCheckpoint.chain_sha256(tuple(chains_by_resource[resource]))
            if reconciliation.checkpoint_chain_sha256 != expected_chain:
                raise ValueError("reconciliation checkpoint chain hash does not match")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "sync_run_id": self.sync_run_id,
            "revision": self.revision,
            "connection_id": self.connection_id,
            "connection_revision": self.connection_revision,
            "connection_sha256": self.connection_sha256,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "provider_id": self.provider_id,
            "source_company_id": self.source_company_id,
            "environment": self.environment.value,
            "requested_resources": list(self.requested_resources),
            "status": self.status.value,
            "checkpoints": [checkpoint.to_dict() for checkpoint in self.checkpoints],
            "reconciliations": [item.to_dict() for item in self.reconciliations],
            "created_at": datetime_to_wire(self.created_at),
            "updated_at": datetime_to_wire(self.updated_at),
        }

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "SyncRun")

    @classmethod
    def from_dict(cls, value: object) -> SyncRun:
        payload = require_wire_object(
            value,
            contract_name="SyncRun",
            expected_fields=_SYNC_RUN_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        requested_resources = require_wire_array(
            payload["requested_resources"], "requested_resources"
        )
        checkpoints = require_wire_array(payload["checkpoints"], "checkpoints")
        reconciliations = require_wire_array(payload["reconciliations"], "reconciliations")
        return cls(
            sync_run_id=payload["sync_run_id"],
            revision=payload["revision"],
            connection_id=payload["connection_id"],
            connection_revision=payload["connection_revision"],
            connection_sha256=payload["connection_sha256"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            provider_id=payload["provider_id"],
            source_company_id=payload["source_company_id"],
            environment=payload["environment"],
            requested_resources=tuple(requested_resources),
            status=payload["status"],
            checkpoints=tuple(SyncCheckpoint.from_dict(item) for item in checkpoints),
            reconciliations=tuple(SourceReconciliation.from_dict(item) for item in reconciliations),
            created_at=parse_wire_datetime(payload["created_at"], "created_at"),
            updated_at=parse_wire_datetime(payload["updated_at"], "updated_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> SyncRun:
        return cls.from_dict(parse_json_object(value, "SyncRun"))

    def assert_matches_connection(self, connection: ConnectorConnection) -> None:
        if not isinstance(connection, ConnectorConnection):
            raise ValueError("connection must be a ConnectorConnection")
        if (
            connection.status is not ConnectorConnectionStatus.ACTIVE
            or self.connection_id != connection.connection_id
            or self.connection_revision != connection.revision
            or self.connection_sha256 != connection.canonical_sha256()
            or _scope_tuple(self) != _scope_tuple(connection)
        ):
            raise ValueError("sync run does not match an active exact connection scope")

    def assert_successor_of(self, previous: SyncRun) -> None:
        if not isinstance(previous, SyncRun):
            raise ValueError("previous must be a SyncRun")
        if self.revision != previous.revision + 1:
            raise ValueError("sync run revision must advance by exactly one")
        immutable_fields = (
            "sync_run_id",
            "connection_id",
            "connection_revision",
            "connection_sha256",
            *_SCOPE_FIELDS,
            "requested_resources",
            "created_at",
        )
        for field_name in immutable_fields:
            if getattr(self, field_name) != getattr(previous, field_name):
                raise ValueError(f"sync run {field_name} is immutable")
        if self.updated_at < previous.updated_at:
            raise ValueError("sync run updated_at cannot move backwards")
        terminal = {
            SyncRunStatus.COMPLETED,
            SyncRunStatus.FAILED,
            SyncRunStatus.CANCELLED,
        }
        if previous.status in terminal:
            raise ValueError("terminal sync run is immutable")
        allowed = {
            SyncRunStatus.PLANNED: {SyncRunStatus.RUNNING},
            SyncRunStatus.RUNNING: {
                SyncRunStatus.RUNNING,
                SyncRunStatus.COMPLETED,
                SyncRunStatus.FAILED,
                SyncRunStatus.CANCELLED,
            },
        }
        if self.status not in allowed[previous.status]:
            raise ValueError(
                f"invalid sync run transition {previous.status.value}->{self.status.value}"
            )
        if self.checkpoints[: len(previous.checkpoints)] != previous.checkpoints:
            raise ValueError("sync run checkpoints are append-only")
        if self.reconciliations[: len(previous.reconciliations)] != previous.reconciliations:
            raise ValueError("sync run reconciliations are append-only")


__all__ = [
    "ConnectorConnection",
    "ConnectorConnectionStatus",
    "ReconciliationStatus",
    "SourceReconciliation",
    "SyncCheckpoint",
    "SyncRun",
    "SyncRunStatus",
]
