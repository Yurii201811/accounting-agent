"""Optional Ed25519 signing for canonical synthetic Edge Worker results."""

from __future__ import annotations

import hashlib
import json
import threading
from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from accounting_agent.contracts import SignatureAlgorithm
from accounting_agent.contracts._wire import (
    datetime_to_wire,
    require_base64,
    require_identifier,
    require_sha256,
    require_utc_datetime,
)

from .contracts import EdgeAdvisoryJobV1, EdgeAdvisoryResultV1


_SIGNATURE_STATEMENT_SCHEMA = "accounting-agent.edge-result-signature.v1"
_SIGNATURE_STATEMENT_PURPOSE = "edge-advisory-result-attestation"
_REPLAY_STATEMENT_SCHEMA = "accounting-agent.edge-result-replay.v1"
_REPLAY_STATEMENT_PURPOSE = "edge-advisory-result-consumption"
_SIGNER_KEY_IDENTITY_DOMAIN = b"accounting-agent.ed25519-public-key.v1\x00"


class EdgeResultVerificationError(ValueError):
    """A signed result failed cryptographic or exact-scope verification."""


class EdgeResultReplayError(EdgeResultVerificationError):
    """A verified local result was consumed more than once in this process."""


class EdgeResultSigner(Protocol):
    key_reference: str
    algorithm: SignatureAlgorithm

    def sign(self, payload: bytes) -> bytes: ...


class EdgeResultVerifier(Protocol):
    key_reference: str
    algorithm: SignatureAlgorithm

    def verify(self, signature: bytes, payload: bytes) -> None: ...


def _ed25519_types() -> tuple[Any, Any, Any, Any, type[Exception]]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as error:
        raise RuntimeError(
            "Ed25519 support requires the accounting-agent[edge] optional dependency"
        ) from error
    return (
        Ed25519PrivateKey,
        Ed25519PublicKey,
        serialization.Encoding,
        serialization.PublicFormat,
        InvalidSignature,
    )


class LocalEd25519Signer:
    """In-memory local signer; key provisioning remains outside this package."""

    __slots__ = ("_private_key", "key_reference")
    algorithm = SignatureAlgorithm.ED25519

    def __init__(self, *, key_reference: str, private_key_bytes: bytes) -> None:
        self.key_reference = require_identifier(key_reference, "key_reference")
        if not isinstance(private_key_bytes, bytes) or len(private_key_bytes) != 32:
            raise ValueError("private_key_bytes must contain exactly 32 bytes")
        private_key_type, _, _, _, _ = _ed25519_types()
        self._private_key = private_key_type.from_private_bytes(private_key_bytes)

    def sign(self, payload: bytes) -> bytes:
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("signed payload must be non-empty bytes")
        return self._private_key.sign(payload)

    def public_verifier(self) -> LocalEd25519Verifier:
        _, _, encoding, public_format, _ = _ed25519_types()
        public_key_bytes = self._private_key.public_key().public_bytes(
            encoding.Raw,
            public_format.Raw,
        )
        return LocalEd25519Verifier(
            key_reference=self.key_reference,
            public_key_bytes=public_key_bytes,
        )


class LocalEd25519Verifier:
    """Public-key-only verifier for one exact local signing identity."""

    __slots__ = ("_key_identity_sha256", "_public_key", "key_reference")
    algorithm = SignatureAlgorithm.ED25519

    def __init__(self, *, key_reference: str, public_key_bytes: bytes) -> None:
        self.key_reference = require_identifier(key_reference, "key_reference")
        if not isinstance(public_key_bytes, bytes) or len(public_key_bytes) != 32:
            raise ValueError("public_key_bytes must contain exactly 32 bytes")
        _, public_key_type, _, _, _ = _ed25519_types()
        self._public_key = public_key_type.from_public_bytes(public_key_bytes)
        self._key_identity_sha256 = hashlib.sha256(
            _SIGNER_KEY_IDENTITY_DOMAIN + public_key_bytes
        ).hexdigest()

    def verify(self, signature: bytes, payload: bytes) -> None:
        if not isinstance(signature, bytes) or not isinstance(payload, bytes) or not payload:
            raise EdgeResultVerificationError("edge result signature input is invalid")
        *_, invalid_signature = _ed25519_types()
        try:
            self._public_key.verify(signature, payload)
        except invalid_signature as error:
            raise EdgeResultVerificationError("edge result signature is invalid") from error


