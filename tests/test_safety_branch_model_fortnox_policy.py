from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any, Mapping
from unittest.mock import Mock, patch

from accounting_agent import model_runtime
from accounting_agent.adapters import fortnox
from accounting_agent.model_runtime import (
    AdvisoryModelOutput,
    BenchmarkDataOrigin,
    BenchmarkObservation,
    DataClassification,
    DeterministicValidationResult,
    ModelPurpose,
    ModelRouteRequest,
    OllamaAdvisoryResult,
    OllamaModel,
    ProviderId,
    RoutingPolicy,
)
from accounting_agent.policy import (
    ActionType,
    AmountThresholds,
    PermissionMode,
    PolicyConfig,
    PolicyContext,
    evaluate_policy,
)
from accounting_agent.risk_review import (
    RiskFinding,
    RiskPolicyImpact,
    RiskSeverity,
    RiskSignal,
)


class _BytesResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.read_limits: list[int] = []

    def __enter__(self) -> _BytesResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        self.read_limits.append(limit)
        return self.payload if limit < 0 else self.payload[:limit]


class _StaticFortnoxTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.get_calls: list[tuple[str, Mapping[str, Any] | None]] = []

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.get_calls.append((path, params))
        return self.response

    def post(
        self,
        path: str,
        *,
        json_body: Mapping[str, Any],
        idempotency_key: str,
        permit: object | None,
    ) -> Mapping[str, Any]:
        raise AssertionError(f"unexpected synthetic POST to {path}")


class _AcceptingPermitValidator:
    def require_valid(self, **_kwargs: object) -> None:
        return None


class _PermitStub:
    idempotency_key = "synthetic-voucher-idempotency"


def _model_output(**changes: object) -> AdvisoryModelOutput:
    values: dict[str, object] = {
        "output_id": "synthetic-output",
        "request_id": "synthetic-request",
        "provider_id": ProviderId.OLLAMA,
        "model_id": "synthetic-model",
        "data_classification": DataClassification.PUBLIC_SYNTHETIC,
        "payload_hash": "a" * 64,
    }
    values.update(changes)
    return AdvisoryModelOutput(**values)  # type: ignore[arg-type]


def _benchmark_observation(**changes: object) -> BenchmarkObservation:
    case = model_runtime.safe_synthetic_benchmark_suite()[0]
    values: dict[str, object] = {
        "case_id": case.case_id,
        "data_origin": BenchmarkDataOrigin.GENERATED_SYNTHETIC,
        "provider_id": ProviderId.OLLAMA,
        "model_id": "synthetic-model",
        "passed_assertions": (),
        "schema_valid": True,
        "deterministic_validation_passed": True,
        "unsafe_action_attempted": False,
        "latency_ms": 1,
    }
    values.update(changes)
    return BenchmarkObservation(**values)  # type: ignore[arg-type]


