from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace
from urllib.error import URLError

import accounting_agent.model_runtime as model_runtime

from accounting_agent.model_runtime import (
    AdvisoryModelOutput,
    BenchmarkDataOrigin,
    BenchmarkObservation,
    DataClassification,
    DeterministicValidationResult,
    ModelPurpose,
    ModelRouteRequest,
    NetworkScope,
    ProviderId,
    RouteStatus,
    RoutingPolicy,
    LocalModelInvocationError,
    gate_advisory_output,
    get_provider_manifest,
    list_provider_manifests,
    local_model_endpoint,
    invoke_ollama_advisory,
    plan_model_route,
    safe_synthetic_benchmark_suite,
    score_synthetic_benchmark,
    discover_ollama,
)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        return self._payload[:limit]


class _RawResponse(_FakeResponse):
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")


class ProviderManifestTests(unittest.TestCase):
    def test_all_v1_provider_manifests_exist_and_are_advisory_only(self) -> None:
        manifests = list_provider_manifests()

        self.assertEqual(
            {item.provider_id for item in manifests},
            {
                ProviderId.DETERMINISTIC,
                ProviderId.OLLAMA,
                ProviderId.LOCAL_OPENAI_COMPATIBLE,
                ProviderId.OPENAI,
                ProviderId.ANTHROPIC,
                ProviderId.GEMINI,
                ProviderId.CODEX_WORKSPACE,
            },
        )
        for manifest in manifests:
            self.assertTrue(manifest.advisory_only)
            self.assertFalse(manifest.can_approve)
            self.assertFalse(manifest.can_execute_accounting_actions)
            self.assertTrue(manifest.requires_deterministic_validation)

    def test_hosted_manifests_are_disabled_and_have_no_runtime_invoker(self) -> None:
        for provider_id in (
            ProviderId.OPENAI,
            ProviderId.ANTHROPIC,
            ProviderId.GEMINI,
            ProviderId.CODEX_WORKSPACE,
        ):
            manifest = get_provider_manifest(provider_id)
            self.assertFalse(manifest.enabled_by_default)
            self.assertEqual(manifest.network_scope, NetworkScope.HOSTED_OR_MANAGED)
            self.assertEqual(manifest.invocation_mode, "external_adapter_required")

    def test_unknown_provider_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown model provider"):
            get_provider_manifest("mystery-model")


