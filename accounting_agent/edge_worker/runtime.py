"""Single-job local advisory runtime with a deliberately empty tool inventory."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Callable

from accounting_agent.contracts import SignatureAlgorithm
from accounting_agent.contracts._wire import (
    datetime_to_wire,
    require_identifier,
    require_utc_datetime,
)
from accounting_agent.model_runtime import (
    ProviderId,
    invoke_local_openai_compatible_advisory,
    invoke_ollama_advisory,
)

from .contracts import EdgeAdvisoryJobV1, EdgeAdvisoryResultV1
from .signing import EdgeResultSigner, SignedEdgeAdvisoryResultV1, sign_edge_result


class EdgeJobExpired(PermissionError):
    """The exact synthetic advisory job is no longer eligible to run."""


class EdgeJobBudgetExceeded(PermissionError):
    """The provider result exceeded the immutable job budget."""


def edge_worker_authority_manifest() -> dict[str, object]:
    """Return the immutable-by-construction authority ceiling for this runtime."""

    return {
        "schema_version": "v1",
        "providers": [
            ProviderId.OLLAMA.value,
            ProviderId.LOCAL_OPENAI_COMPATIBLE.value,
        ],
        "allowed_capabilities": ["model_advisory"],
        "tool_inventory": [],
        "network_scope": "localhost_only",
        "synthetic_only": True,
        "advisory_only": True,
        "requires_deterministic_validation": True,
        "may_approve": False,
        "may_execute": False,
        "forbidden_capabilities": [
            "erp_credentials",
            "connector_calls",
            "mcp_tools",
            "computer_use",
            "subprocess",
            "external_writes",
            "approve",
            "post",
            "send",
            "pay",
            "file_tax",
            "delete",
            "change_settings",
        ],
    }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_edge_advisory_job(
    *,
    job: EdgeAdvisoryJobV1,
    signer: EdgeResultSigner,
    endpoint: str,
    allow_local_invocation: bool = False,
    opener: Callable[..., Any] | None = None,
    clock: Callable[[], datetime] = _utc_now,
) -> SignedEdgeAdvisoryResultV1:
    """Run one bounded local model call and sign its still-advisory result."""

    if not isinstance(job, EdgeAdvisoryJobV1):
        raise TypeError("job must be an EdgeAdvisoryJobV1")
    if allow_local_invocation is not True:
        raise PermissionError("explicit local invocation opt-in is required")
    try:
        signer_algorithm = signer.algorithm
        signer_key_reference = signer.key_reference
        signer_callback = signer.sign
    except AttributeError as error:
        raise TypeError("signer must implement the EdgeResultSigner contract") from error
    if signer_algorithm is not SignatureAlgorithm.ED25519 or not callable(signer_callback):
        raise TypeError("signer must implement the Ed25519 EdgeResultSigner contract")
    require_identifier(signer_key_reference, "signer key_reference")
    started_at = clock()
    require_utc_datetime(started_at, "clock result")
    if started_at >= job.deadline:
        raise EdgeJobExpired("edge advisory job deadline has passed")

    invocation: Callable[..., Any]
    if job.provider_id is ProviderId.OLLAMA:
        invocation = invoke_ollama_advisory
    elif job.provider_id is ProviderId.LOCAL_OPENAI_COMPATIBLE:
        invocation = invoke_local_openai_compatible_advisory
    else:  # defensive; the immutable job contract already rejects this
        raise PermissionError("edge advisory provider is not available")
    invocation_kwargs: dict[str, Any] = {
        "request_id": job.request_id,
        "model_id": job.model_id,
        "purpose": job.purpose,
        "data_classification": job.data_classification,
        "prompt": job.prompt,
        "endpoint": endpoint,
        "allow_local_invocation": True,
        "max_prompt_bytes": job.budget.max_prompt_bytes,
        "max_response_bytes": job.budget.max_response_bytes,
        "timeout_seconds": job.budget.timeout_seconds,
    }
    if opener is not None:
        invocation_kwargs["opener"] = opener
    provider_result = invocation(**invocation_kwargs)
    if len(provider_result.payload_json.encode("utf-8")) > job.budget.max_response_bytes:
        raise EdgeJobBudgetExceeded("edge provider result exceeded the response budget")
    if provider_result.latency_ms > job.budget.timeout_seconds * 1_000:
        raise EdgeJobBudgetExceeded("edge provider result exceeded the timeout budget")

    completed_at = clock()
    require_utc_datetime(completed_at, "clock result")
    if completed_at >= job.deadline:
        raise EdgeJobExpired("edge advisory job exceeded its deadline")
    result_identity = hashlib.sha256(
        (
            job.canonical_digest
            + provider_result.payload_hash
            + datetime_to_wire(completed_at)
        ).encode("utf-8")
    ).hexdigest()
    result = EdgeAdvisoryResultV1(
        result_id=f"edge-result-{result_identity[:24]}",
        job_id=job.job_id,
        job_digest=job.canonical_digest,
        request_id=job.request_id,
        tenant_id=job.tenant_id,
        client_id=job.client_id,
        legal_entity_id=job.legal_entity_id,
        case_id=job.case_id,
        evidence_sha256=job.evidence_sha256,
        provider_id=job.provider_id,
        model_id=job.model_id,
        purpose=job.purpose,
        data_classification=job.data_classification,
        prompt_sha256=job.prompt_sha256,
        payload_json=provider_result.payload_json,
        latency_ms=provider_result.latency_ms,
        endpoint=provider_result.endpoint,
        completed_at=completed_at,
    )
    result.assert_matches_job(job)
    return sign_edge_result(result, signer, signed_at=completed_at)


__all__ = [
    "EdgeJobExpired",
    "EdgeJobBudgetExceeded",
    "edge_worker_authority_manifest",
    "run_edge_advisory_job",
]
