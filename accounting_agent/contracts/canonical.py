"""Typed, immutable accounting observations for provider-neutral interchange.

These records carry canonical facts read from an accounting source. They do not
carry credentials, raw bank-account values, approval authority, or connector
transport behavior. Top-level records are versioned independently from the
source observation that produced them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any

from accounting_agent.connector_contract import ConnectorEnvironment

from ._wire import (
    _MAX_INTEROPERABLE_INTEGER,
    canonical_json_sha256,
    datetime_to_wire,
    parse_enum,
    parse_json_object,
    parse_wire_date,
    parse_wire_datetime,
    require_date,
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
from .sync import SyncCheckpoint


class PeriodState(str, Enum):
    """Observed source-period state; unknown is never silently treated as open."""

    UNKNOWN = "unknown"
    OPEN = "open"
    CLOSED = "closed"
    LOCKED = "locked"


class BankDetailsState(str, Enum):
    """Presence state for a one-way bank fingerprint, never raw bank data."""

    UNKNOWN = "unknown"
    NOT_PROVIDED = "not_provided"
    FINGERPRINTED = "fingerprinted"


class LifecycleStatus(str, Enum):
    UNKNOWN = "unknown"
    ACTIVE = "active"
    INACTIVE = "inactive"


class InvoiceKind(str, Enum):
    SUPPLIER_INVOICE = "supplier_invoice"
    SUPPLIER_CREDIT_NOTE = "supplier_credit_note"


class InvoiceStatus(str, Enum):
    UNKNOWN = "unknown"
    DRAFT = "draft"
    OPEN = "open"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"


class JournalStatus(str, Enum):
    UNKNOWN = "unknown"
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


_SOURCE_FIELDS = frozenset(
    {
        "source_system",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "connection_id",
        "connection_revision",
        "connection_sha256",
        "environment",
        "sync_run_id",
        "checkpoint_id",
        "checkpoint_sha256",
        "source_record_id",
        "source_version",
        "source_sha256",
        "raw_snapshot_sha256",
        "mapping_version",
        "observed_at",
    }
)
_DIMENSION_ASSIGNMENT_FIELDS = frozenset({"dimension_id", "value_id"})
_INVOICE_LINE_FIELDS = frozenset(
    {
        "line_id",
        "description",
        "account_id",
        "tax_code",
        "net_minor",
        "tax_minor",
        "gross_minor",
    }
)
_JOURNAL_LINE_FIELDS = frozenset(
    {
        "line_id",
        "account_id",
        "description",
        "debit_minor",
        "credit_minor",
        "dimensions",
    }
)
_SUPPLIER_FIELDS = frozenset(
    {
        "schema_version",
        "supplier_id",
        "record_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "source",
        "display_name",
        "organization_identifier",
        "bank_details_state",
        "bank_account_fingerprint",
        "status",
    }
)
_INVOICE_FIELDS = frozenset(
    {
        "schema_version",
        "invoice_id",
        "record_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "source",
        "kind",
        "status",
        "supplier_id",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "period_id",
        "period_state",
        "lines",
        "net_minor",
        "tax_minor",
        "gross_minor",
    }
)
_JOURNAL_FIELDS = frozenset(
    {
        "schema_version",
        "journal_id",
        "record_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "source",
        "status",
        "journal_number",
        "journal_date",
        "currency",
        "period_id",
        "period_state",
        "lines",
    }
)
_BALANCE_FIELDS = frozenset(
    {
        "schema_version",
        "balance_id",
        "record_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "source",
        "account_id",
        "period_id",
        "period_state",
        "as_of_date",
        "currency",
        "amount_minor",
        "dimensions",
    }
)
_PERIOD_FIELDS = frozenset(
    {
        "schema_version",
        "period_id",
        "record_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "source",
        "fiscal_year_id",
        "start_date",
        "end_date",
        "state",
    }
)
_DIMENSION_FIELDS = frozenset(
    {
        "schema_version",
        "dimension_id",
        "record_version",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "source",
        "dimension_type",
        "code",
        "label",
        "status",
    }
)


def _require_source_system(value: object) -> str:
    source_system = require_nonempty_text(value, "source_system", maximum=64)
    if not re.fullmatch(r"[a-z][a-z0-9_.-]*", source_system):
        raise ValueError("source_system must be a lowercase provider identifier")
    return source_system


def _require_currency(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency must be an uppercase three-letter code")
    return value


def _require_integer(value: object, field_name: str, *, non_negative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer minor-unit amount")
    if abs(value) > _MAX_INTEROPERABLE_INTEGER:
        raise ValueError(
            f"{field_name} must stay within the interoperable integer range"
        )
    if non_negative and value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer minor-unit amount")
    return value


def _validate_scope(record: object) -> None:
    for field_name in ("tenant_id", "client_id", "legal_entity_id"):
        object.__setattr__(
            record,
            field_name,
            require_identifier(getattr(record, field_name), field_name),
        )


def _validate_record_header(record: object, record_id_field: str) -> None:
    object.__setattr__(
        record,
        record_id_field,
        require_identifier(getattr(record, record_id_field), record_id_field),
    )
    require_positive_integer(getattr(record, "record_version"), "record_version")
    _validate_scope(record)
    source = getattr(record, "source")
    if not isinstance(source, RecordSource):
        raise ValueError("source must be a RecordSource")
    if (
        source.tenant_id,
        source.client_id,
        source.legal_entity_id,
    ) != (
        getattr(record, "tenant_id"),
        getattr(record, "client_id"),
        getattr(record, "legal_entity_id"),
    ):
        raise ValueError("source scope must match canonical record scope")


def _record_wire_header(record: object, record_id_field: str) -> dict[str, Any]:
    source = getattr(record, "source")
    if not isinstance(source, RecordSource):
        raise ValueError("source must be a RecordSource")
    return {
        "schema_version": "v1",
        record_id_field: getattr(record, record_id_field),
        "record_version": getattr(record, "record_version"),
        "tenant_id": getattr(record, "tenant_id"),
        "client_id": getattr(record, "client_id"),
        "legal_entity_id": getattr(record, "legal_entity_id"),
        "source": source.to_dict(),
    }


def _assert_record_successor(
    current: object,
    previous: object,
    *,
    expected_type: type[object],
    immutable_fields: tuple[str, ...],
) -> None:
    if not isinstance(previous, expected_type):
        raise ValueError(f"previous must be a {expected_type.__name__}")
    if getattr(current, "record_version") != getattr(previous, "record_version") + 1:
        raise ValueError("record_version must advance by exactly one")
    for field_name in (
        "tenant_id",
        "client_id",
        "legal_entity_id",
        *immutable_fields,
    ):
        if getattr(current, field_name) != getattr(previous, field_name):
            raise ValueError(f"record successor cannot change {field_name}")
    current_source = getattr(current, "source")
    previous_source = getattr(previous, "source")
    if not isinstance(current_source, RecordSource) or not isinstance(
        previous_source,
        RecordSource,
    ):
        raise ValueError("record successor sources must be RecordSource values")
    current_source.assert_successor_of(previous_source)


def _parse_period_state(value: object, field_name: str = "period_state") -> PeriodState:
    return parse_enum(value, PeriodState, field_name)


def _validate_period_successor(previous: PeriodState, current: PeriodState) -> None:
    if previous is PeriodState.LOCKED and current is not PeriodState.LOCKED:
        raise ValueError("locked period cannot be reopened or become unknown")
    if previous in {PeriodState.OPEN, PeriodState.CLOSED} and current is PeriodState.UNKNOWN:
        raise ValueError("known period cannot regress to unknown")


def _validate_lifecycle_status_successor(
    previous: LifecycleStatus,
    current: LifecycleStatus,
) -> None:
    allowed = {
        LifecycleStatus.UNKNOWN: set(LifecycleStatus),
        LifecycleStatus.ACTIVE: {
            LifecycleStatus.ACTIVE,
            LifecycleStatus.INACTIVE,
        },
        LifecycleStatus.INACTIVE: {LifecycleStatus.INACTIVE},
    }
    if current not in allowed[previous]:
        raise ValueError(
            f"lifecycle status cannot transition from {previous.value} to {current.value}"
        )


def _validate_invoice_status_successor(
    previous: InvoiceStatus,
    current: InvoiceStatus,
) -> None:
    allowed = {
        InvoiceStatus.UNKNOWN: set(InvoiceStatus),
        InvoiceStatus.DRAFT: {
            InvoiceStatus.DRAFT,
            InvoiceStatus.OPEN,
            InvoiceStatus.PARTIALLY_PAID,
            InvoiceStatus.PAID,
            InvoiceStatus.VOID,
        },
        InvoiceStatus.OPEN: {
            InvoiceStatus.OPEN,
            InvoiceStatus.PARTIALLY_PAID,
            InvoiceStatus.PAID,
            InvoiceStatus.VOID,
        },
        InvoiceStatus.PARTIALLY_PAID: {
            InvoiceStatus.PARTIALLY_PAID,
            InvoiceStatus.PAID,
            InvoiceStatus.VOID,
        },
        InvoiceStatus.PAID: {InvoiceStatus.PAID},
        InvoiceStatus.VOID: {InvoiceStatus.VOID},
    }
    if current not in allowed[previous]:
        raise ValueError(
            f"invoice status cannot transition from {previous.value} to {current.value}"
        )


def _validate_journal_status_successor(
    previous: JournalStatus,
    current: JournalStatus,
) -> None:
    allowed = {
        JournalStatus.UNKNOWN: set(JournalStatus),
        JournalStatus.DRAFT: {JournalStatus.DRAFT, JournalStatus.POSTED},
        JournalStatus.POSTED: {JournalStatus.POSTED, JournalStatus.REVERSED},
        JournalStatus.REVERSED: {JournalStatus.REVERSED},
    }
    if current not in allowed[previous]:
        raise ValueError(
            f"journal status cannot transition from {previous.value} to {current.value}"
        )


def _validate_dimensions(value: object) -> tuple[DimensionAssignment, ...]:
    dimensions = require_tuple(value, "dimensions")
    if not all(isinstance(item, DimensionAssignment) for item in dimensions):
        raise ValueError("dimensions contains an invalid DimensionAssignment")
    dimension_ids = tuple(item.dimension_id for item in dimensions)
    if len(dimension_ids) != len(set(dimension_ids)):
        raise ValueError("dimensions must not repeat a dimension_id")
    return dimensions


@dataclass(frozen=True)
class RecordSource:
    """Exact connector observation that produced a canonical record."""

    source_system: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    connection_id: str
    connection_revision: int
    connection_sha256: str
    environment: ConnectorEnvironment
    sync_run_id: str
    checkpoint_id: str
    checkpoint_sha256: str
    source_record_id: str
    source_version: str
    source_sha256: str
    raw_snapshot_sha256: str
    mapping_version: str
    observed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_system", _require_source_system(self.source_system))
        _validate_scope(self)
        for field_name in (
            "connection_id",
            "sync_run_id",
            "checkpoint_id",
            "source_record_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_positive_integer(self.connection_revision, "connection_revision")
        require_sha256(self.connection_sha256, "connection_sha256")
        object.__setattr__(
            self,
            "environment",
            parse_enum(self.environment, ConnectorEnvironment, "connector environment"),
        )
        require_sha256(self.checkpoint_sha256, "checkpoint_sha256")
        object.__setattr__(
            self,
            "source_version",
            require_nonempty_text(self.source_version, "source_version", maximum=128),
        )
        require_sha256(self.source_sha256, "source_sha256")
        require_sha256(self.raw_snapshot_sha256, "raw_snapshot_sha256")
        object.__setattr__(
            self,
            "mapping_version",
            require_nonempty_text(self.mapping_version, "mapping_version", maximum=128),
        )
        require_utc_datetime(self.observed_at, "observed_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "connection_id": self.connection_id,
            "connection_revision": self.connection_revision,
            "connection_sha256": self.connection_sha256,
            "environment": self.environment.value,
            "sync_run_id": self.sync_run_id,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_sha256": self.checkpoint_sha256,
            "source_record_id": self.source_record_id,
            "source_version": self.source_version,
            "source_sha256": self.source_sha256,
            "raw_snapshot_sha256": self.raw_snapshot_sha256,
            "mapping_version": self.mapping_version,
            "observed_at": datetime_to_wire(self.observed_at),
        }

    @classmethod
    def from_dict(cls, value: object) -> RecordSource:
        payload = require_wire_object(
            value,
            contract_name="RecordSource",
            expected_fields=_SOURCE_FIELDS,
        )
        return cls(
            source_system=payload["source_system"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            connection_id=payload["connection_id"],
            connection_revision=payload["connection_revision"],
            connection_sha256=payload["connection_sha256"],
            environment=payload["environment"],
            sync_run_id=payload["sync_run_id"],
            checkpoint_id=payload["checkpoint_id"],
            checkpoint_sha256=payload["checkpoint_sha256"],
            source_record_id=payload["source_record_id"],
            source_version=payload["source_version"],
            source_sha256=payload["source_sha256"],
            raw_snapshot_sha256=payload["raw_snapshot_sha256"],
            mapping_version=payload["mapping_version"],
            observed_at=parse_wire_datetime(payload["observed_at"], "observed_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> RecordSource:
        return cls.from_dict(parse_json_object(value, "RecordSource"))

    def assert_successor_of(self, previous: RecordSource) -> None:
        if not isinstance(previous, RecordSource):
            raise ValueError("previous must be a RecordSource")
        for field_name in (
            "source_system",
            "tenant_id",
            "client_id",
            "legal_entity_id",
            "connection_id",
            "environment",
            "source_record_id",
        ):
            if getattr(self, field_name) != getattr(previous, field_name):
                raise ValueError(f"source successor cannot change {field_name}")
        if self.connection_revision < previous.connection_revision:
            raise ValueError("source connection_revision cannot move backwards")
        if (
            self.connection_revision == previous.connection_revision
            and self.connection_sha256 != previous.connection_sha256
        ):
            raise ValueError("one connection revision must retain one exact hash")
        if self.observed_at < previous.observed_at:
            raise ValueError("source observed_at cannot move backwards")
        if (
            self.source_version == previous.source_version
            and self.source_sha256 == previous.source_sha256
            and self.sync_run_id == previous.sync_run_id
            and self.checkpoint_id == previous.checkpoint_id
            and self.raw_snapshot_sha256 == previous.raw_snapshot_sha256
            and self.mapping_version == previous.mapping_version
        ):
            raise ValueError("source successor requires new versioned provenance")

    def assert_matches_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        if not isinstance(checkpoint, SyncCheckpoint):
            raise ValueError("checkpoint must be a SyncCheckpoint")
        if (
            self.source_system != checkpoint.provider_id
            or self.tenant_id != checkpoint.tenant_id
            or self.client_id != checkpoint.client_id
            or self.legal_entity_id != checkpoint.legal_entity_id
            or self.connection_id != checkpoint.connection_id
            or self.connection_revision != checkpoint.connection_revision
            or self.connection_sha256 != checkpoint.connection_sha256
            or self.environment != checkpoint.environment
            or self.sync_run_id != checkpoint.sync_run_id
            or self.checkpoint_id != checkpoint.checkpoint_id
            or self.checkpoint_sha256 != checkpoint.canonical_sha256()
            or self.raw_snapshot_sha256 != checkpoint.raw_snapshot_sha256
            or self.observed_at > checkpoint.captured_at
        ):
            raise ValueError("source does not match exact sync checkpoint")


@dataclass(frozen=True)
class DimensionAssignment:
    dimension_id: str
    value_id: str

    def __post_init__(self) -> None:
        for field_name in ("dimension_id", "value_id"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )

    def to_dict(self) -> dict[str, str]:
        return {"dimension_id": self.dimension_id, "value_id": self.value_id}

    @classmethod
    def from_dict(cls, value: object) -> DimensionAssignment:
        payload = require_wire_object(
            value,
            contract_name="DimensionAssignment",
            expected_fields=_DIMENSION_ASSIGNMENT_FIELDS,
        )
        return cls(dimension_id=payload["dimension_id"], value_id=payload["value_id"])


@dataclass(frozen=True)
class InvoiceLine:
    line_id: str
    description: str
    account_id: str
    tax_code: str
    net_minor: int
    tax_minor: int
    gross_minor: int

    def __post_init__(self) -> None:
        for field_name in ("line_id", "account_id", "tax_code"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "description",
            require_nonempty_text(self.description, "description", maximum=512),
        )
        for field_name in ("net_minor", "tax_minor", "gross_minor"):
            _require_integer(getattr(self, field_name), field_name)
        if self.net_minor + self.tax_minor != self.gross_minor:
            raise ValueError("invoice line net_minor plus tax_minor must equal gross_minor")

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "description": self.description,
            "account_id": self.account_id,
            "tax_code": self.tax_code,
            "net_minor": self.net_minor,
            "tax_minor": self.tax_minor,
            "gross_minor": self.gross_minor,
        }

    @classmethod
    def from_dict(cls, value: object) -> InvoiceLine:
        payload = require_wire_object(
            value,
            contract_name="InvoiceLine",
            expected_fields=_INVOICE_LINE_FIELDS,
        )
        return cls(
            line_id=payload["line_id"],
            description=payload["description"],
            account_id=payload["account_id"],
            tax_code=payload["tax_code"],
            net_minor=payload["net_minor"],
            tax_minor=payload["tax_minor"],
            gross_minor=payload["gross_minor"],
        )


@dataclass(frozen=True)
class JournalLine:
    line_id: str
    account_id: str
    description: str
    debit_minor: int
    credit_minor: int
    dimensions: tuple[DimensionAssignment, ...]

    def __post_init__(self) -> None:
        for field_name in ("line_id", "account_id"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "description",
            require_nonempty_text(self.description, "description", maximum=512),
        )
        debit = _require_integer(self.debit_minor, "debit_minor", non_negative=True)
        credit = _require_integer(self.credit_minor, "credit_minor", non_negative=True)
        if (debit > 0) == (credit > 0):
            raise ValueError("journal line requires exactly one positive debit or credit")
        _validate_dimensions(self.dimensions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "account_id": self.account_id,
            "description": self.description,
            "debit_minor": self.debit_minor,
            "credit_minor": self.credit_minor,
            "dimensions": [item.to_dict() for item in self.dimensions],
        }

    @classmethod
    def from_dict(cls, value: object) -> JournalLine:
        payload = require_wire_object(
            value,
            contract_name="JournalLine",
            expected_fields=_JOURNAL_LINE_FIELDS,
        )
        dimensions = require_wire_array(payload["dimensions"], "dimensions")
        return cls(
            line_id=payload["line_id"],
            account_id=payload["account_id"],
            description=payload["description"],
            debit_minor=payload["debit_minor"],
            credit_minor=payload["credit_minor"],
            dimensions=tuple(DimensionAssignment.from_dict(item) for item in dimensions),
        )


@dataclass(frozen=True)
class CanonicalSupplier:
    supplier_id: str
    record_version: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    source: RecordSource
    display_name: str
    organization_identifier: str
    bank_details_state: BankDetailsState
    bank_account_fingerprint: str
    status: LifecycleStatus

    def __post_init__(self) -> None:
        _validate_record_header(self, "supplier_id")
        object.__setattr__(
            self,
            "display_name",
            require_nonempty_text(self.display_name, "display_name", maximum=256),
        )
        object.__setattr__(
            self,
            "organization_identifier",
            require_identifier(self.organization_identifier, "organization_identifier"),
        )
        state = parse_enum(self.bank_details_state, BankDetailsState, "bank_details_state")
        object.__setattr__(self, "bank_details_state", state)
        if state is BankDetailsState.FINGERPRINTED:
            require_sha256(self.bank_account_fingerprint, "bank_account_fingerprint")
        elif self.bank_account_fingerprint != "":
            raise ValueError(
                "bank_account_fingerprint must be empty unless bank details are fingerprinted"
            )
        object.__setattr__(
            self,
            "status",
            parse_enum(self.status, LifecycleStatus, "supplier status"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **_record_wire_header(self, "supplier_id"),
            "display_name": self.display_name,
            "organization_identifier": self.organization_identifier,
            "bank_details_state": self.bank_details_state.value,
            "bank_account_fingerprint": self.bank_account_fingerprint,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalSupplier:
        payload = require_wire_object(
            value,
            contract_name="CanonicalSupplier",
            expected_fields=_SUPPLIER_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            supplier_id=payload["supplier_id"],
            record_version=payload["record_version"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            source=RecordSource.from_dict(payload["source"]),
            display_name=payload["display_name"],
            organization_identifier=payload["organization_identifier"],
            bank_details_state=payload["bank_details_state"],
            bank_account_fingerprint=payload["bank_account_fingerprint"],
            status=payload["status"],
        )

    @classmethod
    def from_json(cls, value: object) -> CanonicalSupplier:
        return cls.from_dict(parse_json_object(value, "CanonicalSupplier"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "CanonicalSupplier")

    def bank_fingerprint_changed_from(self, previous: CanonicalSupplier) -> bool:
        if not isinstance(previous, CanonicalSupplier):
            raise ValueError("previous must be a CanonicalSupplier")
        for field_name in ("tenant_id", "client_id", "legal_entity_id", "supplier_id"):
            if getattr(self, field_name) != getattr(previous, field_name):
                raise ValueError(f"bank comparison cannot change {field_name}")
        return (
            self.bank_details_state,
            self.bank_account_fingerprint,
        ) != (
            previous.bank_details_state,
            previous.bank_account_fingerprint,
        )

    def assert_successor_of(self, previous: CanonicalSupplier) -> None:
        _assert_record_successor(
            self,
            previous,
            expected_type=CanonicalSupplier,
            immutable_fields=("supplier_id", "organization_identifier"),
        )
        _validate_lifecycle_status_successor(previous.status, self.status)


@dataclass(frozen=True)
class CanonicalInvoice:
    invoice_id: str
    record_version: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    source: RecordSource
    kind: InvoiceKind
    status: InvoiceStatus
    supplier_id: str
    invoice_number: str
    invoice_date: date
    due_date: date
    currency: str
    period_id: str
    period_state: PeriodState
    lines: tuple[InvoiceLine, ...]
    net_minor: int
    tax_minor: int
    gross_minor: int

    def __post_init__(self) -> None:
        _validate_record_header(self, "invoice_id")
        object.__setattr__(self, "kind", parse_enum(self.kind, InvoiceKind, "invoice kind"))
        object.__setattr__(
            self,
            "status",
            parse_enum(self.status, InvoiceStatus, "invoice status"),
        )
        object.__setattr__(self, "supplier_id", require_identifier(self.supplier_id, "supplier_id"))
        object.__setattr__(
            self,
            "invoice_number",
            require_nonempty_text(self.invoice_number, "invoice_number", maximum=128),
        )
        require_date(self.invoice_date, "invoice_date")
        require_date(self.due_date, "due_date")
        if self.due_date < self.invoice_date:
            raise ValueError("due_date cannot precede invoice_date")
        object.__setattr__(self, "currency", _require_currency(self.currency))
        object.__setattr__(self, "period_id", require_identifier(self.period_id, "period_id"))
        object.__setattr__(self, "period_state", _parse_period_state(self.period_state))
        lines = require_tuple(self.lines, "lines")
        if not lines or not all(isinstance(line, InvoiceLine) for line in lines):
            raise ValueError("lines must be a non-empty tuple of InvoiceLine records")
        line_ids = tuple(line.line_id for line in lines)
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("invoice lines must have unique line_id values")
        for field_name in ("net_minor", "tax_minor", "gross_minor"):
            _require_integer(getattr(self, field_name), field_name)
        if self.net_minor + self.tax_minor != self.gross_minor:
            raise ValueError("invoice net_minor plus tax_minor must equal gross_minor")
        if sum(line.net_minor for line in lines) != self.net_minor:
            raise ValueError("invoice line net amounts must equal net_minor")
        if sum(line.tax_minor for line in lines) != self.tax_minor:
            raise ValueError("invoice line tax amounts must equal tax_minor")

    def to_dict(self) -> dict[str, Any]:
        return {
            **_record_wire_header(self, "invoice_id"),
            "kind": self.kind.value,
            "status": self.status.value,
            "supplier_id": self.supplier_id,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "currency": self.currency,
            "period_id": self.period_id,
            "period_state": self.period_state.value,
            "lines": [line.to_dict() for line in self.lines],
            "net_minor": self.net_minor,
            "tax_minor": self.tax_minor,
            "gross_minor": self.gross_minor,
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalInvoice:
        payload = require_wire_object(
            value,
            contract_name="CanonicalInvoice",
            expected_fields=_INVOICE_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        lines = require_wire_array(payload["lines"], "lines")
        return cls(
            invoice_id=payload["invoice_id"],
            record_version=payload["record_version"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            source=RecordSource.from_dict(payload["source"]),
            kind=payload["kind"],
            status=payload["status"],
            supplier_id=payload["supplier_id"],
            invoice_number=payload["invoice_number"],
            invoice_date=parse_wire_date(payload["invoice_date"], "invoice_date"),
            due_date=parse_wire_date(payload["due_date"], "due_date"),
            currency=payload["currency"],
            period_id=payload["period_id"],
            period_state=payload["period_state"],
            lines=tuple(InvoiceLine.from_dict(item) for item in lines),
            net_minor=payload["net_minor"],
            tax_minor=payload["tax_minor"],
            gross_minor=payload["gross_minor"],
        )

    @classmethod
    def from_json(cls, value: object) -> CanonicalInvoice:
        return cls.from_dict(parse_json_object(value, "CanonicalInvoice"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "CanonicalInvoice")

    def assert_successor_of(self, previous: CanonicalInvoice) -> None:
        _assert_record_successor(
            self,
            previous,
            expected_type=CanonicalInvoice,
            immutable_fields=(
                "invoice_id",
                "kind",
                "supplier_id",
                "invoice_number",
                "invoice_date",
                "currency",
                "period_id",
            ),
        )
        _validate_period_successor(previous.period_state, self.period_state)
        _validate_invoice_status_successor(previous.status, self.status)
        if previous.status in {InvoiceStatus.PAID, InvoiceStatus.VOID}:
            for field_name in (
                "due_date",
                "lines",
                "net_minor",
                "tax_minor",
                "gross_minor",
            ):
                if getattr(self, field_name) != getattr(previous, field_name):
                    raise ValueError(
                        f"terminal invoice content cannot change {field_name}"
                    )


@dataclass(frozen=True)
class CanonicalJournal:
    journal_id: str
    record_version: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    source: RecordSource
    status: JournalStatus
    journal_number: str
    journal_date: date
    currency: str
    period_id: str
    period_state: PeriodState
    lines: tuple[JournalLine, ...]

    def __post_init__(self) -> None:
        _validate_record_header(self, "journal_id")
        object.__setattr__(
            self,
            "status",
            parse_enum(self.status, JournalStatus, "journal status"),
        )
        object.__setattr__(
            self,
            "journal_number",
            require_nonempty_text(self.journal_number, "journal_number", maximum=128),
        )
        require_date(self.journal_date, "journal_date")
        object.__setattr__(self, "currency", _require_currency(self.currency))
        object.__setattr__(self, "period_id", require_identifier(self.period_id, "period_id"))
        object.__setattr__(self, "period_state", _parse_period_state(self.period_state))
        lines = require_tuple(self.lines, "lines")
        if not lines or not all(isinstance(line, JournalLine) for line in lines):
            raise ValueError("lines must be a non-empty tuple of JournalLine records")
        line_ids = tuple(line.line_id for line in lines)
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("journal lines must have unique line_id values")
        if self.debit_total_minor != self.credit_total_minor:
            raise ValueError("journal debit and credit totals must balance")

    @property
    def debit_total_minor(self) -> int:
        return sum(line.debit_minor for line in self.lines)

    @property
    def credit_total_minor(self) -> int:
        return sum(line.credit_minor for line in self.lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            **_record_wire_header(self, "journal_id"),
            "status": self.status.value,
            "journal_number": self.journal_number,
            "journal_date": self.journal_date.isoformat(),
            "currency": self.currency,
            "period_id": self.period_id,
            "period_state": self.period_state.value,
            "lines": [line.to_dict() for line in self.lines],
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalJournal:
        payload = require_wire_object(
            value,
            contract_name="CanonicalJournal",
            expected_fields=_JOURNAL_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        lines = require_wire_array(payload["lines"], "lines")
        return cls(
            journal_id=payload["journal_id"],
            record_version=payload["record_version"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            source=RecordSource.from_dict(payload["source"]),
            status=payload["status"],
            journal_number=payload["journal_number"],
            journal_date=parse_wire_date(payload["journal_date"], "journal_date"),
            currency=payload["currency"],
            period_id=payload["period_id"],
            period_state=payload["period_state"],
            lines=tuple(JournalLine.from_dict(item) for item in lines),
        )

    @classmethod
    def from_json(cls, value: object) -> CanonicalJournal:
        return cls.from_dict(parse_json_object(value, "CanonicalJournal"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "CanonicalJournal")

    def assert_successor_of(self, previous: CanonicalJournal) -> None:
        _assert_record_successor(
            self,
            previous,
            expected_type=CanonicalJournal,
            immutable_fields=(
                "journal_id",
                "journal_number",
                "journal_date",
                "currency",
                "period_id",
            ),
        )
        _validate_period_successor(previous.period_state, self.period_state)
        _validate_journal_status_successor(previous.status, self.status)
        if (
            previous.status in {JournalStatus.POSTED, JournalStatus.REVERSED}
            and self.lines != previous.lines
        ):
            raise ValueError("posted journal content cannot change lines")


@dataclass(frozen=True)
class CanonicalBalance:
    balance_id: str
    record_version: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    source: RecordSource
    account_id: str
    period_id: str
    period_state: PeriodState
    as_of_date: date
    currency: str
    amount_minor: int
    dimensions: tuple[DimensionAssignment, ...]

    def __post_init__(self) -> None:
        _validate_record_header(self, "balance_id")
        object.__setattr__(self, "account_id", require_identifier(self.account_id, "account_id"))
        object.__setattr__(self, "period_id", require_identifier(self.period_id, "period_id"))
        object.__setattr__(self, "period_state", _parse_period_state(self.period_state))
        require_date(self.as_of_date, "as_of_date")
        object.__setattr__(self, "currency", _require_currency(self.currency))
        _require_integer(self.amount_minor, "amount_minor")
        _validate_dimensions(self.dimensions)

    def to_dict(self) -> dict[str, Any]:
        return {
            **_record_wire_header(self, "balance_id"),
            "account_id": self.account_id,
            "period_id": self.period_id,
            "period_state": self.period_state.value,
            "as_of_date": self.as_of_date.isoformat(),
            "currency": self.currency,
            "amount_minor": self.amount_minor,
            "dimensions": [item.to_dict() for item in self.dimensions],
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalBalance:
        payload = require_wire_object(
            value,
            contract_name="CanonicalBalance",
            expected_fields=_BALANCE_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        dimensions = require_wire_array(payload["dimensions"], "dimensions")
        return cls(
            balance_id=payload["balance_id"],
            record_version=payload["record_version"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            source=RecordSource.from_dict(payload["source"]),
            account_id=payload["account_id"],
            period_id=payload["period_id"],
            period_state=payload["period_state"],
            as_of_date=parse_wire_date(payload["as_of_date"], "as_of_date"),
            currency=payload["currency"],
            amount_minor=payload["amount_minor"],
            dimensions=tuple(DimensionAssignment.from_dict(item) for item in dimensions),
        )

    @classmethod
    def from_json(cls, value: object) -> CanonicalBalance:
        return cls.from_dict(parse_json_object(value, "CanonicalBalance"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "CanonicalBalance")

    def assert_successor_of(self, previous: CanonicalBalance) -> None:
        _assert_record_successor(
            self,
            previous,
            expected_type=CanonicalBalance,
            immutable_fields=(
                "balance_id",
                "account_id",
                "period_id",
                "as_of_date",
                "currency",
                "dimensions",
            ),
        )
        _validate_period_successor(previous.period_state, self.period_state)


@dataclass(frozen=True)
class CanonicalPeriod:
    period_id: str
    record_version: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    source: RecordSource
    fiscal_year_id: str
    start_date: date
    end_date: date
    state: PeriodState

    def __post_init__(self) -> None:
        _validate_record_header(self, "period_id")
        object.__setattr__(
            self,
            "fiscal_year_id",
            require_identifier(self.fiscal_year_id, "fiscal_year_id"),
        )
        require_date(self.start_date, "start_date")
        require_date(self.end_date, "end_date")
        if self.end_date < self.start_date:
            raise ValueError("period end_date cannot precede start_date")
        object.__setattr__(self, "state", _parse_period_state(self.state, "state"))

    def to_dict(self) -> dict[str, Any]:
        return {
            **_record_wire_header(self, "period_id"),
            "fiscal_year_id": self.fiscal_year_id,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalPeriod:
        payload = require_wire_object(
            value,
            contract_name="CanonicalPeriod",
            expected_fields=_PERIOD_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            period_id=payload["period_id"],
            record_version=payload["record_version"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            source=RecordSource.from_dict(payload["source"]),
            fiscal_year_id=payload["fiscal_year_id"],
            start_date=parse_wire_date(payload["start_date"], "start_date"),
            end_date=parse_wire_date(payload["end_date"], "end_date"),
            state=payload["state"],
        )

    @classmethod
    def from_json(cls, value: object) -> CanonicalPeriod:
        return cls.from_dict(parse_json_object(value, "CanonicalPeriod"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "CanonicalPeriod")

    def assert_successor_of(self, previous: CanonicalPeriod) -> None:
        _assert_record_successor(
            self,
            previous,
            expected_type=CanonicalPeriod,
            immutable_fields=("period_id", "fiscal_year_id", "start_date", "end_date"),
        )
        _validate_period_successor(previous.state, self.state)


@dataclass(frozen=True)
class CanonicalDimension:
    dimension_id: str
    record_version: int
    tenant_id: str
    client_id: str
    legal_entity_id: str
    source: RecordSource
    dimension_type: str
    code: str
    label: str
    status: LifecycleStatus

    def __post_init__(self) -> None:
        _validate_record_header(self, "dimension_id")
        object.__setattr__(
            self,
            "dimension_type",
            require_identifier(self.dimension_type, "dimension_type"),
        )
        object.__setattr__(self, "code", require_nonempty_text(self.code, "code", maximum=128))
        object.__setattr__(
            self,
            "label",
            require_nonempty_text(self.label, "label", maximum=256),
        )
        object.__setattr__(
            self,
            "status",
            parse_enum(self.status, LifecycleStatus, "dimension status"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **_record_wire_header(self, "dimension_id"),
            "dimension_type": self.dimension_type,
            "code": self.code,
            "label": self.label,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalDimension:
        payload = require_wire_object(
            value,
            contract_name="CanonicalDimension",
            expected_fields=_DIMENSION_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            dimension_id=payload["dimension_id"],
            record_version=payload["record_version"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            source=RecordSource.from_dict(payload["source"]),
            dimension_type=payload["dimension_type"],
            code=payload["code"],
            label=payload["label"],
            status=payload["status"],
        )

    @classmethod
    def from_json(cls, value: object) -> CanonicalDimension:
        return cls.from_dict(parse_json_object(value, "CanonicalDimension"))

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "CanonicalDimension")

    def assert_successor_of(self, previous: CanonicalDimension) -> None:
        _assert_record_successor(
            self,
            previous,
            expected_type=CanonicalDimension,
            immutable_fields=("dimension_id", "dimension_type", "code"),
        )
        _validate_lifecycle_status_successor(previous.status, self.status)


__all__ = [
    "BankDetailsState",
    "CanonicalBalance",
    "CanonicalDimension",
    "CanonicalInvoice",
    "CanonicalJournal",
    "CanonicalPeriod",
    "CanonicalSupplier",
    "DimensionAssignment",
    "InvoiceKind",
    "InvoiceLine",
    "InvoiceStatus",
    "JournalLine",
    "JournalStatus",
    "LifecycleStatus",
    "PeriodState",
    "RecordSource",
]