class RoutingTests(unittest.TestCase):
    def _request(
        self,
        classification: DataClassification,
        provider_id: ProviderId,
    ) -> ModelRouteRequest:
        return ModelRouteRequest(
            request_id="route-test",
            purpose=ModelPurpose.EXPLANATION,
            data_classification=classification,
            preferred_provider=provider_id,
        )

    def test_default_policy_routes_confidential_accounting_data_only_locally(self) -> None:
        local = plan_model_route(
            self._request(DataClassification.CONFIDENTIAL_ACCOUNTING, ProviderId.OLLAMA)
        )
        hosted = plan_model_route(
            self._request(DataClassification.CONFIDENTIAL_ACCOUNTING, ProviderId.OPENAI)
        )

        self.assertEqual(local.status, RouteStatus.ROUTED)
        self.assertEqual(local.network_scope, NetworkScope.LOCALHOST_ONLY)
        self.assertEqual(hosted.status, RouteStatus.BLOCKED)
        self.assertIn("hosted_provider_not_enabled", hosted.reason_codes)

    def test_private_course_material_is_local_only_even_with_hosted_opt_in(self) -> None:
        decision = plan_model_route(
            self._request(DataClassification.PRIVATE_COURSE, ProviderId.ANTHROPIC),
            policy=RoutingPolicy(
                allow_hosted=True,
                hosted_classifications=(
                    DataClassification.PUBLIC_SYNTHETIC,
                    DataClassification.PRIVATE_COURSE,
                ),
            ),
        )

        self.assertEqual(decision.status, RouteStatus.BLOCKED)
        self.assertIn("classification_local_only", decision.reason_codes)

    def test_credentials_and_secrets_are_never_routed_to_a_model(self) -> None:
        for provider_id in ProviderId:
            decision = plan_model_route(
                self._request(DataClassification.CREDENTIAL_OR_SECRET, provider_id),
                policy=RoutingPolicy(
                    allow_hosted=True,
                    allow_workspace_agent=True,
                    hosted_classifications=tuple(DataClassification),
                    workspace_classifications=tuple(DataClassification),
                ),
            )
            self.assertEqual(decision.status, RouteStatus.BLOCKED)
            self.assertIn("credentials_forbidden", decision.reason_codes)

    def test_public_synthetic_data_can_be_planned_for_hosted_provider_only_by_opt_in(self) -> None:
        request = self._request(DataClassification.PUBLIC_SYNTHETIC, ProviderId.GEMINI)

        blocked = plan_model_route(request)
        routed = plan_model_route(
            request,
            policy=RoutingPolicy(
                allow_hosted=True,
                hosted_classifications=(DataClassification.PUBLIC_SYNTHETIC,),
            ),
        )

        self.assertEqual(blocked.status, RouteStatus.BLOCKED)
        self.assertEqual(routed.status, RouteStatus.ROUTED)
        self.assertFalse(routed.runtime_invocation_available)
        self.assertTrue(routed.requires_external_operator)

    def test_codex_workspace_agent_requires_separate_explicit_opt_in(self) -> None:
        request = self._request(DataClassification.INTERNAL_WORKSPACE, ProviderId.CODEX_WORKSPACE)

        self.assertEqual(plan_model_route(request).status, RouteStatus.BLOCKED)
        routed = plan_model_route(
            request,
            policy=RoutingPolicy(
                allow_workspace_agent=True,
                workspace_classifications=(DataClassification.INTERNAL_WORKSPACE,),
            ),
        )
        self.assertEqual(routed.status, RouteStatus.ROUTED)
        self.assertFalse(routed.runtime_invocation_available)

    def test_local_models_may_be_disabled_by_deployment_policy(self) -> None:
        decision = plan_model_route(
            self._request(DataClassification.INTERNAL_WORKSPACE, ProviderId.OLLAMA),
            policy=RoutingPolicy(allow_local_models=False),
        )

        self.assertEqual(decision.status, RouteStatus.BLOCKED)
        self.assertIn("local_models_disabled", decision.reason_codes)

    def test_route_request_and_policy_are_immutable(self) -> None:
        request = self._request(DataClassification.PUBLIC_SYNTHETIC, ProviderId.OLLAMA)
        policy = RoutingPolicy()

        with self.assertRaises(FrozenInstanceError):
            request.request_id = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            policy.allow_hosted = True  # type: ignore[misc]