class ModelRuntimeBranchTests(unittest.TestCase):
    def test_provider_manifest_rejects_each_authority_and_data_boundary(self) -> None:
        manifest = model_runtime.get_provider_manifest(ProviderId.OLLAMA)
        invalid_changes = (
            {"label": " "},
            {"supported_classifications": (DataClassification.CREDENTIAL_OR_SECRET,)},
            {"advisory_only": False},
            {"requires_deterministic_validation": False},
            {"can_approve": True},
            {"can_execute_accounting_actions": True},
        )

        for changes in invalid_changes:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(manifest, **changes)

    def test_route_contracts_reject_invalid_inputs_and_disabled_classifications(self) -> None:
        with self.assertRaisesRegex(ValueError, "request_id"):
            ModelRouteRequest(
                request_id=" ",
                purpose=ModelPurpose.EXPLANATION,
                data_classification=DataClassification.PUBLIC_SYNTHETIC,
                preferred_provider=ProviderId.OLLAMA,
            )
        with self.assertRaisesRegex(TypeError, "allow_local_models"):
            RoutingPolicy(allow_local_models=1)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "ModelRouteRequest"):
            model_runtime.plan_model_route(object())  # type: ignore[arg-type]

        request = ModelRouteRequest(
            request_id="synthetic-route",
            purpose=ModelPurpose.EXPLANATION,
            data_classification=DataClassification.PUBLIC_SYNTHETIC,
            preferred_provider=ProviderId.OPENAI,
        )
        with self.assertRaisesRegex(TypeError, "RoutingPolicy"):
            model_runtime.plan_model_route(request, policy=object())  # type: ignore[arg-type]

        hosted = model_runtime.plan_model_route(
            request,
            policy=RoutingPolicy(allow_hosted=True, hosted_classifications=()),
        )
        self.assertIn("classification_not_enabled_for_hosted_provider", hosted.reason_codes)

        private_workspace = replace(
            request,
            data_classification=DataClassification.PRIVATE_COURSE,
            preferred_provider=ProviderId.CODEX_WORKSPACE,
        )
        private_decision = model_runtime.plan_model_route(
            private_workspace,
            policy=RoutingPolicy(
                allow_workspace_agent=True,
                workspace_classifications=(DataClassification.PRIVATE_COURSE,),
            ),
        )
        self.assertIn("classification_local_only", private_decision.reason_codes)

        internal_workspace = replace(
            request,
            data_classification=DataClassification.INTERNAL_WORKSPACE,
            preferred_provider=ProviderId.CODEX_WORKSPACE,
        )
        workspace_decision = model_runtime.plan_model_route(
            internal_workspace,
            policy=RoutingPolicy(allow_workspace_agent=True, workspace_classifications=()),
        )
        self.assertIn(
            "classification_not_enabled_for_workspace_agent",
            workspace_decision.reason_codes,
        )

    def test_ollama_model_and_endpoint_validation_fail_closed(self) -> None:
        invalid_models = (
            {"name": "", "size_bytes": None},
            {"name": "synthetic", "size_bytes": True},
            {"name": "synthetic", "size_bytes": -1},
        )
        for values in invalid_models:
            with self.subTest(values=values), self.assertRaises(ValueError):
                OllamaModel(**values)  # type: ignore[arg-type]

        for endpoint in (None, "", "http://127.0.0.1:not-a-port"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                model_runtime.local_model_endpoint(endpoint)  # type: ignore[arg-type]

        with self.assertRaisesRegex(OSError, "redirect"):
            model_runtime._RejectRedirects().redirect_request()

        request = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        fake_opener = Mock()
        fake_opener.open.return_value = "synthetic-response"
        with patch.object(model_runtime, "build_opener", return_value=fake_opener) as build:
            response = model_runtime._open_loopback_only(request, timeout=0.25)
        self.assertEqual("synthetic-response", response)
        self.assertEqual(0.25, fake_opener.open.call_args.kwargs["timeout"])
        self.assertEqual(2, len(build.call_args.args))

    def test_discovery_rejects_invalid_timeouts_without_opening(self) -> None:
        opener = Mock(side_effect=AssertionError("discovery opener must stay unused"))
        for timeout in (True, "1", 0, float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                model_runtime.discover_ollama(
                    timeout_seconds=timeout,  # type: ignore[arg-type]
                    opener=opener,
                )
        opener.assert_not_called()

    def test_discovery_rejects_oversized_and_malformed_model_entries(self) -> None:
        malformed = (
            (b"x" * 1_000_001, "invalid_ollama_response"),
            (json.dumps({"models": ["not-an-object"]}).encode(), "invalid_ollama_response"),
            (json.dumps({"models": [{"name": 7}]}).encode(), "invalid_ollama_response"),
        )
        for raw, expected_code in malformed:
            with self.subTest(raw_size=len(raw)):
                result = model_runtime.discover_ollama(
                    opener=lambda _request, *, timeout, raw=raw: _BytesResponse(raw)
                )
                self.assertFalse(result.available)
                self.assertEqual(expected_code, result.error_code)

    def test_advisory_output_rejects_invalid_identity_hash_and_authority(self) -> None:
        invalid_changes = (
            {"output_id": ""},
            {"data_classification": DataClassification.CREDENTIAL_OR_SECRET},
            {"payload_hash": "not-a-hash"},
            {"advisory_only": False},
            {"requires_deterministic_validation": False},
            {"may_approve": True},
            {"may_execute": True},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _model_output(**changes)

    def test_advisory_result_validates_storage_contract(self) -> None:
        output = _model_output()
        invalid = (
            {"output": object(), "payload_json": "{}", "latency_ms": 0},
            {"output": output, "payload_json": "", "latency_ms": 0},
            {"output": output, "payload_json": "{}", "latency_ms": True},
            {"output": output, "payload_json": "{}", "latency_ms": -1},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                OllamaAdvisoryResult(
                    endpoint="http://127.0.0.1:11434",
                    **values,  # type: ignore[arg-type]
                )

        stored_list = OllamaAdvisoryResult(
            output=output,
            payload_json="[]",
            latency_ms=0,
            endpoint="http://127.0.0.1:11434",
        )
        with self.assertRaisesRegex(RuntimeError, "not a JSON object"):
            _ = stored_list.payload

    def test_invocation_rejects_invalid_arguments_before_transport(self) -> None:
        def never_open(_request: object, *, timeout: float) -> _BytesResponse:
            raise AssertionError(f"transport opened with timeout {timeout}")

        base: dict[str, object] = {
            "request_id": "synthetic-invocation",
            "model_id": "synthetic-model",
            "purpose": ModelPurpose.CLASSIFICATION,
            "data_classification": DataClassification.PUBLIC_SYNTHETIC,
            "prompt": "Synthetic fixture only.",
            "allow_local_invocation": True,
            "opener": never_open,
        }
        invalid = (
            ("empty model", {"model_id": ""}),
            ("long model", {"model_id": "m" * 201}),
            ("control model", {"model_id": "model\x00"}),
            ("empty prompt", {"prompt": " "}),
            ("long prompt", {"prompt": "x" * 100_001}),
            ("boolean timeout", {"timeout_seconds": True}),
            ("string timeout", {"timeout_seconds": "1"}),
            ("zero timeout", {"timeout_seconds": 0}),
            ("infinite timeout", {"timeout_seconds": float("inf")}),
        )
        for label, changes in invalid:
            with self.subTest(label=label), self.assertRaises(ValueError):
                model_runtime.invoke_ollama_advisory(
                    **(base | changes)  # type: ignore[arg-type]
                )

    def test_invocation_rejects_oversized_and_invalid_response_shapes(self) -> None:
        def invoke(raw: bytes) -> None:
            model_runtime.invoke_ollama_advisory(
                request_id="synthetic-response",
                model_id="synthetic-model",
                purpose=ModelPurpose.CLASSIFICATION,
                data_classification=DataClassification.PUBLIC_SYNTHETIC,
                prompt="Synthetic fixture only.",
                allow_local_invocation=True,
                opener=lambda _request, *, timeout: _BytesResponse(raw),
            )

        invalid_responses = (
            (b"x" * 1_000_001, "ollama_response_too_large"),
            (b"[]", "invalid_ollama_response"),
            (json.dumps({"message": []}).encode(), "invalid_ollama_response"),
            (
                json.dumps(
                    {
                        "model": "synthetic-model",
                        "done": True,
                        "message": {"role": "assistant", "content": 7},
                    }
                ).encode(),
                "invalid_ollama_response",
            ),
            (b"\xff", "invalid_ollama_response"),
        )
        for raw, code in invalid_responses:
            with self.subTest(code=code, raw_size=len(raw)):
                with self.assertRaisesRegex(model_runtime.LocalModelInvocationError, code):
                    invoke(raw)

    def test_invocation_defensively_rejects_non_dict_message_and_oversized_content(self) -> None:
        class _IndexableMessage:
            def __getitem__(self, key: str) -> str:
                if key != "content":
                    raise KeyError(key)
                return "{}"

        payloads = (
            {
                "model": "synthetic-model",
                "done": True,
                "message": _IndexableMessage(),
            },
            {
                "model": "synthetic-model",
                "done": True,
                "message": {
                    "role": "assistant",
                    "content": "x" * 1_000_001,
                },
            },
        )
        for payload in payloads:
            with self.subTest(message_type=type(payload["message"]).__name__):
                with patch.object(model_runtime.json, "loads", return_value=payload):
                    with self.assertRaisesRegex(
                        model_runtime.LocalModelInvocationError,
                        "invalid_ollama_response",
                    ):
                        model_runtime.invoke_ollama_advisory(
                            request_id="synthetic-defensive-response",
                            model_id="synthetic-model",
                            purpose=ModelPurpose.CLASSIFICATION,
                            data_classification=DataClassification.PUBLIC_SYNTHETIC,
                            prompt="Synthetic fixture only.",
                            allow_local_invocation=True,
                            opener=lambda _request, *, timeout: _BytesResponse(b"{}"),
                        )

    def test_validation_result_and_gate_reject_invalid_contracts(self) -> None:
        invalid_results = (
            {"validator_id": "", "validated_payload_hash": "a" * 64, "passed": True},
            {"validator_id": "v1", "validated_payload_hash": "a" * 64, "passed": 1},
            {"validator_id": "v1", "validated_payload_hash": "bad", "passed": True},
            {
                "validator_id": "v1",
                "validated_payload_hash": "a" * 64,
                "passed": False,
                "issue_codes": ("",),
            },
            {
                "validator_id": "v1",
                "validated_payload_hash": "a" * 64,
                "passed": False,
                "issue_codes": ("duplicate", "duplicate"),
            },
            {
                "validator_id": "v1",
                "validated_payload_hash": "a" * 64,
                "passed": True,
                "issue_codes": ("unexpected",),
            },
            {
                "validator_id": "v1",
                "validated_payload_hash": "a" * 64,
                "passed": False,
            },
        )
        for values in invalid_results:
            with self.subTest(values=values), self.assertRaises((TypeError, ValueError)):
                DeterministicValidationResult(**values)  # type: ignore[arg-type]

        valid_validation = DeterministicValidationResult(
            validator_id="v1",
            validated_payload_hash="a" * 64,
            passed=True,
        )
        with self.assertRaisesRegex(TypeError, "AdvisoryModelOutput"):
            model_runtime.gate_advisory_output(object(), valid_validation)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "DeterministicValidationResult"):
            model_runtime.gate_advisory_output(_model_output(), object())  # type: ignore[arg-type]

    def test_synthetic_case_validation_rejects_private_or_ambiguous_metadata(self) -> None:
        case = model_runtime.safe_synthetic_benchmark_suite()[0]
        invalid_changes = (
            {"case_id": ""},
            {"capability": ""},
            {"fixture_uri": "private://fixture"},
            {"data_origin": BenchmarkDataOrigin.EXTERNAL_OR_PRIVATE},
            {"data_classification": DataClassification.CONFIDENTIAL_ACCOUNTING},
            {"required_assertions": ()},
            {"required_assertions": ("valid", "")},
            {"required_assertions": ("duplicate", "duplicate")},
            {"target_latency_ms": True},
            {"target_latency_ms": 0},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(case, **changes)

    def test_benchmark_observation_and_score_validate_types(self) -> None:
        invalid_observations = (
            {"case_id": ""},
            {"model_id": ""},
            {"passed_assertions": ("",)},
            {"passed_assertions": ("duplicate", "duplicate")},
            {"schema_valid": 1},
            {"deterministic_validation_passed": 1},
            {"unsafe_action_attempted": 0},
            {"latency_ms": True},
            {"latency_ms": "1"},
        )
        for changes in invalid_observations:
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                _benchmark_observation(**changes)

        case = model_runtime.safe_synthetic_benchmark_suite()[0]
        observation = _benchmark_observation()
        with self.assertRaisesRegex(TypeError, "SyntheticBenchmarkCase"):
            model_runtime.score_synthetic_benchmark(object(), observation)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "BenchmarkObservation"):
            model_runtime.score_synthetic_benchmark(case, object())  # type: ignore[arg-type]


class FortnoxBranchTests(unittest.TestCase):
    def test_http_transport_rejects_non_get_before_open(self) -> None:
        transport = fortnox.HttpFortnoxTransport(
            fortnox.FortnoxConfig(access_token="synthetic-token")
        )
        with patch.object(fortnox, "_open_fortnox_read") as opened:
            with self.assertRaisesRegex(fortnox.FortnoxPolicyViolation, "Only HTTP GET"):
                transport._request("POST", "/accounts", json_body={"synthetic": True})
        opened.assert_not_called()

    def test_http_transport_encodes_dormant_headers_and_body_with_injected_open(self) -> None:
        transport = fortnox.HttpFortnoxTransport(
            fortnox.FortnoxConfig(access_token="synthetic-token")
        )
        response = _BytesResponse(b"{}")
        with patch.object(fortnox, "_open_fortnox_read", return_value=response) as opened:
            result = transport._request(
                "GET",
                "/accounts",
                json_body={"synthetic": True},
                idempotency_key="synthetic-idempotency",
            )

        self.assertEqual({}, result)
        request = opened.call_args.args[0]
        self.assertEqual("synthetic-idempotency", request.get_header("Idempotency-key"))
        self.assertEqual({"synthetic": True}, json.loads(request.data.decode("utf-8")))
        self.assertEqual([fortnox.MAX_FORTNOX_RESPONSE_BYTES + 1], response.read_limits)

    def test_http_transport_handles_empty_invalid_and_non_mapping_bodies(self) -> None:
        transport = fortnox.HttpFortnoxTransport(
            fortnox.FortnoxConfig(access_token="synthetic-token")
        )
        cases = (
            (b"", None),
            (b"not-json", "non-JSON"),
            (b"[]", "unexpected response shape"),
        )
        for raw, expected_error in cases:
            with self.subTest(raw=raw):
                with patch.object(
                    fortnox,
                    "_open_fortnox_read",
                    return_value=_BytesResponse(raw),
                ):
                    if expected_error is None:
                        self.assertEqual({}, transport.get("/accounts"))
                    else:
                        with self.assertRaisesRegex(
                            fortnox.FortnoxTransportError,
                            expected_error,
                        ):
                            transport.get("/accounts")

    def test_http_transport_redacts_url_error_reason(self) -> None:
        token = "synthetic-transport-secret"
        transport = fortnox.HttpFortnoxTransport(fortnox.FortnoxConfig(access_token=token))
        with patch.object(
            fortnox,
            "_open_fortnox_read",
            side_effect=urllib.error.URLError(f"connection refused for {token}"),
        ):
            with self.assertRaises(fortnox.FortnoxTransportError) as caught:
                transport.get("/accounts")
        self.assertNotIn(token, str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))

    def test_config_environment_and_base_url_validation_branches(self) -> None:
        config = fortnox.FortnoxConfig.from_env(
            {
                "FORTNOX_ACCESS_TOKEN": "synthetic-token",
                "FORTNOX_DRY_RUN": "false",
                "FORTNOX_ALLOW_DRAFT_WRITES": "yes",
                "FORTNOX_ALLOW_SENSITIVE_READS": "on",
                "FORTNOX_TIMEOUT_SECONDS": "7",
            }
        )
        self.assertEqual("synthetic-token", config.access_token)
        self.assertFalse(config.dry_run)
        self.assertTrue(config.allow_draft_writes)
        self.assertTrue(config.allow_sensitive_reads)
        self.assertEqual(7, config.timeout_seconds)

        for base_url in (
            " https://api.fortnox.se/3",
            "https://api.fortnox.se:not-a-port/3",
        ):
            with self.subTest(base_url=base_url), self.assertRaises(fortnox.FortnoxPolicyViolation):
                fortnox.FortnoxConfig(base_url=base_url)

    def test_invalid_paths_and_query_types_fail_before_open(self) -> None:
        transport = fortnox.HttpFortnoxTransport(
            fortnox.FortnoxConfig(access_token="synthetic-token")
        )
        with patch.object(fortnox, "_open_fortnox_read") as opened:
            for path in ("/unknown", "/accounts/1/too-deep"):
                with self.subTest(path=path), self.assertRaises(fortnox.FortnoxPolicyViolation):
                    transport.get(path)
            with self.assertRaisesRegex(fortnox.FortnoxPolicyViolation, "must be a mapping"):
                transport.get("/accounts", params=[("page", 1)])  # type: ignore[arg-type]
        opened.assert_not_called()

    def test_adapter_rejects_invalid_reference_response_shapes(self) -> None:
        list_adapter = fortnox.FortnoxAdapter(
            transport=_StaticFortnoxTransport({"Accounts": "not-a-list"})
        )
        with self.assertRaisesRegex(fortnox.FortnoxTransportError, "not a list"):
            list_adapter.list_accounts()

        item_adapter = fortnox.FortnoxAdapter(
            transport=_StaticFortnoxTransport({"Account": ["not-an-object"]})
        )
        with self.assertRaisesRegex(fortnox.FortnoxTransportError, "not an object"):
            item_adapter.get_account(1930)

    def test_supplier_payload_requires_rows_and_preserves_optional_reference(self) -> None:
        adapter = fortnox.FortnoxAdapter(transport=_StaticFortnoxTransport({}))
        required = {
            "supplier_number": "42",
            "invoice_number": "SYN-1",
            "invoice_date": "2026-07-11",
            "due_date": "2026-08-10",
            "total": "125.00",
            "vat": "25.00",
        }
        with self.assertRaisesRegex(ValueError, "at least one row"):
            adapter.prepare_supplier_invoice_draft_payload(rows=[], **required)
        with self.assertRaisesRegex(ValueError, "supplier_number"):
            adapter.prepare_supplier_invoice_draft_payload(
                rows=[{"account": 4010, "debit": "100.00"}],
                **(required | {"supplier_number": " "}),
            )

        payload = adapter.prepare_supplier_invoice_draft_payload(
            rows=[{"account": 4010, "debit": "100.00"}],
            your_reference="Synthetic buyer",
            **required,
        )
        self.assertEqual("Synthetic buyer", payload["SupplierInvoice"]["YourReference"])

    def test_row_validation_covers_missing_negative_dual_and_metadata_cases(self) -> None:
        with self.assertRaisesRegex(ValueError, "supplier invoice row requires account"):
            fortnox._supplier_invoice_row({})
        with self.assertRaisesRegex(ValueError, "voucher row requires account"):
            fortnox._voucher_row({})
        with self.assertRaisesRegex(ValueError, "must not be negative"):
            fortnox._voucher_row({"account": 4010, "debit": "-1"})
        with self.assertRaisesRegex(ValueError, "both debit and credit"):
            fortnox._voucher_row({"account": 4010, "debit": "1", "credit": "1"})

        row = fortnox._voucher_row(
            {
                "account": 4010,
                "debit": "1",
                "description": "Synthetic row",
                "cost_center": "C1",
                "project": "P1",
            }
        )
        self.assertEqual("Synthetic row", row["TransactionInformation"])
        self.assertEqual("C1", row["CostCenter"])
        self.assertEqual("P1", row["Project"])

    def test_voucher_empty_rows_and_forbidden_payload_markers_fail_closed(self) -> None:
        adapter = fortnox.FortnoxAdapter(transport=_StaticFortnoxTransport({}))
        with self.assertRaisesRegex(ValueError, "at least one row"):
            adapter.prepare_voucher_draft_payload(
                transaction_date="2026-07-11",
                description="Synthetic voucher",
                voucher_series="A",
                rows=[],
            )
        with self.assertRaisesRegex(fortnox.FortnoxProtectedOperation, "approval"):
            fortnox._assert_no_forbidden_payload_markers(
                {"nested": [{"approval": "synthetic approval"}]}
            )

    def test_adapter_defensive_none_permit_and_dry_run_voucher_branches(self) -> None:
        adapter = fortnox.FortnoxAdapter(
            transport=_StaticFortnoxTransport({}),
            permit_validator=_AcceptingPermitValidator(),  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(fortnox.FortnoxPolicyViolation, "without a permit"):
            adapter._create_draft(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                case_id="synthetic-case",
                entity_id="synthetic-entity",
                payload={"SupplierInvoice": {"Booked": False}},
                permit=None,
            )

        result = adapter._create_draft(
            action_type=ActionType.DRAFT_VOUCHER,
            case_id="synthetic-case",
            entity_id="synthetic-entity",
            payload={"Voucher": {"VoucherRows": []}},
            permit=_PermitStub(),  # type: ignore[arg-type]
        )
        self.assertEqual("dry_run_voucher_payload_prepared_only", result.status)
        self.assertTrue(result.dry_run)

    def test_forbidden_action_redirect_and_secret_redaction_branches(self) -> None:
        adapter = fortnox.FortnoxAdapter(transport=_StaticFortnoxTransport({}))
        with self.assertRaises(fortnox.FortnoxProtectedOperation):
            adapter._raise_if_action_forbidden(ActionType.POST_VOUCHER)
        with self.assertRaisesRegex(fortnox.FortnoxTransportError, "redirect"):
            fortnox._RejectFortnoxRedirects().redirect_request()

        with patch.dict(os.environ, {"FORTNOX_ACCESS_TOKEN": "synthetic-env-secret"}):
            redacted = fortnox._redact(
                "synthetic-direct-secret synthetic-env-secret",
                additional_secrets=("", "synthetic-direct-secret"),
            )
        self.assertEqual("[REDACTED] [REDACTED]", redacted)


class PolicyBranchTests(unittest.TestCase):
    def test_threshold_types_and_client_currency_keys_are_validated(self) -> None:
        for value in (True, -1):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(
                    ValueError,
                    "non-negative integer",
                ),
            ):
                AmountThresholds(
                    draft_without_review_minor=value,  # type: ignore[arg-type]
                    escalation_required_minor=100,
                )

        with self.assertRaisesRegex(TypeError, "currency amount thresholds"):
            PolicyConfig(currency_amount_thresholds={"SEK": object()})  # type: ignore[dict-item]
        with self.assertRaisesRegex(ValueError, "client currency threshold keys"):
            PolicyConfig(
                client_currency_amount_thresholds={
                    (7, "SEK"): AmountThresholds()  # type: ignore[dict-item]
                }
            )
        with self.assertRaisesRegex(TypeError, "client currency thresholds"):
            PolicyConfig(
                client_currency_amount_thresholds={
                    ("synthetic-client", "SEK"): object()  # type: ignore[dict-item]
                }
            )

    def test_missing_client_and_unknown_customer_require_review(self) -> None:
        missing_client = evaluate_policy(
            PolicyContext(
                action_type=ActionType.READ_ANALYSIS,
                client_id=" ",
                currency_code="SEK",
            )
        )
        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, missing_client.permission_mode)
        self.assertIn("client_id_missing", missing_client.reasons)

        unknown_customer = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="synthetic-client",
                currency_code="SEK",
                customer_known=False,
                risk_evidence_complete=True,
            )
        )
        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, unknown_customer.permission_mode)
        self.assertIn("customer_not_previously_known", unknown_customer.reasons)

    def test_negative_amount_and_out_of_range_confidence_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "amount_minor"):
            evaluate_policy(
                PolicyContext(
                    action_type=ActionType.READ_ANALYSIS,
                    client_id="synthetic-client",
                    currency_code="SEK",
                    amount_minor=-1,
                )
            )
        for field_name, value in (("duplicate_risk", -0.1), ("vat_confidence", 1.1)):
            with (
                self.subTest(field_name=field_name),
                self.assertRaisesRegex(
                    ValueError,
                    "between 0.0 and 1.0",
                ),
            ):
                evaluate_policy(
                    PolicyContext(
                        action_type=ActionType.READ_ANALYSIS,
                        client_id="synthetic-client",
                        currency_code="SEK",
                        **{field_name: value},
                    )
                )

    def test_forbidden_risk_impact_clears_previously_required_reviews(self) -> None:
        finding = RiskFinding(
            signal=RiskSignal.CHANGED_BANK_DETAILS,
            severity=RiskSeverity.BLOCKER,
            message="Synthetic blocked risk",
            policy_impact=RiskPolicyImpact(
                minimum_permission_mode=PermissionMode.FORBIDDEN.value,
                required_reviews=("security_review",),
                reason="synthetic_forbidden_risk",
            ),
        )
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="synthetic-client",
                currency_code="SEK",
                amount_minor=20_000_00,
                risk_evidence_complete=True,
                risk_findings=(finding,),
            )
        )
        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)
        self.assertIn("synthetic_forbidden_risk", decision.reasons)


if __name__ == "__main__":
    unittest.main()
