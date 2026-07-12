from __future__ import annotations

import importlib.util
import json
import ast
import tomllib
import unittest
from base64 import b64encode
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accounting_agent.model_runtime import DataClassification, ModelPurpose, ProviderId


ROOT = Path(__file__).resolve().parents[1]


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self._payload[:limit]


class EdgeWorkerPackageTests(unittest.TestCase):
    def test_public_edge_worker_package_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("accounting_agent.edge_worker"))

    def test_job_contract_binds_exact_scope_evidence_prompt_provider_and_budget(self) -> None:
        from accounting_agent import edge_worker

        budget_type = getattr(edge_worker, "EdgeAdvisoryBudget", None)
        job_type = getattr(edge_worker, "EdgeAdvisoryJobV1", None)
        self.assertIsNotNone(budget_type)
        self.assertIsNotNone(job_type)
        budget = budget_type(
            max_prompt_bytes=4_096,
            max_response_bytes=8_192,
            timeout_seconds=30,
        )
        job = job_type(
            job_id="job-edge-00000001",
            request_id="request-edge-00000001",
            tenant_id="tenant-synthetic",
            client_id="client-synthetic",
            legal_entity_id="entity-synthetic",
            case_id="case-synthetic",
            evidence_sha256=("b" * 64, "a" * 64),
            provider_id=ProviderId.OLLAMA,
            model_id="qwen3:4b",
            purpose=ModelPurpose.CLASSIFICATION,
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            prompt="Classify this generated synthetic invoice fixture.",
            budget=budget,
            deadline=datetime(2026, 7, 12, 12, tzinfo=UTC),
        )

        self.assertEqual(job.evidence_sha256, ("a" * 64, "b" * 64))
        self.assertEqual(job.tool_inventory, ())
        self.assertFalse(job.may_approve)
        self.assertFalse(job.may_execute)
        self.assertEqual(len(job.prompt_sha256), 64)
        wire = job.to_dict()
        self.assertNotIn("prompt", wire)
        self.assertEqual(wire["prompt_sha256"], job.prompt_sha256)
        self.assertEqual(wire["tool_inventory"], [])
        self.assertEqual(wire["capability"], "model_advisory")
        self.assertEqual(wire["deadline"], "2026-07-12T12:00:00Z")
        self.assertEqual(len(job.canonical_digest), 64)
        self.assertEqual(
            job.canonical_digest,
            replace(job, evidence_sha256=tuple(reversed(job.evidence_sha256))).canonical_digest,
        )

    def _job_kwargs(self) -> dict[str, object]:
        from accounting_agent.edge_worker import EdgeAdvisoryBudget

        return {
            "job_id": "job-edge-00000001",
            "request_id": "request-edge-00000001",
            "tenant_id": "tenant-synthetic",
            "client_id": "client-synthetic",
            "legal_entity_id": "entity-synthetic",
            "case_id": "case-synthetic",
            "evidence_sha256": ("a" * 64,),
            "provider_id": ProviderId.OLLAMA,
            "model_id": "qwen3:4b",
            "purpose": ModelPurpose.CLASSIFICATION,
            "data_classification": DataClassification.PUBLIC_SYNTHETIC,
            "prompt": "Classify this generated synthetic invoice fixture.",
            "budget": EdgeAdvisoryBudget(
                max_prompt_bytes=4_096,
                max_response_bytes=8_192,
                timeout_seconds=30,
            ),
            "deadline": datetime(2026, 7, 12, 12, tzinfo=UTC),
        }

    def _result_for(self, job: object) -> object:
        from accounting_agent.edge_worker import EdgeAdvisoryResultV1

        return EdgeAdvisoryResultV1(
            result_id="result-edge-00000001",
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
            payload_json='{"decision":"human_review","risk_flags":[]}',
            latency_ms=8,
            endpoint="http://127.0.0.1:11434",
            completed_at=datetime(2026, 7, 12, 11, 30, tzinfo=UTC),
        )

    def test_job_rejects_nonlocal_or_nonsynthetic_model_routes(self) -> None:
        from accounting_agent.edge_worker import EdgeAdvisoryJobV1

        for field_name, unsafe_value in (
            ("provider_id", ProviderId.OPENAI),
            ("provider_id", ProviderId.CODEX_WORKSPACE),
            ("data_classification", DataClassification.CONFIDENTIAL_ACCOUNTING),
            ("data_classification", DataClassification.CREDENTIAL_OR_SECRET),
        ):
            with self.subTest(field_name=field_name, unsafe_value=unsafe_value):
                values = self._job_kwargs()
                values[field_name] = unsafe_value
                with self.assertRaisesRegex(ValueError, "local|synthetic"):
                    EdgeAdvisoryJobV1(**values)

    def test_job_rejects_ambiguous_evidence_and_wrong_budget_type(self) -> None:
        from accounting_agent.edge_worker import EdgeAdvisoryJobV1

        for evidence in ((), ("a" * 64, "a" * 64), ("A" * 64,)):
            with self.subTest(evidence=evidence):
                values = self._job_kwargs()
                values["evidence_sha256"] = evidence
                with self.assertRaises(ValueError):
                    EdgeAdvisoryJobV1(**values)

        values = self._job_kwargs()
        values["budget"] = object()
        with self.assertRaisesRegex(TypeError, "EdgeAdvisoryBudget"):
            EdgeAdvisoryJobV1(**values)

    def test_budget_has_nonextendable_global_ceilings(self) -> None:
        from accounting_agent.edge_worker import EdgeAdvisoryBudget

        for field_name, value in (
            ("max_prompt_bytes", 100_001),
            ("max_response_bytes", 1_000_001),
            ("timeout_seconds", 181),
        ):
            with self.subTest(field_name=field_name):
                values = {
                    "max_prompt_bytes": 100_000,
                    "max_response_bytes": 1_000_000,
                    "timeout_seconds": 180,
                }
                values[field_name] = value
                with self.assertRaisesRegex(ValueError, "ceiling"):
                    EdgeAdvisoryBudget(**values)

    def test_result_contract_is_canonical_advisory_only_and_matches_exact_job(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        result_type = getattr(edge_worker, "EdgeAdvisoryResultV1", None)
        self.assertIsNotNone(result_type)
        payload_json = json.dumps(
            {"decision": "human_review", "risk_flags": ["possible_duplicate"]},
            sort_keys=True,
            separators=(",", ":"),
        )
        result = result_type(
            result_id="result-edge-00000001",
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
            payload_json=payload_json,
            latency_ms=8,
            endpoint="http://localhost:11434",
            completed_at=datetime(2026, 7, 12, 11, 30, tzinfo=UTC),
        )

        result.assert_matches_job(job)
        self.assertEqual(result.payload, json.loads(payload_json))
        self.assertEqual(result.tool_inventory, ())
        self.assertFalse(result.may_approve)
        self.assertFalse(result.may_execute)
        self.assertEqual(result.validation_status, "pending_deterministic_validation")
        self.assertEqual(result.to_dict()["tool_inventory"], [])
        self.assertEqual(len(result.payload_sha256), 64)
        self.assertEqual(len(result.canonical_digest), 64)

        other_job = replace(job, case_id="different-case")
        with self.assertRaisesRegex(ValueError, "scope|job"):
            result.assert_matches_job(other_job)

    def test_ed25519_result_signature_verifies_once_and_rejects_replay(self) -> None:
        from accounting_agent import edge_worker
        from accounting_agent.contracts import SignatureAlgorithm

        signer_type = getattr(edge_worker, "LocalEd25519Signer", None)
        sign_result = getattr(edge_worker, "sign_edge_result", None)
        verify_result = getattr(edge_worker, "verify_signed_edge_result", None)
        replay_guard_type = getattr(edge_worker, "LocalEdgeReplayGuard", None)
        self.assertIsNotNone(signer_type)
        self.assertIsNotNone(sign_result)
        self.assertIsNotNone(verify_result)
        self.assertIsNotNone(replay_guard_type)
        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        result = self._result_for(job)
        signer = signer_type(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        signed = sign_result(
            result,
            signer,
            signed_at=datetime(2026, 7, 12, 11, 31, tzinfo=UTC),
        )
        verifier = signer.public_verifier()
        replay_guard = replay_guard_type()

        verified = verify_result(
            signed,
            verifier,
            expected_job=job,
            replay_guard=replay_guard,
        )

        self.assertEqual(verified, result)
        self.assertEqual(signed.signature.algorithm, SignatureAlgorithm.ED25519)
        self.assertEqual(signed.signature.signed_payload_sha256, result.canonical_digest)
        self.assertFalse(hasattr(signer, "private_key_bytes"))
        with self.assertRaisesRegex(edge_worker.EdgeResultReplayError, "replay"):
            verify_result(
                signed,
                verifier,
                expected_job=job,
                replay_guard=replay_guard,
            )

    def test_replay_guard_rejects_same_result_resigned_at_valid_timestamp(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        result = self._result_for(job)
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        first = edge_worker.sign_edge_result(
            result,
            signer,
            signed_at=datetime(2026, 7, 12, 11, 31, tzinfo=UTC),
        )
        resigned = edge_worker.sign_edge_result(
            result,
            signer,
            signed_at=datetime(2026, 7, 12, 11, 32, tzinfo=UTC),
        )
        verifier = signer.public_verifier()
        replay_guard = edge_worker.LocalEdgeReplayGuard()

        edge_worker.verify_signed_edge_result(
            first,
            verifier,
            expected_job=job,
            replay_guard=replay_guard,
        )
        with self.assertRaisesRegex(edge_worker.EdgeResultReplayError, "replay"):
            edge_worker.verify_signed_edge_result(
                resigned,
                verifier,
                expected_job=job,
                replay_guard=replay_guard,
            )

    def test_signature_tamper_and_cross_scope_reuse_fail_closed(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        result = self._result_for(job)
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        signed = edge_worker.sign_edge_result(
            result,
            signer,
            signed_at=datetime(2026, 7, 12, 11, 31, tzinfo=UTC),
        )
        verifier = signer.public_verifier()

        tampered_signature = replace(
            signed.signature,
            signature_base64=b64encode(b"x" * 64).decode("ascii"),
        )
        with self.assertRaisesRegex(edge_worker.EdgeResultVerificationError, "signature"):
            edge_worker.verify_signed_edge_result(
                replace(signed, signature=tampered_signature),
                verifier,
                expected_job=job,
                replay_guard=edge_worker.LocalEdgeReplayGuard(),
            )

        other_job = replace(job, case_id="different-case")
        with self.assertRaisesRegex(edge_worker.EdgeResultVerificationError, "scope|job"):
            edge_worker.verify_signed_edge_result(
                signed,
                verifier,
                expected_job=other_job,
                replay_guard=edge_worker.LocalEdgeReplayGuard(),
            )

    def test_signature_statement_binds_timestamp_and_key_identity(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        result = self._result_for(job)
        private_key = b"\x01" * 32
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=private_key,
        )
        signed = edge_worker.sign_edge_result(
            result,
            signer,
            signed_at=datetime(2026, 7, 12, 11, 31, tzinfo=UTC),
        )
        cases = (
            (
                replace(
                    signed,
                    signature=replace(
                        signed.signature,
                        signed_at=datetime(2026, 7, 12, 11, 32, tzinfo=UTC),
                    ),
                ),
                signer.public_verifier(),
            ),
            (
                replace(
                    signed,
                    signature=replace(
                        signed.signature,
                        key_reference="fixture-alias",
                    ),
                ),
                edge_worker.LocalEd25519Signer(
                    key_reference="fixture-alias",
                    private_key_bytes=private_key,
                ).public_verifier(),
            ),
        )

        for tampered, verifier in cases:
            with self.subTest(signature=tampered.signature.to_dict()):
                with self.assertRaisesRegex(
                    edge_worker.EdgeResultVerificationError,
                    "signature",
                ):
                    edge_worker.verify_signed_edge_result(
                        tampered,
                        verifier,
                        expected_job=job,
                        replay_guard=edge_worker.LocalEdgeReplayGuard(),
                    )

    def test_verification_rejects_a_caller_supplied_noop_verifier(self) -> None:
        from accounting_agent import edge_worker
        from accounting_agent.contracts import SignatureAlgorithm

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        result = self._result_for(job)
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        signed = edge_worker.sign_edge_result(
            result,
            signer,
            signed_at=datetime(2026, 7, 12, 11, 31, tzinfo=UTC),
        )

        class NoopVerifier:
            key_reference = "fixture"
            algorithm = SignatureAlgorithm.ED25519

            def verify(self, signature: bytes, payload: bytes) -> None:
                return None

        with self.assertRaisesRegex(TypeError, "LocalEd25519Verifier"):
            edge_worker.verify_signed_edge_result(
                signed,
                NoopVerifier(),
                expected_job=job,
                replay_guard=edge_worker.LocalEdgeReplayGuard(),
            )

    def test_verification_rechecks_deadline_payload_and_latency_job_budgets(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(
            **{
                **self._job_kwargs(),
                "budget": edge_worker.EdgeAdvisoryBudget(
                    max_prompt_bytes=4_096,
                    max_response_bytes=64,
                    timeout_seconds=1,
                ),
            }
        )
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        base = self._result_for(job)
        cases = (
            (
                replace(base, completed_at=job.deadline),
                job.deadline,
                "deadline",
            ),
            (
                base,
                job.deadline,
                "deadline",
            ),
            (
                replace(base, payload_json=json.dumps({"value": "x" * 80})),
                base.completed_at,
                "response budget",
            ),
            (
                replace(base, latency_ms=1_001),
                base.completed_at,
                "timeout budget",
            ),
        )
        for result, signed_at, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                signed = edge_worker.sign_edge_result(result, signer, signed_at=signed_at)
                with self.assertRaisesRegex(
                    edge_worker.EdgeResultVerificationError,
                    expected_reason,
                ):
                    edge_worker.verify_signed_edge_result(
                        signed,
                        signer.public_verifier(),
                        expected_job=job,
                        replay_guard=edge_worker.LocalEdgeReplayGuard(),
                    )

    def test_runtime_executes_one_ollama_advisory_job_and_signs_exact_result(self) -> None:
        from accounting_agent import edge_worker

        run_job = getattr(edge_worker, "run_edge_advisory_job", None)
        self.assertIsNotNone(run_job)
        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        calls: list[object] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            calls.append(request)
            return _FakeResponse(
                {
                    "model": "qwen3:4b",
                    "done": True,
                    "message": {
                        "role": "assistant",
                        "content": '{"decision":"human_review","risk_flags":[]}',
                    },
                }
            )

        signed = run_job(
            job=job,
            signer=signer,
            endpoint="http://localhost:11434",
            allow_local_invocation=True,
            opener=opener,
            clock=lambda: datetime(2026, 7, 12, 11, 30, tzinfo=UTC),
        )

        verified = edge_worker.verify_signed_edge_result(
            signed,
            signer.public_verifier(),
            expected_job=job,
            replay_guard=edge_worker.LocalEdgeReplayGuard(),
        )
        self.assertEqual(verified.payload["decision"], "human_review")
        self.assertEqual(verified.provider_id, ProviderId.OLLAMA)
        self.assertEqual(verified.tool_inventory, ())
        self.assertFalse(verified.may_approve)
        self.assertFalse(verified.may_execute)
        self.assertEqual(len(calls), 1)
        request_body = json.loads(calls[0].data.decode("utf-8"))
        self.assertNotIn("tools", request_body)
        self.assertNotIn("functions", request_body)

    def test_runtime_rejects_invalid_signer_before_any_provider_call(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        opened = False

        def opener(_request: object, *, timeout: float) -> _FakeResponse:
            nonlocal opened
            opened = True
            return _FakeResponse({})

        with self.assertRaisesRegex(TypeError, "signer"):
            edge_worker.run_edge_advisory_job(
                job=job,
                signer=object(),
                endpoint="http://127.0.0.1:11434",
                allow_local_invocation=True,
                opener=opener,
                clock=lambda: datetime(2026, 7, 12, 11, 30, tzinfo=UTC),
            )
        self.assertFalse(opened)

    def test_runtime_opt_in_and_deadline_checks_make_zero_provider_calls(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        calls = 0

        def opener(_request: object, *, timeout: float) -> _FakeResponse:
            nonlocal calls
            calls += 1
            return _FakeResponse({})

        with self.assertRaisesRegex(PermissionError, "explicit local invocation opt-in"):
            edge_worker.run_edge_advisory_job(
                job=job,
                signer=signer,
                endpoint="http://127.0.0.1:11434",
                opener=opener,
            )
        with self.assertRaisesRegex(edge_worker.EdgeJobExpired, "deadline"):
            edge_worker.run_edge_advisory_job(
                job=job,
                signer=signer,
                endpoint="http://127.0.0.1:11434",
                allow_local_invocation=True,
                opener=opener,
                clock=lambda: job.deadline,
            )
        self.assertEqual(calls, 0)

    def test_runtime_discards_result_completed_at_the_deadline(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        times = iter(
            (
                datetime(2026, 7, 12, 11, 59, 59, tzinfo=UTC),
                job.deadline,
            )
        )

        with self.assertRaisesRegex(edge_worker.EdgeJobExpired, "exceeded"):
            edge_worker.run_edge_advisory_job(
                job=job,
                signer=signer,
                endpoint="http://127.0.0.1:11434",
                allow_local_invocation=True,
                opener=lambda _request, timeout: _FakeResponse(
                    {
                        "model": "qwen3:4b",
                        "done": True,
                        "message": {"role": "assistant", "content": "{}"},
                    }
                ),
                clock=lambda: next(times),
            )

    def test_runtime_rechecks_provider_result_budgets_before_signing(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(
            **{
                **self._job_kwargs(),
                "budget": edge_worker.EdgeAdvisoryBudget(
                    max_prompt_bytes=4_096,
                    max_response_bytes=64,
                    timeout_seconds=1,
                ),
            }
        )
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        cases = (
            SimpleNamespace(
                payload_json=json.dumps({"value": "x" * 80}),
                payload_hash="a" * 64,
                latency_ms=1,
                endpoint="http://127.0.0.1:11434",
            ),
            SimpleNamespace(
                payload_json="{}",
                payload_hash="b" * 64,
                latency_ms=1_001,
                endpoint="http://127.0.0.1:11434",
            ),
        )
        for provider_result in cases:
            with self.subTest(provider_result=provider_result):
                with patch(
                    "accounting_agent.edge_worker.runtime.invoke_ollama_advisory",
                    return_value=provider_result,
                ), self.assertRaisesRegex(edge_worker.EdgeJobBudgetExceeded, "budget"):
                    edge_worker.run_edge_advisory_job(
                        job=job,
                        signer=signer,
                        endpoint="http://127.0.0.1:11434",
                        allow_local_invocation=True,
                        clock=lambda: datetime(2026, 7, 12, 11, 30, tzinfo=UTC),
                    )

    def test_runtime_defensively_rejects_wrong_job_signer_and_tampered_provider(self) -> None:
        from accounting_agent import edge_worker

        with self.assertRaisesRegex(TypeError, "job"):
            edge_worker.run_edge_advisory_job(
                job=object(),
                signer=object(),
                endpoint="http://127.0.0.1:11434",
                allow_local_invocation=True,
            )

        job = edge_worker.EdgeAdvisoryJobV1(**self._job_kwargs())

        class WrongSigner:
            algorithm = "not-ed25519"
            key_reference = "fixture"
            sign = "not-callable"

        with self.assertRaisesRegex(TypeError, "Ed25519"):
            edge_worker.run_edge_advisory_job(
                job=job,
                signer=WrongSigner(),
                endpoint="http://127.0.0.1:11434",
                allow_local_invocation=True,
            )

        object.__setattr__(job, "provider_id", ProviderId.OPENAI)
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        with self.assertRaisesRegex(PermissionError, "provider"):
            edge_worker.run_edge_advisory_job(
                job=job,
                signer=signer,
                endpoint="http://127.0.0.1:11434",
                allow_local_invocation=True,
                clock=lambda: datetime(2026, 7, 12, 11, 30, tzinfo=UTC),
            )

    def test_runtime_dispatches_loopback_openai_compatible_without_tools(self) -> None:
        from accounting_agent import edge_worker

        job = edge_worker.EdgeAdvisoryJobV1(
            **{
                **self._job_kwargs(),
                "provider_id": ProviderId.LOCAL_OPENAI_COMPATIBLE,
                "model_id": "local-qwen",
            }
        )
        signer = edge_worker.LocalEd25519Signer(
            key_reference="fixture",
            private_key_bytes=b"\x01" * 32,
        )
        calls: list[object] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            calls.append(request)
            return _FakeResponse(
                {
                    "id": "chatcmpl-synthetic-002",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "local-qwen",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"decision":"human_review"}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 4,
                        "total_tokens": 12,
                    },
                }
            )

        signed = edge_worker.run_edge_advisory_job(
            job=job,
            signer=signer,
            endpoint="http://127.0.0.1:8080",
            allow_local_invocation=True,
            opener=opener,
            clock=lambda: datetime(2026, 7, 12, 11, 30, tzinfo=UTC),
        )

        self.assertEqual(signed.result.provider_id, ProviderId.LOCAL_OPENAI_COMPATIBLE)
        request_body = json.loads(calls[0].data.decode("utf-8"))
        self.assertNotIn("tools", request_body)
        self.assertNotIn("functions", request_body)

    def test_authority_manifest_is_fixed_to_local_advice_with_empty_tools(self) -> None:
        from accounting_agent import edge_worker

        manifest_builder = getattr(edge_worker, "edge_worker_authority_manifest", None)
        self.assertIsNotNone(manifest_builder)
        manifest = manifest_builder()

        self.assertEqual(manifest["allowed_capabilities"], ["model_advisory"])
        self.assertEqual(manifest["tool_inventory"], [])
        self.assertEqual(manifest["network_scope"], "localhost_only")
        self.assertTrue(manifest["synthetic_only"])
        self.assertFalse(manifest["may_approve"])
        self.assertFalse(manifest["may_execute"])
        for forbidden in (
            "erp_credentials",
            "connector_calls",
            "mcp_tools",
            "computer_use",
            "subprocess",
            "external_writes",
        ):
            self.assertIn(forbidden, manifest["forbidden_capabilities"])

    def test_edge_worker_modules_do_not_import_authority_or_process_surfaces(self) -> None:
        package = ROOT / "accounting_agent" / "edge_worker"
        banned = {
            "accounting_agent.adapters",
            "accounting_agent.connector_contract",
            "accounting_agent.erp",
            "accounting_agent.external_writes",
            "accounting_agent.permits",
            "accounting_agent.restricted_fortnox_mcp",
            "subprocess",
        }
        imported: set[str] = set()
        for source in sorted(package.glob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
        for module in imported:
            self.assertFalse(
                any(module == item or module.startswith(f"{item}.") for item in banned),
                module,
            )

    def test_ed25519_is_an_optional_edge_dependency_and_no_cli_is_added(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        edge_dependencies = project["project"]["optional-dependencies"]["edge"]
        qa_dependencies = project["dependency-groups"]["qa"]

        self.assertTrue(any(item.startswith("cryptography") for item in edge_dependencies))
        self.assertTrue(any(item.startswith("cryptography") for item in qa_dependencies))
        self.assertEqual(
            project["project"]["scripts"],
            {"accounting-agent": "accounting_agent.cli:main"},
        )

    def test_bounded_edge_contracts_are_exported_from_the_public_package(self) -> None:
        import accounting_agent

        expected = {
            "EDGE_ADVISORY_CAPABILITY",
            "EdgeAdvisoryBudget",
            "EdgeAdvisoryJobV1",
            "EdgeAdvisoryResultV1",
            "EdgeJobBudgetExceeded",
            "EdgeJobExpired",
            "EdgeResultReplayError",
            "EdgeResultSignature",
            "EdgeResultVerificationError",
            "LocalEd25519Signer",
            "LocalEd25519Verifier",
            "LocalEdgeReplayGuard",
            "SignedEdgeAdvisoryResultV1",
            "edge_worker_authority_manifest",
            "run_edge_advisory_job",
            "sign_edge_result",
            "verify_signed_edge_result",
        }

        self.assertLessEqual(expected, set(accounting_agent.__all__))
        for name in expected:
            self.assertIsNotNone(getattr(accounting_agent, name, None), name)


if __name__ == "__main__":
    unittest.main()
