"""Fail-closed tenant policy for advisory model routing.

The contract records which single provider a tenant has qualified. It contains
no credentials, provider client, network behavior, automatic fallback, approval
authority, or accounting execution authority. Runtime availability is checked
outside this data contract and an unavailable provider must cause a visible
stop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar

from accounting_agent.model_runtime import (
    DataClassification,
    ModelPurpose,
    ProviderId,
    get_provider_manifest,
)

from ._wire import (
    canonical_json_sha256,
    datetime_to_wire,
    parse_enum,
    parse_json_object,
    parse_wire_datetime,
    require_identifier,
    require_positive_integer,
    require_sha256,
    require_tuple,
    require_utc_datetime,
    require_wire_array,
    require_wire_object,
    require_wire_version,
)


class ProcessingRegion(str, Enum):
    LOCAL_DEVICE = "local_device"
    SWEDEN = "se"
    EUROPEAN_UNION = "eu"


class RedactionMode(str, Enum):
    NONE = "none"
    STRUCTURED_MINIMIZATION = "structured_minimization"
    PSEUDONYMIZATION = "pseudonymization"
    METADATA_ONLY = "metadata_only"


_HOSTED_PROVIDERS = frozenset(
    {
        ProviderId.OPENAI,
        ProviderId.ANTHROPIC,
        ProviderId.GEMINI,
        ProviderId.CODEX_WORKSPACE,
    }
)
_LOCAL_PROVIDERS = frozenset(
    {
        ProviderId.DETERMINISTIC,
        ProviderId.OLLAMA,
        ProviderId.LOCAL_OPENAI_COMPATIBLE,
    }
)
_SENSITIVE_HOSTED_CLASSIFICATIONS = frozenset(
    {
        DataClassification.CONFIDENTIAL_ACCOUNTING,
        DataClassification.PERSONAL_DATA,
    }
)
_REDACTION_STRENGTH = {
    RedactionMode.NONE: 0,
    RedactionMode.STRUCTURED_MINIMIZATION: 1,
    RedactionMode.PSEUDONYMIZATION: 2,
    RedactionMode.METADATA_ONLY: 3,
}
_POLICY_FIELDS = frozenset(
    {
        "schema_version",
        "policy_id",
        "policy_version",
        "tenant_id",
        "provider_id",
        "purposes",
        "classifications",
        "processing_region",
        "max_retention_days",
        "redaction_mode",
        "max_requests",
        "max_input_tokens",
        "max_output_tokens",
        "max_cost_minor",
        "cost_currency",
        "consent_actor_id",
        "consented_at",
        "consent_evidence_sha256",
        "dpa_sha256",
        "subprocessor_review_sha256",
        "evaluation_sha256",
        "no_training_required",
        "expires_at",
        "silent_fallback_allowed",
        "can_approve",
        "can_execute",
    }
)
_EnumT = TypeVar("_EnumT", bound=Enum)


def _require_nonnegative_integer(value: object, field_name: str) -> int:
    return require_positive_integer(value, field_name, allow_zero=True)


def _require_currency(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("cost_currency must be an uppercase three-letter code")
    return value


def _require_false(value: object, field_name: str) -> bool:
    if type(value) is not bool or value:
        raise ValueError(f"{field_name} must be false")
    return value


def _require_true(value: object, field_name: str) -> bool:
    if type(value) is not bool or not value:
        raise ValueError(f"{field_name} must be true")
    return value


def _parse_unique_enum_tuple(
    value: object,
    enum_type: type[_EnumT],
    field_name: str,
) -> tuple[_EnumT, ...]:
    values = require_tuple(value, field_name)
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    parsed = tuple(parse_enum(item, enum_type, field_name) for item in values)
    if len(parsed) != len(set(parsed)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(parsed, key=lambda item: str(item.value)))


def _require_optional_sha256(value: object, field_name: str) -> str:
    if value == "":
        return ""
    return require_sha256(value, field_name)


@dataclass(frozen=True)
class ModelRoutePolicy:
    """One tenant-approved provider route with bounded advisory capability."""

    policy_id: str
    policy_version: int
    tenant_id: str
    provider_id: ProviderId
    purposes: tuple[ModelPurpose, ...]
    classifications: tuple[DataClassification, ...]
    processing_region: ProcessingRegion
    max_retention_days: int
    redaction_mode: RedactionMode
    max_requests: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_minor: int
    cost_currency: str
    consent_actor_id: str
    consented_at: datetime
    consent_evidence_sha256: str
    dpa_sha256: str
    subprocessor_review_sha256: str
    evaluation_sha256: str
    no_training_required: bool
    expires_at: datetime
    silent_fallback_allowed: bool
    can_approve: bool
    can_execute: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", require_identifier(self.policy_id, "policy_id"))
        require_positive_integer(self.policy_version, "policy_version")
        object.__setattr__(self, "tenant_id", require_identifier(self.tenant_id, "tenant_id"))
        provider = parse_enum(self.provider_id, ProviderId, "provider_id")
        object.__setattr__(self, "provider_id", provider)
        purposes = _parse_unique_enum_tuple(self.purposes, ModelPurpose, "purposes")
        classifications = _parse_unique_enum_tuple(
            self.classifications,
            DataClassification,
            "classifications",
        )
        object.__setattr__(self, "purposes", purposes)
        object.__setattr__(self, "classifications", classifications)
        region = parse_enum(self.processing_region, ProcessingRegion, "processing_region")
        object.__setattr__(self, "processing_region", region)
        redaction = parse_enum(self.redaction_mode, RedactionMode, "redaction_mode")
        object.__setattr__(self, "redaction_mode", redaction)
        for field_name in (
            "max_retention_days",
            "max_requests",
            "max_input_tokens",
            "max_output_tokens",
            "max_cost_minor",
        ):
            _require_nonnegative_integer(getattr(self, field_name), field_name)
        object.__setattr__(self, "cost_currency", _require_currency(self.cost_currency))
        object.__setattr__(
            self,
            "consent_actor_id",
            require_identifier(self.consent_actor_id, "consent_actor_id"),
        )
        require_utc_datetime(self.consented_at, "consented_at")
        require_sha256(self.consent_evidence_sha256, "consent_evidence_sha256")
        require_utc_datetime(self.expires_at, "expires_at")
        if self.expires_at <= self.consented_at:
            raise ValueError("expires_at must be later than consented_at")
        dpa_hash = _require_optional_sha256(self.dpa_sha256, "dpa_sha256")
        subprocessor_hash = _require_optional_sha256(
            self.subprocessor_review_sha256,
            "subprocessor_review_sha256",
        )
        require_sha256(self.evaluation_sha256, "evaluation_sha256")
        _require_true(self.no_training_required, "no_training_required")
        _require_false(self.silent_fallback_allowed, "silent_fallback_allowed")
        _require_false(self.can_approve, "can_approve")
        _require_false(self.can_execute, "can_execute")
        self._validate_provider_boundary(dpa_hash, subprocessor_hash)

    def _validate_provider_boundary(self, dpa_hash: str, subprocessor_hash: str) -> None:
        if DataClassification.CREDENTIAL_OR_SECRET in self.classifications:
            raise ValueError("credentials and secrets are forbidden from every model route")
        if (
            DataClassification.PRIVATE_COURSE in self.classifications
            and self.provider_id not in _LOCAL_PROVIDERS
        ):
            raise ValueError("private course material is restricted to local providers")
        manifest = get_provider_manifest(self.provider_id)
        unsupported = set(self.classifications) - set(manifest.supported_classifications)
        if unsupported:
            raise ValueError(
                f"provider does not support classification: {min(item.value for item in unsupported)}"
            )
        if self.provider_id in _HOSTED_PROVIDERS:
            if self.processing_region is ProcessingRegion.LOCAL_DEVICE:
                raise ValueError("hosted providers require an explicit nonlocal processing region")
            if not dpa_hash:
                raise ValueError("hosted providers require DPA qualification evidence")
            if not subprocessor_hash:
                raise ValueError("hosted providers require subprocessor qualification evidence")
            if (
                set(self.classifications) & _SENSITIVE_HOSTED_CLASSIFICATIONS
                and self.redaction_mode is RedactionMode.NONE
            ):
                raise ValueError("sensitive hosted routes require redaction")
            return
        if self.processing_region is not ProcessingRegion.LOCAL_DEVICE:
            raise ValueError("local providers require local_device processing region")
        if dpa_hash:
            raise ValueError("local providers must not claim hosted DPA evidence")
        if subprocessor_hash:
            raise ValueError("local providers must not claim hosted subprocessor evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "tenant_id": self.tenant_id,
            "provider_id": self.provider_id.value,
            "purposes": [purpose.value for purpose in self.purposes],
            "classifications": [item.value for item in self.classifications],
            "processing_region": self.processing_region.value,
            "max_retention_days": self.max_retention_days,
            "redaction_mode": self.redaction_mode.value,
            "max_requests": self.max_requests,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_cost_minor": self.max_cost_minor,
            "cost_currency": self.cost_currency,
            "consent_actor_id": self.consent_actor_id,
            "consented_at": datetime_to_wire(self.consented_at),
            "consent_evidence_sha256": self.consent_evidence_sha256,
            "dpa_sha256": self.dpa_sha256,
            "subprocessor_review_sha256": self.subprocessor_review_sha256,
            "evaluation_sha256": self.evaluation_sha256,
            "no_training_required": self.no_training_required,
            "expires_at": datetime_to_wire(self.expires_at),
            "silent_fallback_allowed": self.silent_fallback_allowed,
            "can_approve": self.can_approve,
            "can_execute": self.can_execute,
        }

    def canonical_sha256(self) -> str:
        return canonical_json_sha256(self.to_dict(), "ModelRoutePolicy")

    @classmethod
    def from_dict(cls, value: object) -> ModelRoutePolicy:
        payload = require_wire_object(
            value,
            contract_name="ModelRoutePolicy",
            expected_fields=_POLICY_FIELDS,
        )
        require_wire_version(payload["schema_version"])
        purposes = require_wire_array(payload["purposes"], "purposes")
        classifications = require_wire_array(payload["classifications"], "classifications")
        return cls(
            policy_id=payload["policy_id"],
            policy_version=payload["policy_version"],
            tenant_id=payload["tenant_id"],
            provider_id=payload["provider_id"],
            purposes=tuple(purposes),
            classifications=tuple(classifications),
            processing_region=payload["processing_region"],
            max_retention_days=payload["max_retention_days"],
            redaction_mode=payload["redaction_mode"],
            max_requests=payload["max_requests"],
            max_input_tokens=payload["max_input_tokens"],
            max_output_tokens=payload["max_output_tokens"],
            max_cost_minor=payload["max_cost_minor"],
            cost_currency=payload["cost_currency"],
            consent_actor_id=payload["consent_actor_id"],
            consented_at=parse_wire_datetime(payload["consented_at"], "consented_at"),
            consent_evidence_sha256=payload["consent_evidence_sha256"],
            dpa_sha256=payload["dpa_sha256"],
            subprocessor_review_sha256=payload["subprocessor_review_sha256"],
            evaluation_sha256=payload["evaluation_sha256"],
            no_training_required=payload["no_training_required"],
            expires_at=parse_wire_datetime(payload["expires_at"], "expires_at"),
            silent_fallback_allowed=payload["silent_fallback_allowed"],
            can_approve=payload["can_approve"],
            can_execute=payload["can_execute"],
        )

    @classmethod
    def from_json(cls, value: object) -> ModelRoutePolicy:
        return cls.from_dict(parse_json_object(value, "ModelRoutePolicy"))

    def assert_successor_of(self, previous: ModelRoutePolicy) -> None:
        if not isinstance(previous, ModelRoutePolicy):
            raise ValueError("previous must be a ModelRoutePolicy")
        if self.policy_version != previous.policy_version + 1:
            raise ValueError("policy_version must advance by exactly one")
        for field_name in (
            "policy_id",
            "tenant_id",
            "provider_id",
            "processing_region",
            "cost_currency",
        ):
            if getattr(self, field_name) != getattr(previous, field_name):
                raise ValueError(f"policy successor cannot change {field_name}")
        if not set(self.purposes).issubset(previous.purposes):
            raise ValueError("policy successor cannot add purposes")
        if not set(self.classifications).issubset(previous.classifications):
            raise ValueError("policy successor cannot add classifications")
        for field_name in (
            "max_retention_days",
            "max_requests",
            "max_input_tokens",
            "max_output_tokens",
            "max_cost_minor",
        ):
            if getattr(self, field_name) > getattr(previous, field_name):
                raise ValueError(f"policy successor cannot increase {field_name}")
        if _REDACTION_STRENGTH[self.redaction_mode] < _REDACTION_STRENGTH[previous.redaction_mode]:
            raise ValueError("policy successor cannot weaken redaction")
        consent_changed = (
            self.consent_actor_id,
            self.consented_at,
            self.consent_evidence_sha256,
        ) != (
            previous.consent_actor_id,
            previous.consented_at,
            previous.consent_evidence_sha256,
        )
        if consent_changed and (
            self.consented_at <= previous.consented_at
            or self.consent_evidence_sha256 == previous.consent_evidence_sha256
        ):
            raise ValueError(
                "fresh consent requires a later timestamp and new authenticated evidence"
            )
        if self.expires_at > previous.expires_at:
            raise ValueError("policy successor cannot extend expires_at")


__all__ = [
    "ModelRoutePolicy",
    "ProcessingRegion",
    "RedactionMode",
]
