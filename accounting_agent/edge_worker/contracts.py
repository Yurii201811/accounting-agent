"""Immutable, synthetic-only contracts for local advisory Edge Worker jobs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from accounting_agent.contracts._wire import (
    canonical_json_sha256,
    datetime_to_wire,
    parse_enum,
    parse_json_object,
    require_identifier,
    require_positive_integer,
    require_sha256,
    require_tuple,
    require_utc_datetime,
)
from accounting_agent.model_runtime import DataClassification, ModelPurpose, ProviderId
from accounting_agent.model_runtime import local_model_endpoint


EDGE_ADVISORY_CAPABILITY: Final = "model_advisory"
_LOCAL_EDGE_PROVIDERS: Final = frozenset(
    {ProviderId.OLLAMA, ProviderId.LOCAL_OPENAI_COMPATIBLE}
)


@dataclass(frozen=True)
class EdgeAdvisoryBudget:
    """Hard byte and time ceilings applied before a local provider call."""

    max_prompt_bytes: int
    max_response_bytes: int
    timeout_seconds: int

    def __post_init__(self) -> None:
        require_positive_integer(self.max_prompt_bytes, "max_prompt_bytes")
        require_positive_integer(self.max_response_bytes, "max_response_bytes")
        require_positive_integer(self.timeout_seconds, "timeout_seconds")
        if self.max_prompt_bytes > 100_000:
            raise ValueError("max_prompt_bytes exceeds the Edge Worker ceiling")
        if self.max_response_bytes > 1_000_000:
            raise ValueError("max_response_bytes exceeds the Edge Worker ceiling")
        if self.timeout_seconds > 180:
            raise ValueError("timeout_seconds exceeds the Edge Worker ceiling")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_prompt_bytes": self.max_prompt_bytes,
            "max_response_bytes": self.max_response_bytes,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class EdgeAdvisoryJobV1:
    """One exact local advisory request with no tool or accounting authority."""

    job_id: str
    request_id: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    case_id: str
    evidence_sha256: tuple[str, ...]
    provider_id: ProviderId
    model_id: str
    purpose: ModelPurpose
    data_classification: DataClassification
    prompt: str = field(repr=False)
    budget: EdgeAdvisoryBudget
    deadline: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "job_id",
            "request_id",
            "tenant_id",
            "client_id",
            "legal_entity_id",
            "case_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        evidence = require_tuple(self.evidence_sha256, "evidence_sha256")
        if not evidence:
            raise ValueError("evidence_sha256 must not be empty")
        normalized_evidence = tuple(
            sorted(require_sha256(item, "evidence_sha256 item") for item in evidence)
        )
        if len(normalized_evidence) != len(set(normalized_evidence)):
            raise ValueError("evidence_sha256 must not contain duplicates")
        object.__setattr__(self, "evidence_sha256", normalized_evidence)
        provider = parse_enum(self.provider_id, ProviderId, "edge provider")
        if provider not in _LOCAL_EDGE_PROVIDERS:
            raise ValueError("Edge Worker supports only local advisory providers")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "purpose", parse_enum(self.purpose, ModelPurpose, "model purpose"))
        classification = parse_enum(
            self.data_classification,
            DataClassification,
            "data classification",
        )
        if classification is not DataClassification.PUBLIC_SYNTHETIC:
            raise ValueError("this Edge Worker foundation accepts public synthetic data only")
        object.__setattr__(self, "data_classification", classification)
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id must be non-empty")
        object.__setattr__(self, "model_id", self.model_id.strip())
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise ValueError("prompt must be non-empty")
        if not isinstance(self.budget, EdgeAdvisoryBudget):
            raise TypeError("budget must be an EdgeAdvisoryBudget")
        if len(self.prompt.encode("utf-8")) > self.budget.max_prompt_bytes:
            raise ValueError("prompt exceeds the Edge Worker job budget")
        require_utc_datetime(self.deadline, "deadline")

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()

    @property
    def tool_inventory(self) -> tuple[()]:
        return ()

    @property
    def may_approve(self) -> bool:
        return False

    @property
    def may_execute(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "job_id": self.job_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "case_id": self.case_id,
            "evidence_sha256": list(self.evidence_sha256),
            "provider_id": self.provider_id.value,
            "model_id": self.model_id,
            "purpose": self.purpose.value,
            "data_classification": self.data_classification.value,
            "prompt_sha256": self.prompt_sha256,
            "budget": self.budget.to_dict(),
            "deadline": datetime_to_wire(self.deadline),
            "capability": EDGE_ADVISORY_CAPABILITY,
            "tool_inventory": [],
            "advisory_only": True,
            "requires_deterministic_validation": True,
            "may_approve": False,
            "may_execute": False,
        }

    @property
    def canonical_digest(self) -> str:
        return canonical_json_sha256(self.to_dict(), "EdgeAdvisoryJobV1")


@dataclass(frozen=True)
class EdgeAdvisoryResultV1:
    """Canonical local model advice, still pending deterministic validation."""

    result_id: str
    job_id: str
    job_digest: str
    request_id: str
    tenant_id: str
    client_id: str
    legal_entity_id: str
    case_id: str
    evidence_sha256: tuple[str, ...]
    provider_id: ProviderId
    model_id: str
    purpose: ModelPurpose
    data_classification: DataClassification
    prompt_sha256: str
    payload_json: str = field(repr=False)
    latency_ms: int
    endpoint: str
    completed_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "result_id",
            "job_id",
            "request_id",
            "tenant_id",
            "client_id",
            "legal_entity_id",
            "case_id",
        ):
            object.__setattr__(
                self,
                field_name,
                require_identifier(getattr(self, field_name), field_name),
            )
        require_sha256(self.job_digest, "job_digest")
        evidence = require_tuple(self.evidence_sha256, "evidence_sha256")
        normalized_evidence = tuple(
            sorted(require_sha256(item, "evidence_sha256 item") for item in evidence)
        )
        if not normalized_evidence or len(normalized_evidence) != len(set(normalized_evidence)):
            raise ValueError("evidence_sha256 must be non-empty and unique")
        object.__setattr__(self, "evidence_sha256", normalized_evidence)
        provider = parse_enum(self.provider_id, ProviderId, "edge result provider")
        if provider not in _LOCAL_EDGE_PROVIDERS:
            raise ValueError("Edge Worker results support only local advisory providers")
        object.__setattr__(self, "provider_id", provider)
        object.__setattr__(self, "purpose", parse_enum(self.purpose, ModelPurpose, "model purpose"))
        classification = parse_enum(
            self.data_classification,
            DataClassification,
            "data classification",
        )
        if classification is not DataClassification.PUBLIC_SYNTHETIC:
            raise ValueError("Edge Worker results accept public synthetic data only")
        object.__setattr__(self, "data_classification", classification)
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("model_id must be non-empty")
        object.__setattr__(self, "model_id", self.model_id.strip())
        require_sha256(self.prompt_sha256, "prompt_sha256")
        payload = parse_json_object(self.payload_json, "EdgeAdvisoryResultV1 payload")
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical_json_sha256(payload, "EdgeAdvisoryResultV1 payload")
        object.__setattr__(self, "payload_json", canonical_payload)
        require_positive_integer(self.latency_ms, "latency_ms", allow_zero=True)
        object.__setattr__(self, "endpoint", local_model_endpoint(self.endpoint))
        require_utc_datetime(self.completed_at, "completed_at")

    @property
    def payload(self) -> dict[str, Any]:
        parsed = json.loads(self.payload_json)
        if not isinstance(parsed, dict):
            raise RuntimeError("stored edge result payload is not a JSON object")
        return parsed

    @property
    def payload_sha256(self) -> str:
        return hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()

    @property
    def validation_status(self) -> str:
        return "pending_deterministic_validation"

    @property
    def tool_inventory(self) -> tuple[()]:
        return ()

    @property
    def may_approve(self) -> bool:
        return False

    @property
    def may_execute(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "v1",
            "result_id": self.result_id,
            "job_id": self.job_id,
            "job_digest": self.job_digest,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "client_id": self.client_id,
            "legal_entity_id": self.legal_entity_id,
            "case_id": self.case_id,
            "evidence_sha256": list(self.evidence_sha256),
            "provider_id": self.provider_id.value,
            "model_id": self.model_id,
            "purpose": self.purpose.value,
            "data_classification": self.data_classification.value,
            "prompt_sha256": self.prompt_sha256,
            "payload": self.payload,
            "payload_sha256": self.payload_sha256,
            "latency_ms": self.latency_ms,
            "endpoint": self.endpoint,
            "completed_at": datetime_to_wire(self.completed_at),
            "validation_status": self.validation_status,
            "capability": EDGE_ADVISORY_CAPABILITY,
            "tool_inventory": [],
            "advisory_only": True,
            "requires_deterministic_validation": True,
            "may_approve": False,
            "may_execute": False,
        }

    @property
    def canonical_digest(self) -> str:
        return canonical_json_sha256(self.to_dict(), "EdgeAdvisoryResultV1")

    def assert_matches_job(self, job: EdgeAdvisoryJobV1) -> None:
        if not isinstance(job, EdgeAdvisoryJobV1):
            raise TypeError("job must be an EdgeAdvisoryJobV1")
        actual = (
            self.job_id,
            self.job_digest,
            self.request_id,
            self.tenant_id,
            self.client_id,
            self.legal_entity_id,
            self.case_id,
            self.evidence_sha256,
            self.provider_id,
            self.model_id,
            self.purpose,
            self.data_classification,
            self.prompt_sha256,
        )
        expected = (
            job.job_id,
            job.canonical_digest,
            job.request_id,
            job.tenant_id,
            job.client_id,
            job.legal_entity_id,
            job.case_id,
            job.evidence_sha256,
            job.provider_id,
            job.model_id,
            job.purpose,
            job.data_classification,
            job.prompt_sha256,
        )
        if actual != expected:
            raise ValueError("edge result scope or job binding does not match")


__all__ = [
    "EDGE_ADVISORY_CAPABILITY",
    "EdgeAdvisoryBudget",
    "EdgeAdvisoryJobV1",
    "EdgeAdvisoryResultV1",
]
