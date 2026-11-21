"""Bounded local advisory Edge Worker contracts and runtime."""

from .contracts import (
    EDGE_ADVISORY_CAPABILITY,
    EdgeAdvisoryBudget,
    EdgeAdvisoryJobV1,
    EdgeAdvisoryResultV1,
)
from .signing import (
    EdgeResultReplayError,
    EdgeResultSignature,
    EdgeResultSigner,
    EdgeResultVerificationError,
    EdgeResultVerifier,
    LocalEd25519Signer,
    LocalEd25519Verifier,
    LocalEdgeReplayGuard,
    SignedEdgeAdvisoryResultV1,
    canonical_result_bytes,
    sign_edge_result,
    verify_signed_edge_result,
)
from .runtime import (
    EdgeJobBudgetExceeded,
    EdgeJobExpired,
    edge_worker_authority_manifest,
    run_edge_advisory_job,
)

__all__ = [
    "EDGE_ADVISORY_CAPABILITY",
    "EdgeAdvisoryBudget",
    "EdgeAdvisoryJobV1",
    "EdgeAdvisoryResultV1",
    "EdgeJobExpired",
    "EdgeJobBudgetExceeded",
    "EdgeResultReplayError",
    "EdgeResultSignature",
    "EdgeResultSigner",
    "EdgeResultVerificationError",
    "EdgeResultVerifier",
    "LocalEd25519Signer",
    "LocalEd25519Verifier",
    "LocalEdgeReplayGuard",
    "SignedEdgeAdvisoryResultV1",
    "canonical_result_bytes",
    "sign_edge_result",
    "verify_signed_edge_result",
    "edge_worker_authority_manifest",
    "run_edge_advisory_job",
]