class OllamaDiscoveryTests(unittest.TestCase):
    def test_local_endpoint_accepts_only_explicit_loopback_http_urls(self) -> None:
        self.assertEqual(
            local_model_endpoint("http://127.0.0.1:11434/"),
            "http://127.0.0.1:11434",
        )
        self.assertEqual(
            local_model_endpoint("http://localhost:11434"),
            "http://127.0.0.1:11434",
        )
        self.assertEqual(
            local_model_endpoint("http://[::1]:11434"),
            "http://[::1]:11434",
        )
        for unsafe in (
            "https://ollama.example.com",
            "http://192.168.1.3:11434",
            "http://user:secret@127.0.0.1:11434",
            "file:///tmp/ollama",
            "http://127.0.0.1:11434/api/tags",
        ):
            with self.subTest(endpoint=unsafe):
                with self.assertRaisesRegex(ValueError, "loopback|base URL|credentials"):
                    local_model_endpoint(unsafe)

    def test_discovery_uses_configured_local_endpoint_and_short_timeout(self) -> None:
        calls: list[tuple[str, float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            calls.append((request.full_url, timeout))  # type: ignore[attr-defined]
            return _FakeResponse(
                {
                    "models": [
                        {"name": "qwen3:8b", "size": 4_800_000_000},
                        {"name": "gemma3:4b", "size": 3_200_000_000},
                    ]
                }
            )

        discovery = discover_ollama(
            endpoint="http://localhost:12434",
            timeout_seconds=0.75,
            opener=opener,
        )

        self.assertTrue(discovery.available)
        self.assertEqual(discovery.endpoint, "http://127.0.0.1:12434")
        self.assertEqual(discovery.model_names, ("gemma3:4b", "qwen3:8b"))
        self.assertEqual(calls, [("http://127.0.0.1:12434/api/tags", 0.75)])

    def test_discovery_clamps_timeout_and_fails_closed_without_raising(self) -> None:
        calls: list[float] = []

        def unavailable(_request: object, *, timeout: float) -> _FakeResponse:
            calls.append(timeout)
            raise URLError("connection refused")

        discovery = discover_ollama(timeout_seconds=30.0, opener=unavailable)

        self.assertFalse(discovery.available)
        self.assertEqual(discovery.model_names, ())
        self.assertEqual(calls, [2.0])
        self.assertEqual(discovery.error_code, "ollama_unavailable")

    def test_discovery_rejects_remote_endpoint_before_opening_network(self) -> None:
        opened = False

        def opener(_request: object, *, timeout: float) -> _FakeResponse:
            nonlocal opened
            opened = True
            return _FakeResponse({"models": []})

        with self.assertRaises(ValueError):
            discover_ollama(endpoint="http://10.0.0.4:11434", opener=opener)
        self.assertFalse(opened)

    def test_malformed_discovery_response_is_not_reported_as_available(self) -> None:
        def opener(_request: object, *, timeout: float) -> _FakeResponse:
            return _FakeResponse({"models": "not-a-list"})

        discovery = discover_ollama(opener=opener)

        self.assertFalse(discovery.available)
        self.assertEqual(discovery.error_code, "invalid_ollama_response")


class AdvisoryGateTests(unittest.TestCase):
    def _output(self) -> AdvisoryModelOutput:
        return AdvisoryModelOutput(
            output_id="advice-1",
            request_id="request-1",
            provider_id=ProviderId.OLLAMA,
            model_id="synthetic-test-model",
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            payload_hash="a" * 64,
        )

    def test_model_output_is_pending_and_cannot_authorize_any_action(self) -> None:
        output = self._output()

        self.assertTrue(output.advisory_only)
        self.assertTrue(output.requires_deterministic_validation)
        self.assertFalse(output.may_approve)
        self.assertFalse(output.may_execute)

    def test_failed_deterministic_validation_blocks_human_review(self) -> None:
        gate = gate_advisory_output(
            self._output(),
            DeterministicValidationResult(
                validator_id="journal-v1",
                validated_payload_hash="a" * 64,
                passed=False,
                issue_codes=("journal_unbalanced",),
            ),
        )

        self.assertFalse(gate.eligible_for_human_review)
        self.assertFalse(gate.may_approve)
        self.assertFalse(gate.may_execute)
        self.assertIn("journal_unbalanced", gate.issue_codes)

    def test_passed_validation_only_allows_human_review_not_execution(self) -> None:
        gate = gate_advisory_output(
            self._output(),
            DeterministicValidationResult(
                validator_id="journal-v1",
                validated_payload_hash="a" * 64,
                passed=True,
            ),
        )

        self.assertTrue(gate.eligible_for_human_review)
        self.assertFalse(gate.may_approve)
        self.assertFalse(gate.may_execute)

    def test_validation_is_bound_to_the_exact_advisory_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "payload hash"):
            gate_advisory_output(
                self._output(),
                DeterministicValidationResult(
                    validator_id="journal-v1",
                    validated_payload_hash="b" * 64,
                    passed=True,
                ),
            )


class OllamaInvocationTests(unittest.TestCase):
    def _response(self, content: str) -> _FakeResponse:
        return _FakeResponse(
            {
                "model": "qwen3:4b",
                "done": True,
                "message": {"role": "assistant", "content": content},
            }
        )

    def test_invocation_requires_explicit_local_opt_in_before_network(self) -> None:
        opened = False

        def opener(_request: object, *, timeout: float) -> _FakeResponse:
            nonlocal opened
            opened = True
            return self._response('{"decision":"review"}')

        with self.assertRaisesRegex(PermissionError, "explicit local invocation opt-in"):
            invoke_ollama_advisory(
                request_id="local-1",
                model_id="qwen3:4b",
                purpose=ModelPurpose.CLASSIFICATION,
                data_classification=DataClassification.PUBLIC_SYNTHETIC,
                prompt="Synthetic duplicate invoice fixture.",
                opener=opener,
            )
        self.assertFalse(opened)

    def test_invocation_is_loopback_only_and_never_accepts_secrets(self) -> None:
        for classification, endpoint in (
            (DataClassification.PUBLIC_SYNTHETIC, "https://remote.example"),
            (DataClassification.CREDENTIAL_OR_SECRET, "http://127.0.0.1:11434"),
        ):
            with self.subTest(classification=classification, endpoint=endpoint):
                with self.assertRaises((ValueError, PermissionError)):
                    invoke_ollama_advisory(
                        request_id="local-2",
                        model_id="qwen3:4b",
                        purpose=ModelPurpose.CLASSIFICATION,
                        data_classification=classification,
                        prompt="Synthetic fixture only.",
                        endpoint=endpoint,
                        allow_local_invocation=True,
                    )

    def test_strict_json_response_becomes_hash_bound_advisory_output(self) -> None:
        calls: list[tuple[object, float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            calls.append((request, timeout))
            return self._response(
                '{"can_execute":false,"decision":"block_review",'
                '"requires_human":true,"risk_flags":["possible_duplicate"]}'
            )

        result = invoke_ollama_advisory(
            request_id="local-3",
            model_id="qwen3:4b",
            purpose=ModelPurpose.CLASSIFICATION,
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            prompt="Synthetic duplicate invoice fixture.",
            allow_local_invocation=True,
            timeout_seconds=999,
            opener=opener,
        )

        self.assertEqual(result.payload["decision"], "block_review")
        self.assertFalse(result.payload["can_execute"])
        self.assertEqual(result.output.request_id, "local-3")
        self.assertEqual(result.output.provider_id, ProviderId.OLLAMA)
        self.assertTrue(result.output.advisory_only)
        self.assertFalse(result.output.may_approve)
        self.assertFalse(result.output.may_execute)
        self.assertEqual(result.output.payload_hash, result.payload_hash)
        self.assertEqual(len(result.payload_hash), 64)
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertEqual(calls[0][1], 180.0)
        request = calls[0][0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        body = json.loads(request.data.decode("utf-8"))
        self.assertFalse(body["stream"])
        self.assertFalse(body["think"])
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["model"], "qwen3:4b")
        self.assertIn("advisory", body["messages"][0]["content"].lower())

    def test_fenced_or_non_object_json_fails_closed(self) -> None:
        for content in (
            '```json\n{"decision":"block_review"}\n```',
            '[{"decision":"block_review"}]',
            "not json",
        ):
            with self.subTest(content=content):
                with self.assertRaisesRegex(
                    LocalModelInvocationError,
                    "strict_json_object_required",
                ):
                    invoke_ollama_advisory(
                        request_id="local-4",
                        model_id="qwen3:4b",
                        purpose=ModelPurpose.CLASSIFICATION,
                        data_classification=DataClassification.PUBLIC_SYNTHETIC,
                        prompt="Synthetic duplicate invoice fixture.",
                        allow_local_invocation=True,
                        opener=lambda _request, timeout: self._response(content),
                    )

    def test_transport_errors_are_redacted_and_fail_closed(self) -> None:
        def unavailable(_request: object, *, timeout: float) -> _FakeResponse:
            raise URLError("private host detail must not escape")

        with self.assertRaisesRegex(
            LocalModelInvocationError,
            "ollama_unavailable",
        ) as caught:
            invoke_ollama_advisory(
                request_id="local-5",
                model_id="qwen3:4b",
                purpose=ModelPurpose.CLASSIFICATION,
                data_classification=DataClassification.PUBLIC_SYNTHETIC,
                prompt="Synthetic duplicate invoice fixture.",
                allow_local_invocation=True,
                opener=unavailable,
            )
        self.assertNotIn("private host detail", str(caught.exception))

    def test_response_must_match_requested_model_and_completed_assistant_turn(self) -> None:
        invalid_responses = (
            {
                "model": "different-model",
                "done": True,
                "message": {"role": "assistant", "content": "{}"},
            },
            {
                "model": "qwen3:4b",
                "done": False,
                "message": {"role": "assistant", "content": "{}"},
            },
            {
                "model": "qwen3:4b",
                "done": True,
                "message": {"role": "tool", "content": "{}"},
            },
        )
        for payload in invalid_responses:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(
                    LocalModelInvocationError,
                    "invalid_ollama_response",
                ):
                    invoke_ollama_advisory(
                        request_id="local-6",
                        model_id="qwen3:4b",
                        purpose=ModelPurpose.CLASSIFICATION,
                        data_classification=DataClassification.PUBLIC_SYNTHETIC,
                        prompt="Synthetic fixture only.",
                        allow_local_invocation=True,
                        opener=lambda _request, timeout: _FakeResponse(payload),
                    )

    def test_invocation_enforces_caller_prompt_and_response_byte_budgets(self) -> None:
        with self.assertRaisesRegex(ValueError, "prompt exceeds"):
            invoke_ollama_advisory(
                request_id="local-budget-1",
                model_id="qwen3:4b",
                purpose=ModelPurpose.CLASSIFICATION,
                data_classification=DataClassification.PUBLIC_SYNTHETIC,
                prompt="synthetic payload",
                allow_local_invocation=True,
                max_prompt_bytes=4,
                max_response_bytes=1_024,
                opener=lambda _request, timeout: self._response("{}"),
            )

        with self.assertRaisesRegex(
            LocalModelInvocationError,
            "ollama_response_too_large",
        ):
            invoke_ollama_advisory(
                request_id="local-budget-2",
                model_id="qwen3:4b",
                purpose=ModelPurpose.CLASSIFICATION,
                data_classification=DataClassification.PUBLIC_SYNTHETIC,
                prompt="synthetic payload",
                allow_local_invocation=True,
                max_prompt_bytes=1_024,
                max_response_bytes=16,
                opener=lambda _request, timeout: self._response('{"large":"payload"}'),
            )

    def test_duplicate_and_nonfinite_ollama_json_are_rejected(self) -> None:
        invalid_content = (
            '{"decision":"a","decision":"b"}',
            '{"confidence":NaN}',
            '{"confidence":1e309}',
        )
        for content in invalid_content:
            with self.subTest(layer="content", content=content):
                with self.assertRaisesRegex(
                    LocalModelInvocationError,
                    "strict_json_object_required",
                ):
                    invoke_ollama_advisory(
                        request_id="ollama-strict-content",
                        model_id="qwen3:4b",
                        purpose=ModelPurpose.CLASSIFICATION,
                        data_classification=DataClassification.PUBLIC_SYNTHETIC,
                        prompt="Synthetic fixture only.",
                        allow_local_invocation=True,
                        opener=lambda _request, timeout, value=content: self._response(value),
                    )

        invalid_envelopes = (
            '{"model":"qwen3:4b","model":"qwen3:4b","done":true,'
            '"message":{"role":"assistant","content":"{}"}}',
            '{"model":"qwen3:4b","done":true,"metric":Infinity,'
            '"message":{"role":"assistant","content":"{}"}}',
            '{"model":"qwen3:4b","done":true,"metric":-1e309,'
            '"message":{"role":"assistant","content":"{}"}}',
        )
        for envelope in invalid_envelopes:
            with self.subTest(layer="envelope", envelope=envelope):
                with self.assertRaisesRegex(
                    LocalModelInvocationError,
                    "invalid_ollama_response",
                ):
                    invoke_ollama_advisory(
                        request_id="ollama-strict-envelope",
                        model_id="qwen3:4b",
                        purpose=ModelPurpose.CLASSIFICATION,
                        data_classification=DataClassification.PUBLIC_SYNTHETIC,
                        prompt="Synthetic fixture only.",
                        allow_local_invocation=True,
                        opener=lambda _request, timeout, value=envelope: _RawResponse(value),
                    )


class LocalOpenAICompatibleInvocationTests(unittest.TestCase):
    def test_strict_local_chat_completion_is_hash_bound_and_has_no_tool_surface(self) -> None:
        invoke = getattr(model_runtime, "invoke_local_openai_compatible_advisory", None)
        self.assertIsNotNone(invoke)
        calls: list[tuple[object, float]] = []

        def opener(request: object, *, timeout: float) -> _FakeResponse:
            calls.append((request, timeout))
            return _FakeResponse(
                {
                    "id": "chatcmpl-synthetic-001",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "local-qwen",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"decision":"human_review","risk_flags":[]}',
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 8,
                        "total_tokens": 20,
                    },
                }
            )

        result = invoke(
            request_id="local-openai-1",
            model_id="local-qwen",
            purpose=ModelPurpose.CLASSIFICATION,
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            prompt="Generated synthetic invoice fixture.",
            allow_local_invocation=True,
            max_prompt_bytes=1_024,
            max_response_bytes=4_096,
            timeout_seconds=45,
            opener=opener,
        )

        self.assertEqual(result.payload, {"decision": "human_review", "risk_flags": []})
        self.assertEqual(result.output.provider_id, ProviderId.LOCAL_OPENAI_COMPATIBLE)
        self.assertFalse(result.output.may_approve)
        self.assertFalse(result.output.may_execute)
        self.assertEqual(result.output.payload_hash, result.payload_hash)
        request, timeout = calls[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(timeout, 45.0)
        self.assertNotIn("Authorization", request.headers)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", body)
        self.assertNotIn("functions", body)

    def test_provider_returned_tool_calls_are_rejected(self) -> None:
        response = {
            "id": "chatcmpl-synthetic-tool",
            "object": "chat.completion",
            "created": 1,
            "model": "local-qwen",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "{}",
                        "tool_calls": [],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        with self.assertRaisesRegex(
            LocalModelInvocationError,
            "invalid_local_openai_compatible_response",
        ):
            model_runtime.invoke_local_openai_compatible_advisory(
                request_id="local-openai-tool",
                model_id="local-qwen",
                purpose=ModelPurpose.CLASSIFICATION,
                data_classification=DataClassification.PUBLIC_SYNTHETIC,
                prompt="Generated synthetic invoice fixture.",
                allow_local_invocation=True,
                opener=lambda _request, timeout: _FakeResponse(response),
            )

    def test_duplicate_and_nonfinite_openai_compatible_json_are_rejected(self) -> None:
        for content in (
            '{"decision":"a","decision":"b"}',
            '{"confidence":-Infinity}',
            '{"confidence":-1e309}',
        ):
            response = {
                "id": "chatcmpl-synthetic-strict",
                "object": "chat.completion",
                "created": 1,
                "model": "local-qwen",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            with self.subTest(layer="content", content=content):
                with self.assertRaisesRegex(
                    LocalModelInvocationError,
                    "strict_json_object_required",
                ):
                    model_runtime.invoke_local_openai_compatible_advisory(
                        request_id="local-openai-strict-content",
                        model_id="local-qwen",
                        purpose=ModelPurpose.CLASSIFICATION,
                        data_classification=DataClassification.PUBLIC_SYNTHETIC,
                        prompt="Generated synthetic invoice fixture.",
                        allow_local_invocation=True,
                        opener=lambda _request, timeout, value=response: _FakeResponse(value),
                    )

        invalid_envelopes = (
            '{"object":"chat.completion","model":"local-qwen","model":"local-qwen",'
            '"choices":[{"index":0,"message":{"role":"assistant","content":"{}"},'
            '"finish_reason":"stop"}]}',
            '{"object":"chat.completion","model":"local-qwen","metric":NaN,'
            '"choices":[{"index":0,"message":{"role":"assistant","content":"{}"},'
            '"finish_reason":"stop"}]}',
            '{"object":"chat.completion","model":"local-qwen","metric":1e309,'
            '"choices":[{"index":0,"message":{"role":"assistant","content":"{}"},'
            '"finish_reason":"stop"}]}',
        )
        for envelope in invalid_envelopes:
            with self.subTest(layer="envelope", envelope=envelope):
                with self.assertRaisesRegex(
                    LocalModelInvocationError,
                    "invalid_local_openai_compatible_response",
                ):
                    model_runtime.invoke_local_openai_compatible_advisory(
                        request_id="local-openai-strict-envelope",
                        model_id="local-qwen",
                        purpose=ModelPurpose.CLASSIFICATION,
                        data_classification=DataClassification.PUBLIC_SYNTHETIC,
                        prompt="Generated synthetic invoice fixture.",
                        allow_local_invocation=True,
                        opener=lambda _request, timeout, value=envelope: _RawResponse(value),
                    )


class SyntheticBenchmarkTests(unittest.TestCase):
    def test_suite_contains_only_synthetic_metadata_not_raw_documents_or_prompts(self) -> None:
        suite = safe_synthetic_benchmark_suite()

        self.assertGreaterEqual(len(suite), 4)
        for case in suite:
            self.assertEqual(case.data_origin, BenchmarkDataOrigin.GENERATED_SYNTHETIC)
            self.assertEqual(case.data_classification, DataClassification.PUBLIC_SYNTHETIC)
            self.assertTrue(case.fixture_uri.startswith("synthetic://"))
            self.assertFalse(hasattr(case, "prompt"))
            self.assertFalse(hasattr(case, "document"))
            self.assertFalse(hasattr(case, "client_data"))
            self.assertGreater(len(case.required_assertions), 0)

    def test_scoring_uses_assertions_and_metrics_only(self) -> None:
        case = safe_synthetic_benchmark_suite()[0]
        observation = BenchmarkObservation(
            case_id=case.case_id,
            data_origin=BenchmarkDataOrigin.GENERATED_SYNTHETIC,
            provider_id=ProviderId.OLLAMA,
            model_id="synthetic-local-model",
            passed_assertions=case.required_assertions,
            schema_valid=True,
            deterministic_validation_passed=True,
            unsafe_action_attempted=False,
            latency_ms=case.target_latency_ms,
        )

        score = score_synthetic_benchmark(case, observation)

        self.assertEqual(score.correctness, 1.0)
        self.assertEqual(score.schema, 1.0)
        self.assertEqual(score.safety, 1.0)
        self.assertEqual(score.latency, 1.0)
        self.assertEqual(score.total, 1.0)
        self.assertEqual(score.provider_id, ProviderId.OLLAMA)
        self.assertEqual(score.model_id, "synthetic-local-model")

    def test_unsafe_action_or_failed_validation_zeroes_safety_and_caps_total(self) -> None:
        case = safe_synthetic_benchmark_suite()[0]
        observation = BenchmarkObservation(
            case_id=case.case_id,
            data_origin=BenchmarkDataOrigin.GENERATED_SYNTHETIC,
            provider_id=ProviderId.OLLAMA,
            model_id="synthetic-local-model",
            passed_assertions=case.required_assertions,
            schema_valid=True,
            deterministic_validation_passed=False,
            unsafe_action_attempted=True,
            latency_ms=0,
        )

        score = score_synthetic_benchmark(case, observation)

        self.assertEqual(score.safety, 0.0)
        self.assertLessEqual(score.total, 0.49)

    def test_non_synthetic_or_mismatched_observation_is_rejected(self) -> None:
        case = safe_synthetic_benchmark_suite()[0]
        valid = BenchmarkObservation(
            case_id=case.case_id,
            data_origin=BenchmarkDataOrigin.GENERATED_SYNTHETIC,
            provider_id=ProviderId.OLLAMA,
            model_id="synthetic-local-model",
            passed_assertions=(),
            schema_valid=False,
            deterministic_validation_passed=False,
            unsafe_action_attempted=False,
            latency_ms=10,
        )

        with self.assertRaisesRegex(ValueError, "case_id"):
            score_synthetic_benchmark(case, replace(valid, case_id="other-case"))
        with self.assertRaisesRegex(ValueError, "generated synthetic"):
            score_synthetic_benchmark(
                case,
                replace(valid, data_origin=BenchmarkDataOrigin.EXTERNAL_OR_PRIVATE),
            )

    def test_unknown_assertion_and_invalid_metrics_are_rejected(self) -> None:
        case = safe_synthetic_benchmark_suite()[0]

        with self.assertRaisesRegex(ValueError, "unknown benchmark assertions"):
            score_synthetic_benchmark(
                case,
                BenchmarkObservation(
                    case_id=case.case_id,
                    data_origin=BenchmarkDataOrigin.GENERATED_SYNTHETIC,
                    provider_id=ProviderId.OLLAMA,
                    model_id="synthetic-local-model",
                    passed_assertions=("not_in_case",),
                    schema_valid=True,
                    deterministic_validation_passed=True,
                    unsafe_action_attempted=False,
                    latency_ms=10,
                ),
            )
        with self.assertRaisesRegex(ValueError, "latency_ms"):
            BenchmarkObservation(
                case_id=case.case_id,
                data_origin=BenchmarkDataOrigin.GENERATED_SYNTHETIC,
                provider_id=ProviderId.OLLAMA,
                model_id="synthetic-local-model",
                passed_assertions=(),
                schema_valid=True,
                deterministic_validation_passed=True,
                unsafe_action_attempted=False,
                latency_ms=-1,
            )


if __name__ == "__main__":
    unittest.main()
