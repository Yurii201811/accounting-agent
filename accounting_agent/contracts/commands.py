"""Immutable production command and external-draft receipt contracts.

These records carry exact scope, opaque identifiers, and hashes only. They do
not execute provider calls, contain credentials or source documents, or grant
authority merely by being constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from accounting_agent.connector_contract import ConnectorEnvironment

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
from .scope import AuthenticationStrength, MembershipRole, TenantContext


class ApprovalDecisionOutcome(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class ExternalDraftRecordType(str, Enum):
    SUPPLIER_INVOICE = "supplier_invoice"


class DraftReadbackStatus(str, Enum):
    COMPLETED = "completed"
    AMBIGUOUS = "ambiguous"
    TIMEOUT = "timeout"
    MISSING = "missing"


class ExternalDraftObservedState(str, Enum):
    UNBOOKED_REVERSIBLE = "unbooked_reversible"
    MISSING = "missing"
    UNKNOWN = "unknown"
    BOOKED = "booked"
    APPROVED = "approved"
    SENT = "sent"
    PAID = "paid"


class DraftComparisonStatus(str, Enum):
    EXACT_MATCH = "exact_match"
    MISMATCH = "mismatch"
    SCOPE_DRIFT = "scope_drift"
    NOT_AVAILABLE = "not_available"


_APPROVAL_FIELDS = frozenset(
    {
        "schema_version",
        "context",
        "approval_request_id",
        "approval_request_sha256",
        "requestor_actor_id",
        "acting_role",
        "outcome",
        "reason",
        "expected_version",
        "idempotency_key",
        "decided_at",
    }
)

_DRAFT_FIELDS = frozenset(
    {
        "schema_version",
        "draft_command_id",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "case_id",
        "connection_id",
        "connection_revision",
        "connection_sha256",
        "provider_id",
        "environment",
        "record_type",
        "payload_sha256",
        "evidence_hashes",
        "policy_decision_sha256",
        "approval_receipt_sha256",
        "approval_decision_sha256",
        "permit_id",
        "permit_sha256",
        "idempotency_key",
        "created_at",
        "expires_at",
    }
)

_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "receipt_id",
        "draft_command_id",
        "draft_command_sha256",
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "case_id",
        "connection_id",
        "connection_revision",
        "connection_sha256",
        "provider_id",
        "environment",
        "payload_sha256",
        "idempotency_key",
        "provider_reference",
        "provider_response_sha256",
        "readback_sha256",
        "readback_status",
        "observed_state",
        "comparison_status",
        "attempted_at",
        "readback_at",
        "recorded_at",
    }
)

_DRAFT_SCOPE_FIELDS = (
    "tenant_id",
    "client_id",
    "legal_entity_id",
    "case_id",
    "connection_id",
    "connection_revision",
    "connection_sha256",
    "provider_id",
    "environment",
    "payload_sha256",
    "idempotency_key",
)


def _require_environment(value: object) -> ConnectorEnvironment:
    return parse_enum(value, ConnectorEnvironment, "connector environment")


def _require_strong_idempotency_key(value: object) -> str:
    return require_sha256(value, "idempotency_key")


def _require_scope_identifiers(record: object) -> None:
    for field_name in (
        "tenant_id",
        "client_id",
        "legal_entity_id",
        "case_id",
        "connection_id",
        "provider_id",
    ):
        object.__setattr__(
            record,
            field_name,
            require_identifier(getattr(record, field_name), field_name),
        )
    object.__setattr__(
        record,
        "environment",
        _require_environment(getattr(record, "environment")),
    )


@dataclass(frozen=True)
class ApprovalDecisionCommand:
    """An optimistic, identity-bound human approval decision command."""

    context: TenantContext
    approval_request_id: str
    approval_request_sha256: str
    requestor_actor_id: str
    acting_role: MembershipRole
    outcome: ApprovalDecisionOutcome
    reason: str
    expected_version: int
    idempotency_key: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.context, TenantContext):
            raise ValueError("context must be a trusted TenantContext")
        object.__setattr__(
            self,
            "approval_request_id",
            require_identifier(self.approval_request_id, "approval_request_id"),
        )
        require_sha256(self.approval_request_sha256, "approval_request_sha256")
        object.__setattr__(
            self,
            "requestor_actor_id",
            require_identifier(self.requestor_actor_id, "requestor_actor_id"),
        )
        acting_role = parse_enum(self.acting_role, MembershipRole, "acting role")
        object.__setattr__(self, "acting_role", acting_role)
        if MembershipRole.SERVICE_WORKER in self.context.roles:
            raise ValueError("service identities cannot issue approval decisions")
        if acting_role not in {MembershipRole.REVIEWER, MembershipRole.CONTROLLER}:
            raise ValueError("acting role must be reviewer or controller")
        if acting_role not in self.context.roles:
            raise ValueError("acting role must be present in authenticated roles")
        if self.context.actor_id == self.requestor_actor_id:
            raise ValueError("self-review is forbidden")
        strong_authentication = {
            AuthenticationStrength.MULTI_FACTOR,
            AuthenticationStrength.PHISHING_RESISTANT,
            AuthenticationStrength.HIGH_ASSURANCE,
        }
        if self.context.authentication_strength not in strong_authentication:
            raise ValueError("approval decisions require multi-factor authentication")
        object.__setattr__(
            self,
            "outcome",
            parse_enum(self.outcome, ApprovalDecisionOutcome, "approval outcome"),
        )
        require_nonempty_text(self.reason, "reason", maximum=1024)
        require_positive_integer(self.expected_version, "expected_version")
        _require_strong_idempotency_key(self.idempotency_key)
        require_utc_datetime(self.decided_at, "decided_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "context": self.context.to_dict(),
            "approval_request_id": self.approval_request_id,
            "approval_request_sha256": self.approval_request_sha256,
            "requestor_actor_id": self.requestor_actor_id,
            "acting_role": self.acting_role.value,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "expected_version": self.expected_version,
            "idempotency_key": self.idempotency_key,
            "decided_at": datetime_to_wire(self.decided_at),
        }

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "ApprovalDecisionCommand")

    @classmethod
    def from_dict(cls, value: object) -> ApprovalDecisionCommand:
        payload = require_wire_object(
            value,
            contract_name="ApprovalDecisionCommand",
            expected_fields=_APPROVAL_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            context=TenantContext.from_dict(payload["context"]),
            approval_request_id=payload["approval_request_id"],
            approval_request_sha256=payload["approval_request_sha256"],
            requestor_actor_id=payload["requestor_actor_id"],
            acting_role=payload["acting_role"],
            outcome=payload["outcome"],
            reason=payload["reason"],
            expected_version=payload["expected_version"],
            idempotency_key=payload["idempotency_key"],
            decided_at=parse_wire_datetime(payload["decided_at"], "decided_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> ApprovalDecisionCommand:
        return cls.from_dict(parse_json_object(value, "ApprovalDecisionCommand"))


@dataclass(frozen=True)
class ExternalDraftCommand:
    """A hash-only request envelope for an isolated external-draft gateway."""

    draft_command_id: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    case_id: str
    connection_id: str
    connection_revision: int
    connection_sha256: str
    provider_id: str
    environment: ConnectorEnvironment
    record_type: ExternalDraftRecordType
    payload_sha256: str
    evidence_hashes: tuple[str, ...]
    policy_decision_sha256: str
    approval_receipt_sha256: str
    approval_decision_sha256: str
    permit_id: str
    permit_sha256: str
    idempotency_key: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "draft_command_id",
            require_identifier(self.draft_command_id, "draft_command_id"),
        )
        _require_scope_identifiers(self)
        require_positive_integer(self.connection_revision, "connection_revision")
        require_sha256(self.connection_sha256, "connection_sha256")
        object.__setattr__(
            self,
            "record_type",
            parse_enum(self.record_type, ExternalDraftRecordType, "external draft record type"),
        )
        require_sha256(self.payload_sha256, "payload_sha256")
        evidence_hashes = require_tuple(self.evidence_hashes, "evidence_hashes")
        if not evidence_hashes:
            raise ValueError("evidence_hashes must not be empty")
        if len(evidence_hashes) != len(set(evidence_hashes)):
            raise ValueError("evidence_hashes must not contain duplicates")
        for evidence_hash in evidence_hashes:
            require_sha256(evidence_hash, "evidence_hash")
        object.__setattr__(self, "evidence_hashes", evidence_hashes)
        require_sha256(self.policy_decision_sha256, "policy_decision_sha256")
        require_sha256(self.approval_receipt_sha256, "approval_receipt_sha256")
        require_sha256(self.approval_decision_sha256, "approval_decision_sha256")
        object.__setattr__(self, "permit_id", require_identifier(self.permit_id, "permit_id"))
        require_sha256(self.permit_sha256, "permit_sha256")
        _require_strong_idempotency_key(self.idempotency_key)
        require_utc_datetime(self.created_at, "created_at")
        require_utc_datetime(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("external draft command must expire after it is created")

    @property
    def grants_authority(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "draft_command_id": self.draft_command_id,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "case_id": self.case_id,
            "connection_id": self.connection_id,
            "connection_revision": self.connection_revision,
            "connection_sha256": self.connection_sha256,
            "provider_id": self.provider_id,
            "environment": self.environment.value,
            "record_type": self.record_type.value,
            "payload_sha256": self.payload_sha256,
            "evidence_hashes": list(self.evidence_hashes),
            "policy_decision_sha256": self.policy_decision_sha256,
            "approval_receipt_sha256": self.approval_receipt_sha256,
            "approval_decision_sha256": self.approval_decision_sha256,
            "permit_id": self.permit_id,
            "permit_sha256": self.permit_sha256,
            "idempotency_key": self.idempotency_key,
            "created_at": datetime_to_wire(self.created_at),
            "expires_at": datetime_to_wire(self.expires_at),
        }

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "ExternalDraftCommand")

    @classmethod
    def from_dict(cls, value: object) -> ExternalDraftCommand:
        payload = require_wire_object(
            value,
            contract_name="ExternalDraftCommand",
            expected_fields=_DRAFT_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        evidence_hashes = require_wire_array(payload["evidence_hashes"], "evidence_hashes")
        return cls(
            draft_command_id=payload["draft_command_id"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            case_id=payload["case_id"],
            connection_id=payload["connection_id"],
            connection_revision=payload["connection_revision"],
            connection_sha256=payload["connection_sha256"],
            provider_id=payload["provider_id"],
            environment=payload["environment"],
            record_type=payload["record_type"],
            payload_sha256=payload["payload_sha256"],
            evidence_hashes=tuple(evidence_hashes),
            policy_decision_sha256=payload["policy_decision_sha256"],
            approval_receipt_sha256=payload["approval_receipt_sha256"],
            approval_decision_sha256=payload["approval_decision_sha256"],
            permit_id=payload["permit_id"],
            permit_sha256=payload["permit_sha256"],
            idempotency_key=payload["idempotency_key"],
            created_at=parse_wire_datetime(payload["created_at"], "created_at"),
            expires_at=parse_wire_datetime(payload["expires_at"], "expires_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> ExternalDraftCommand:
        return cls.from_dict(parse_json_object(value, "ExternalDraftCommand"))


@dataclass(frozen=True)
class ExternalDraftReceipt:
    """Observed provider state; unsafe or uncertain outcomes are always frozen."""

    receipt_id: str
    draft_command_id: str
    draft_command_sha256: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    case_id: str
    connection_id: str
    connection_revision: int
    connection_sha256: str
    provider_id: str
    environment: ConnectorEnvironment
    payload_sha256: str
    idempotency_key: str
    provider_reference: str | None
    provider_response_sha256: str | None
    readback_sha256: str | None
    readback_status: DraftReadbackStatus
    observed_state: ExternalDraftObservedState
    comparison_status: DraftComparisonStatus
    attempted_at: datetime
    readback_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("receipt_id", "draft_command_id"):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_sha256(self.draft_command_sha256, "draft_command_sha256")
        _require_scope_identifiers(self)
        require_positive_integer(self.connection_revision, "connection_revision")
        require_sha256(self.connection_sha256, "connection_sha256")
        require_sha256(self.payload_sha256, "payload_sha256")
        _require_strong_idempotency_key(self.idempotency_key)
        if self.provider_reference is not None:
            require_nonempty_text(self.provider_reference, "provider_reference", maximum=1024)
        if self.provider_response_sha256 is not None:
            require_sha256(self.provider_response_sha256, "provider_response_sha256")
        if self.readback_sha256 is not None:
            require_sha256(self.readback_sha256, "readback_sha256")
        readback_status = parse_enum(
            self.readback_status,
            DraftReadbackStatus,
            "draft readback status",
        )
        observed_state = parse_enum(
            self.observed_state,
            ExternalDraftObservedState,
            "external draft observed state",
        )
        comparison_status = parse_enum(
            self.comparison_status,
            DraftComparisonStatus,
            "draft comparison status",
        )
        object.__setattr__(self, "readback_status", readback_status)
        object.__setattr__(self, "observed_state", observed_state)
        object.__setattr__(self, "comparison_status", comparison_status)
        for field_name in ("attempted_at", "readback_at", "recorded_at"):
            require_utc_datetime(getattr(self, field_name), field_name)
        if not self.attempted_at <= self.readback_at <= self.recorded_at:
            raise ValueError("receipt timestamps must be monotonic")
        self._validate_readback_metadata()

    def _validate_readback_metadata(self) -> None:
        if self.readback_status is DraftReadbackStatus.COMPLETED:
            if any(
                value is None
                for value in (
                    self.provider_reference,
                    self.provider_response_sha256,
                    self.readback_sha256,
                )
            ):
                raise ValueError("completed readback requires provider and readback evidence")
            if (
                self.observed_state
                in {
                    ExternalDraftObservedState.UNKNOWN,
                    ExternalDraftObservedState.MISSING,
                }
                or self.comparison_status is DraftComparisonStatus.NOT_AVAILABLE
            ):
                raise ValueError("completed readback requires a concrete comparable provider state")
            if (
                self.comparison_status is DraftComparisonStatus.EXACT_MATCH
                and self.readback_sha256 != self.payload_sha256
            ):
                raise ValueError("exact match requires readback_sha256 to equal payload_sha256")
            if (
                self.comparison_status is DraftComparisonStatus.MISMATCH
                and self.readback_sha256 == self.payload_sha256
            ):
                raise ValueError("mismatch requires different payload and readback hashes")
            return
        if (
            self.readback_sha256 is not None
            or self.comparison_status is not DraftComparisonStatus.NOT_AVAILABLE
        ):
            raise ValueError("non-completed readback cannot claim comparison evidence")
        if (self.provider_reference is None) != (self.provider_response_sha256 is None):
            raise ValueError(
                "non-completed provider reference and response hash must appear together"
            )
        if self.readback_status is DraftReadbackStatus.MISSING:
            if self.observed_state is not ExternalDraftObservedState.MISSING:
                raise ValueError("missing readback requires missing observed state")
            return
        if self.observed_state is not ExternalDraftObservedState.UNKNOWN:
            raise ValueError("ambiguous or timeout readback requires unknown observed state")

    def _observation_is_candidate_safe(self) -> bool:
        return not (
            self.readback_status is not DraftReadbackStatus.COMPLETED
            or self.observed_state is not ExternalDraftObservedState.UNBOOKED_REVERSIBLE
            or self.comparison_status is not DraftComparisonStatus.EXACT_MATCH
            or self.readback_sha256 != self.payload_sha256
        )

    def is_frozen_for(self, command: ExternalDraftCommand) -> bool:
        """Fail closed unless the receipt and exact command both verify as safe."""

        try:
            self.assert_matches_command(command)
        except ValueError:
            return True
        return not self._observation_is_candidate_safe()

    def requires_human_review_for(self, command: ExternalDraftCommand) -> bool:
        return self.is_frozen_for(command)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "receipt_id": self.receipt_id,
            "draft_command_id": self.draft_command_id,
            "draft_command_sha256": self.draft_command_sha256,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "case_id": self.case_id,
            "connection_id": self.connection_id,
            "connection_revision": self.connection_revision,
            "connection_sha256": self.connection_sha256,
            "provider_id": self.provider_id,
            "environment": self.environment.value,
            "payload_sha256": self.payload_sha256,
            "idempotency_key": self.idempotency_key,
            "provider_reference": self.provider_reference,
            "provider_response_sha256": self.provider_response_sha256,
            "readback_sha256": self.readback_sha256,
            "readback_status": self.readback_status.value,
            "observed_state": self.observed_state.value,
            "comparison_status": self.comparison_status.value,
            "attempted_at": datetime_to_wire(self.attempted_at),
            "readback_at": datetime_to_wire(self.readback_at),
            "recorded_at": datetime_to_wire(self.recorded_at),
        }

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "ExternalDraftReceipt")

    @classmethod
    def from_dict(cls, value: object) -> ExternalDraftReceipt:
        payload = require_wire_object(
            value,
            contract_name="ExternalDraftReceipt",
            expected_fields=_RECEIPT_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        return cls(
            receipt_id=payload["receipt_id"],
            draft_command_id=payload["draft_command_id"],
            draft_command_sha256=payload["draft_command_sha256"],
            tenant_id=payload["tenant_id"],
            client_id=payload["client_id"],
            legal_entity_id=payload["legal_entity_id"],
            case_id=payload["case_id"],
            connection_id=payload["connection_id"],
            connection_revision=payload["connection_revision"],
            connection_sha256=payload["connection_sha256"],
            provider_id=payload["provider_id"],
            environment=payload["environment"],
            payload_sha256=payload["payload_sha256"],
            idempotency_key=payload["idempotency_key"],
            provider_reference=payload["provider_reference"],
            provider_response_sha256=payload["provider_response_sha256"],
            readback_sha256=payload["readback_sha256"],
            readback_status=payload["readback_status"],
            observed_state=payload["observed_state"],
            comparison_status=payload["comparison_status"],
            attempted_at=parse_wire_datetime(payload["attempted_at"], "attempted_at"),
            readback_at=parse_wire_datetime(payload["readback_at"], "readback_at"),
            recorded_at=parse_wire_datetime(payload["recorded_at"], "recorded_at"),
        )

    @classmethod
    def from_json(cls, value: object) -> ExternalDraftReceipt:
        return cls.from_dict(parse_json_object(value, "ExternalDraftReceipt"))

    def assert_matches_command(self, command: ExternalDraftCommand) -> None:
        if not isinstance(command, ExternalDraftCommand):
            raise ValueError("command must be an ExternalDraftCommand")
        expected_values = {
            "draft_command_id": command.draft_command_id,
            "draft_command_sha256": command.canonical_sha256(),
            **{field_name: getattr(command, field_name) for field_name in _DRAFT_SCOPE_FIELDS},
        }
        for field_name, expected_value in expected_values.items():
            if getattr(self, field_name) != expected_value:
                raise ValueError(f"receipt does not match exact draft command {field_name}")
        if not command.created_at <= self.attempted_at <= command.expires_at:
            raise ValueError("draft attempt must occur within the valid command window")


__all__ = [
    "ApprovalDecisionCommand",
    "ApprovalDecisionOutcome",
    "DraftComparisonStatus",
    "DraftReadbackStatus",
    "ExternalDraftCommand",
    "ExternalDraftObservedState",
    "ExternalDraftReceipt",
    "ExternalDraftRecordType",
]