@dataclass(frozen=True)
class EdgeResultSignature:
    key_reference: str
    algorithm: SignatureAlgorithm
    signed_payload_sha256: str
    signature_base64: str
    signed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "key_reference",
            require_identifier(self.key_reference, "key_reference"),
        )
        try:
            algorithm = SignatureAlgorithm(self.algorithm)
        except (TypeError, ValueError) as error:
            raise ValueError("unknown edge result signature algorithm") from error
        if algorithm is not SignatureAlgorithm.ED25519:
            raise ValueError("the local Edge Worker foundation permits Ed25519 only")
        object.__setattr__(self, "algorithm", algorithm)
        require_sha256(self.signed_payload_sha256, "signed_payload_sha256")
        require_base64(self.signature_base64, "signature_base64", minimum_bytes=64)
        if len(b64decode(self.signature_base64, validate=True)) != 64:
            raise ValueError("Ed25519 signatures must contain exactly 64 bytes")
        require_utc_datetime(self.signed_at, "signed_at")

    def to_dict(self) -> dict[str, str]:
        return {
            "key_reference": self.key_reference,
            "algorithm": self.algorithm.value,
            "signed_payload_sha256": self.signed_payload_sha256,
            "signature_base64": self.signature_base64,
            "signed_at": datetime_to_wire(self.signed_at),
        }


@dataclass(frozen=True)
class SignedEdgeAdvisoryResultV1:
    result: EdgeAdvisoryResultV1
    signature: EdgeResultSignature

    def __post_init__(self) -> None:
        if not isinstance(self.result, EdgeAdvisoryResultV1):
            raise TypeError("result must be an EdgeAdvisoryResultV1")
        if not isinstance(self.signature, EdgeResultSignature):
            raise TypeError("signature must be an EdgeResultSignature")
        if self.signature.signed_payload_sha256 != self.result.canonical_digest:
            raise ValueError("edge result signature hash does not match the result")
        if self.signature.signed_at < self.result.completed_at:
            raise ValueError("edge result signature cannot precede result completion")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "v1",
            "result": self.result.to_dict(),
            "signature": self.signature.to_dict(),
        }


def canonical_result_bytes(result: EdgeAdvisoryResultV1) -> bytes:
    if not isinstance(result, EdgeAdvisoryResultV1):
        raise TypeError("result must be an EdgeAdvisoryResultV1")
    return json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_signature_statement_bytes(
    *,
    result_digest: str,
    key_reference: str,
    algorithm: SignatureAlgorithm,
    signed_at: datetime,
) -> bytes:
    require_sha256(result_digest, "result_digest")
    key_reference = require_identifier(key_reference, "key_reference")
    if algorithm is not SignatureAlgorithm.ED25519:
        raise ValueError("the local Edge Worker foundation permits Ed25519 only")
    require_utc_datetime(signed_at, "signed_at")
    return json.dumps(
        {
            "algorithm": algorithm.value,
            "key_reference": key_reference,
            "purpose": _SIGNATURE_STATEMENT_PURPOSE,
            "result_digest": result_digest,
            "schema": _SIGNATURE_STATEMENT_SCHEMA,
            "signed_at": datetime_to_wire(signed_at),
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _stable_replay_key(*, result_digest: str, signer_key_identity: str) -> str:
    require_sha256(result_digest, "result_digest")
    require_sha256(signer_key_identity, "signer_key_identity")
    statement = json.dumps(
        {
            "purpose": _REPLAY_STATEMENT_PURPOSE,
            "result_digest": result_digest,
            "schema": _REPLAY_STATEMENT_SCHEMA,
            "signer_key_identity_sha256": signer_key_identity,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(statement).hexdigest()


def sign_edge_result(
    result: EdgeAdvisoryResultV1,
    signer: EdgeResultSigner,
    *,
    signed_at: datetime,
) -> SignedEdgeAdvisoryResultV1:
    if not isinstance(result, EdgeAdvisoryResultV1):
        raise TypeError("result must be an EdgeAdvisoryResultV1")
    require_utc_datetime(signed_at, "signed_at")
    if signer.algorithm is not SignatureAlgorithm.ED25519:
        raise ValueError("the local Edge Worker foundation permits Ed25519 only")
    key_reference = require_identifier(signer.key_reference, "key_reference")
    statement = _canonical_signature_statement_bytes(
        result_digest=result.canonical_digest,
        key_reference=key_reference,
        algorithm=signer.algorithm,
        signed_at=signed_at,
    )
    signature = signer.sign(statement)
    return SignedEdgeAdvisoryResultV1(
        result=result,
        signature=EdgeResultSignature(
            key_reference=key_reference,
            algorithm=signer.algorithm,
            signed_payload_sha256=result.canonical_digest,
            signature_base64=b64encode(signature).decode("ascii"),
            signed_at=signed_at,
        ),
    )


class LocalEdgeReplayGuard:
    """Process-local synthetic replay guard; not a durable production control."""

    __slots__ = ("_lock", "_seen")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def consume(self, replay_key: str) -> None:
        require_sha256(replay_key, "replay_key")
        with self._lock:
            if replay_key in self._seen:
                raise EdgeResultReplayError("verified edge result replay detected")
            self._seen.add(replay_key)


def verify_signed_edge_result(
    signed: SignedEdgeAdvisoryResultV1,
    verifier: LocalEd25519Verifier,
    *,
    expected_job: EdgeAdvisoryJobV1,
    replay_guard: LocalEdgeReplayGuard,
) -> EdgeAdvisoryResultV1:
    if not isinstance(signed, SignedEdgeAdvisoryResultV1):
        raise TypeError("signed must be a SignedEdgeAdvisoryResultV1")
    if not isinstance(verifier, LocalEd25519Verifier):
        raise TypeError("verifier must be a LocalEd25519Verifier")
    if not isinstance(replay_guard, LocalEdgeReplayGuard):
        raise TypeError("replay_guard must be a LocalEdgeReplayGuard")
    try:
        signed.result.assert_matches_job(expected_job)
    except (TypeError, ValueError) as error:
        raise EdgeResultVerificationError("edge result scope or job binding is invalid") from error
    if (
        verifier.algorithm is not signed.signature.algorithm
        or verifier.key_reference != signed.signature.key_reference
    ):
        raise EdgeResultVerificationError("edge result signature identity is invalid")
    try:
        if signed.signature.signed_payload_sha256 != signed.result.canonical_digest:
            raise ValueError("signed result digest does not match the result")
        if signed.signature.signed_at < signed.result.completed_at:
            raise ValueError("signature timestamp precedes result completion")
        statement = _canonical_signature_statement_bytes(
            result_digest=signed.signature.signed_payload_sha256,
            key_reference=signed.signature.key_reference,
            algorithm=signed.signature.algorithm,
            signed_at=signed.signature.signed_at,
        )
        signature_bytes = b64decode(
            signed.signature.signature_base64,
            validate=True,
        )
    except (TypeError, ValueError) as error:
        raise EdgeResultVerificationError(
            "edge result signature metadata is invalid"
        ) from error
    verifier.verify(
        signature_bytes,
        statement,
    )
    if (
        signed.result.completed_at >= expected_job.deadline
        or signed.signature.signed_at >= expected_job.deadline
    ):
        raise EdgeResultVerificationError("edge result exceeded the expected job deadline")
    if len(signed.result.payload_json.encode("utf-8")) > expected_job.budget.max_response_bytes:
        raise EdgeResultVerificationError("edge result exceeds the expected response budget")
    if signed.result.latency_ms > expected_job.budget.timeout_seconds * 1_000:
        raise EdgeResultVerificationError("edge result exceeds the expected timeout budget")
    replay_key = _stable_replay_key(
        result_digest=signed.result.canonical_digest,
        signer_key_identity=verifier._key_identity_sha256,
    )
    replay_guard.consume(replay_key)
    return signed.result


__all__ = [
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
]
