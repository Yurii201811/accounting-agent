from __future__ import annotations

import io
import json
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from accounting_agent import (
    ActionType,
    FortnoxAdapter,
    FortnoxConfig,
    FortnoxPolicyViolation,
    FortnoxProtectedOperation,
    FortnoxTransportError,
    InMemoryIdempotencyStore,
    MissingFortnoxCredentials,
    PermissionMode,
    PermitValidationError,
    PermitValidator,
    PolicyContext,
    evaluate_policy,
)
from accounting_agent.adapters.fortnox import (
    HttpFortnoxTransport,
    _assert_no_forbidden_payload_markers,
)
from tests.permit_approval_helpers import issue_test_permit


PERMIT_ISSUED_AT = datetime.now(UTC).replace(microsecond=0)
ENTITY_ID = "synthetic-test-entity"
MAX_TEST_RESPONSE_BYTES = 5_000_000


class FakeHTTPResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.read_limits: list[int] = []

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int = -1) -> bytes:
        self.read_limits.append(limit)
        return self.payload if limit < 0 else self.payload[:limit]


class FakeOpenerDirector:
    def __init__(self, response: FakeHTTPResponse) -> None:
        self.response = response
        self.calls: list[tuple[urllib.request.Request, float]] = []

    def open(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> FakeHTTPResponse:
        self.calls.append((request, timeout))
        return self.response


class FailingOpenerDirector:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def open(
        self,
        request: urllib.request.Request,
        *,
        timeout: float,
    ) -> FakeHTTPResponse:
        raise self.error


class TrackingBytesIO(io.BytesIO):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.read_limits: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_limits.append(size)
        return super().read(size)


class MockFortnoxTransport:
    def __init__(self) -> None:
        self.get_responses: dict[tuple[str, tuple[tuple[str, Any], ...]], dict[str, Any]] = {}
        self.post_responses: dict[str, dict[str, Any]] = {}
        self.posts: list[tuple[str, dict[str, Any], str]] = []

    def add_get(
        self,
        path: str,
        response: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> None:
        self.get_responses[(path, tuple(sorted((params or {}).items())))] = response

    def add_post(self, path: str, response: dict[str, Any]) -> None:
        self.post_responses[path] = response

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.get_responses[(path, tuple(sorted((params or {}).items())))]

    def post(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        idempotency_key: str,
        permit: object,
    ) -> dict[str, Any]:
        self.posts.append((path, json_body, idempotency_key))
        return self.post_responses[path]


class FortnoxReadTests(unittest.TestCase):
    def test_reads_reference_data_from_mock_transport(self) -> None:
        transport = MockFortnoxTransport()
        transport.add_get("/accounts", {"Accounts": [{"Number": 2440}]})
        transport.add_get("/accounts/2440", {"Account": {"Number": 2440}})
        transport.add_get("/suppliers", {"Suppliers": [{"SupplierNumber": "42"}]})
        transport.add_get("/suppliers/42", {"Supplier": {"SupplierNumber": "42"}})
        transport.add_get("/customers", {"Customers": [{"CustomerNumber": "7"}]})
        transport.add_get("/customers/7", {"Customer": {"CustomerNumber": "7"}})
        transport.add_get("/financialyears", {"FinancialYears": [{"Id": 1}]})
        transport.add_get("/financialyears/1", {"FinancialYear": {"Id": 1}})

        adapter = FortnoxAdapter(transport=transport)

        self.assertEqual(2440, adapter.list_accounts()[0]["Number"])
        self.assertEqual(2440, adapter.get_account(2440)["Number"])
        self.assertEqual("42", adapter.list_suppliers()[0]["SupplierNumber"])
        self.assertEqual("42", adapter.get_supplier("42")["SupplierNumber"])
        self.assertEqual("7", adapter.list_customers()[0]["CustomerNumber"])
        self.assertEqual("7", adapter.get_customer("7")["CustomerNumber"])
        self.assertEqual(1, adapter.list_financial_years()[0]["Id"])
        self.assertEqual(1, adapter.get_financial_year(1)["Id"])

    def test_sensitive_reads_are_blocked_by_default(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())

        with self.assertRaises(FortnoxPolicyViolation):
            adapter.list_vouchers()
        with self.assertRaises(FortnoxPolicyViolation):
            adapter.list_invoices()
        with self.assertRaises(FortnoxPolicyViolation):
            adapter.list_supplier_invoices()

    def test_sensitive_reads_can_be_enabled_for_mocked_read_only_flow(self) -> None:
        transport = MockFortnoxTransport()
        transport.add_get("/supplierinvoices", {"SupplierInvoices": [{"GivenNumber": "1"}]})
        adapter = FortnoxAdapter(
            config=FortnoxConfig(allow_sensitive_reads=True),
            transport=transport,
        )

        self.assertEqual("1", adapter.list_supplier_invoices()[0]["GivenNumber"])

    def test_real_transport_requires_credentials_for_reads(self) -> None:
        adapter = FortnoxAdapter(config=FortnoxConfig(access_token=None))

        with self.assertRaises(MissingFortnoxCredentials):
            adapter.list_accounts()


class HttpFortnoxTransportSecurityTests(unittest.TestCase):
    def test_config_rejects_unapproved_or_ambiguous_base_urls(self) -> None:
        unsafe_urls = (
            "http://api.fortnox.se/3",
            "https://evil.invalid/3",
            "https://api.fortnox.se.evil.invalid/3",
            "https://api.fortnox.se@evil.invalid/3",
            "https://synthetic-user@api.fortnox.se/3",
            "https://api.fortnox.se:444/3",
            "https://api.fortnox.se/3?redirect=https://evil.invalid",
            "https://api.fortnox.se/3/../other",
        )

        for base_url in unsafe_urls:
            with self.subTest(base_url=base_url):
                with self.assertRaisesRegex(
                    FortnoxPolicyViolation,
                    "approved Fortnox HTTPS origin",
                ):
                    FortnoxConfig(base_url=base_url, access_token="synthetic-token")

    def test_config_normalizes_the_approved_https_origin(self) -> None:
        config = FortnoxConfig(
            base_url="https://API.FORTNOX.SE:443/3/",
            access_token="synthetic-token",
        )

        self.assertEqual("https://api.fortnox.se/3", config.base_url)

    def test_explicit_empty_environment_does_not_inherit_process_credentials(self) -> None:
        with patch.dict(
            "accounting_agent.adapters.fortnox.os.environ",
            {"FORTNOX_ACCESS_TOKEN": "ambient-process-token"},
            clear=True,
        ):
            config = FortnoxConfig.from_env({})

        self.assertIsNone(config.access_token)

    def test_invalid_paths_fail_before_any_transport_open(self) -> None:
        transport = HttpFortnoxTransport(
            FortnoxConfig(access_token="synthetic-token")
        )
        unsafe_paths = (
            "https://evil.invalid/accounts",
            "//evil.invalid/accounts",
            "/../accounts",
            "/accounts?redirect=https://evil.invalid",
            "/accounts#fragment",
            "/accounts\\extra",
            "/accounts\nextra",
        )

        for path in unsafe_paths:
            with self.subTest(path=path):
                director = FakeOpenerDirector(FakeHTTPResponse(b"{}"))
                with (
                    patch(
                        "accounting_agent.adapters.fortnox.urllib.request.urlopen",
                        side_effect=director.open,
                    ) as global_open,
                    patch(
                        "accounting_agent.adapters.fortnox.urllib.request.build_opener",
                        return_value=director,
                    ) as build_opener,
                ):
                    with self.assertRaisesRegex(
                        FortnoxPolicyViolation,
                        "safe Fortnox API path",
                    ):
                        transport.get(path)

                self.assertEqual([], director.calls)
                global_open.assert_not_called()
                build_opener.assert_not_called()

    def test_query_values_are_encoded_without_changing_the_approved_origin(self) -> None:
        director = FakeOpenerDirector(
            FakeHTTPResponse(json.dumps({"Accounts": []}).encode("utf-8"))
        )
        transport = HttpFortnoxTransport(
            FortnoxConfig(access_token="synthetic-token", timeout_seconds=13)
        )
        with (
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.urlopen",
                side_effect=director.open,
            ),
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.build_opener",
                return_value=director,
            ),
        ):
            result = transport.get(
                "/accounts",
                params={"filter": "x&redirect=https://evil.invalid", "page": 1},
            )

        self.assertEqual({"Accounts": []}, result)
        request, timeout = director.calls[0]
        self.assertEqual(13, timeout)
        parsed = urllib.parse.urlsplit(request.full_url)
        self.assertEqual(
            ("https", "api.fortnox.se", "/3/accounts"),
            (parsed.scheme, parsed.netloc, parsed.path),
        )
        self.assertEqual(
            {"filter": ["x&redirect=https://evil.invalid"], "page": ["1"]},
            urllib.parse.parse_qs(parsed.query),
        )

    def test_non_scalar_query_values_fail_before_any_transport_open(self) -> None:
        director = FakeOpenerDirector(FakeHTTPResponse(b"{}"))
        transport = HttpFortnoxTransport(
            FortnoxConfig(access_token="synthetic-token")
        )
        with (
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.urlopen",
                side_effect=director.open,
            ) as global_open,
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.build_opener",
                return_value=director,
            ) as build_opener,
        ):
            with self.assertRaisesRegex(
                FortnoxPolicyViolation,
                "query parameters must be scalar values",
            ):
                transport.get("/accounts", params={"page": {"nested": "value"}})

        self.assertEqual([], director.calls)
        global_open.assert_not_called()
        build_opener.assert_not_called()

    def test_default_read_opener_disables_proxies_and_rejects_redirects(self) -> None:
        director = FakeOpenerDirector(FakeHTTPResponse(b"{}"))
        transport = HttpFortnoxTransport(
            FortnoxConfig(access_token="synthetic-token")
        )
        with (
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.urlopen",
                side_effect=director.open,
            ),
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.build_opener",
                return_value=director,
            ) as build_opener,
        ):
            self.assertEqual({}, transport.get("/accounts"))

        build_opener.assert_called_once()
        handlers = build_opener.call_args.args
        self.assertEqual({}, handlers[0].proxies)
        with self.assertRaisesRegex(FortnoxTransportError, "redirect"):
            handlers[1].redirect_request(None, None, 302, "Found", {}, None)

    def test_response_body_is_read_with_a_hard_size_limit(self) -> None:
        response = FakeHTTPResponse(b"{" + b" " * MAX_TEST_RESPONSE_BYTES + b"}")
        director = FakeOpenerDirector(response)
        transport = HttpFortnoxTransport(
            FortnoxConfig(access_token="synthetic-token")
        )
        with (
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.urlopen",
                side_effect=director.open,
            ),
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.build_opener",
                return_value=director,
            ),
        ):
            with self.assertRaisesRegex(FortnoxTransportError, "response exceeds"):
                transport.get("/accounts")

        self.assertEqual([MAX_TEST_RESPONSE_BYTES + 1], response.read_limits)

    def test_direct_config_token_is_redacted_from_http_errors(self) -> None:
        token = "synthetic-direct-config-token"
        error = urllib.error.HTTPError(
            "https://api.fortnox.se/3/accounts",
            500,
            "Synthetic failure",
            {},
            io.BytesIO(f"provider echoed {token}".encode("utf-8")),
        )
        director = FailingOpenerDirector(error)
        transport = HttpFortnoxTransport(FortnoxConfig(access_token=token))
        with (
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.urlopen",
                side_effect=director.open,
            ),
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.build_opener",
                return_value=director,
            ),
        ):
            with self.assertRaises(FortnoxTransportError) as raised:
                transport.get("/accounts")

        self.assertNotIn(token, str(raised.exception))
        self.assertIn("[REDACTED]", str(raised.exception))
        self.assertTrue(error.fp.closed)

    def test_http_error_body_is_bounded_and_truncated(self) -> None:
        error_body = TrackingBytesIO(b"x" * 64_001)
        error = urllib.error.HTTPError(
            "https://api.fortnox.se/3/accounts",
            500,
            "Synthetic failure",
            {},
            error_body,
        )
        director = FailingOpenerDirector(error)
        transport = HttpFortnoxTransport(
            FortnoxConfig(access_token="synthetic-token")
        )
        with (
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.urlopen",
                side_effect=director.open,
            ),
            patch(
                "accounting_agent.adapters.fortnox.urllib.request.build_opener",
                return_value=director,
            ),
        ):
            with self.assertRaises(FortnoxTransportError) as raised:
                transport.get("/accounts")

        self.assertEqual([64_001], error_body.read_limits)
        self.assertIn("[TRUNCATED]", str(raised.exception))
        self.assertTrue(error_body.closed)


class FortnoxDraftPayloadTests(unittest.TestCase):
    def test_prepare_supplier_invoice_draft_payload(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())

        payload = adapter.prepare_supplier_invoice_draft_payload(
            supplier_number="42",
            invoice_number="INV-123",
            invoice_date="2026-05-16",
            due_date="2026-06-15",
            total="1250.00",
            vat="250.00",
            rows=[
                {
                    "account": 4010,
                    "debit": "1000.00",
                    "description": "Consulting",
                    "project": "pilot",
                }
            ],
            comments="Prepared by accounting agent dry run",
        )

        invoice = payload["SupplierInvoice"]
        self.assertFalse(invoice["Booked"])
        self.assertFalse(invoice["PaymentPending"])
        self.assertTrue(invoice["DisablePaymentFile"])
        self.assertEqual("42", invoice["SupplierNumber"])
        self.assertEqual("1250.00", invoice["Total"])
        self.assertEqual(4010, invoice["SupplierInvoiceRows"][0]["Account"])

    def test_prepare_voucher_draft_payload_requires_balanced_rows(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())

        payload = adapter.prepare_voucher_draft_payload(
            transaction_date="2026-05-16",
            description="Supplier invoice proposal",
            voucher_series="A",
            rows=[
                {"account": 4010, "debit": "1000.00"},
                {"account": 2440, "credit": "1000.00"},
            ],
        )

        self.assertEqual("A", payload["Voucher"]["VoucherSeries"])
        self.assertEqual("1000.00", payload["Voucher"]["VoucherRows"][0]["Debit"])

        with self.assertRaises(ValueError):
            adapter.prepare_voucher_draft_payload(
                transaction_date="2026-05-16",
                description="Unbalanced proposal",
                voucher_series="A",
                rows=[
                    {"account": 4010, "debit": "1000.00"},
                    {"account": 2440, "credit": "999.00"},
                ],
            )


class FortnoxDraftCreateTests(unittest.TestCase):
    def test_create_supplier_invoice_draft_requires_permit_even_in_dry_run(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())
        payload = _supplier_invoice_payload(adapter)

        with self.assertRaises(PermitValidationError):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=None,
            )

    def test_create_supplier_invoice_draft_dry_run_records_idempotency(self) -> None:
        store = InMemoryIdempotencyStore()
        transport = MockFortnoxTransport()
        adapter = FortnoxAdapter(transport=transport, idempotency_store=store)
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(ActionType.DRAFT_SUPPLIER_INVOICE, payload)

        first = adapter.create_supplier_invoice_draft(
            case_id="case_1",
            entity_id=ENTITY_ID,
            payload=payload,
            permit=permit,
        )
        second = adapter.create_supplier_invoice_draft(
            case_id="case_1",
            entity_id=ENTITY_ID,
            payload=payload,
            permit=permit,
        )

        self.assertEqual("dry_run_draft_not_created", first.status)
        self.assertTrue(first.dry_run)
        self.assertEqual("duplicate_idempotency_key", second.status)
        self.assertEqual(first.idempotency_key, second.duplicate_of)
        self.assertEqual([], transport.posts)

    def test_create_supplier_invoice_draft_rejects_cross_entity_permit(self) -> None:
        adapter = FortnoxAdapter(transport=MockFortnoxTransport())
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(ActionType.DRAFT_SUPPLIER_INVOICE, payload)

        with self.assertRaisesRegex(PermitValidationError, "entity_id"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id="different-entity",
                payload=payload,
                permit=permit,
            )

    def test_live_supplier_invoice_draft_requires_explicit_config(self) -> None:
        transport = MockFortnoxTransport()
        adapter = FortnoxAdapter(
            config=FortnoxConfig(dry_run=False, allow_draft_writes=False),
            transport=transport,
        )
        payload = _supplier_invoice_payload(adapter)
        permit, permit_store, approval_authority = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
            return_store=True,
        )
        adapter.permit_validator = PermitValidator(
            clock=lambda: PERMIT_ISSUED_AT,
            permit_store=permit_store,
            approval_authority=approval_authority,
        )

        with self.assertRaises(FortnoxPolicyViolation):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_live_supplier_invoice_draft_rejects_draft_only_permit(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            ),
            transport=MockFortnoxTransport(),
        )
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(ActionType.DRAFT_SUPPLIER_INVOICE, payload)

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_live_supplier_invoice_draft_remains_blocked_after_permit_and_config(self) -> None:
        transport = MockFortnoxTransport()
        transport.add_post(
            "/supplierinvoices",
            {"SupplierInvoice": {"GivenNumber": "1001", "Booked": False}},
        )
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            ),
            transport=transport,
        )
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
        )

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )
        self.assertEqual([], transport.posts)

    def test_http_transport_post_requires_execution_permit(self) -> None:
        transport = HttpFortnoxTransport(
            FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            )
        )

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            transport.post(
                "/supplierinvoices",
                json_body={"SupplierInvoice": {"Booked": False}},
                idempotency_key="not-a-valid-permit-key",
                permit=None,  # type: ignore[arg-type]
            )

    def test_live_write_without_credentials_has_clear_error(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(dry_run=False, allow_draft_writes=True, access_token=None)
        )
        payload = _supplier_invoice_payload(adapter)
        permit = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
        )

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_voucher_draft_never_posts_live(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=False,
                allow_draft_writes=True,
            ),
            transport=MockFortnoxTransport(),
        )
        payload = adapter.prepare_voucher_draft_payload(
            transaction_date="2026-05-16",
            description="Dry-run voucher only",
            voucher_series="A",
            rows=[
                {"account": 4010, "debit": "1000.00"},
                {"account": 2440, "credit": "1000.00"},
            ],
        )
        permit = _permit_for(ActionType.DRAFT_VOUCHER, payload)

        with self.assertRaisesRegex(FortnoxPolicyViolation, "structurally disabled"):
            adapter.create_voucher_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

    def test_forbidden_payload_markers_are_blocked(self) -> None:
        adapter = FortnoxAdapter(
            config=FortnoxConfig(
                access_token="test-token",
                dry_run=True,
                allow_draft_writes=True,
            ),
            transport=MockFortnoxTransport(),
        )
        payload = _supplier_invoice_payload(adapter)
        payload["SupplierInvoice"]["Booked"] = True
        permit, permit_store, approval_authority = _permit_for(
            ActionType.DRAFT_SUPPLIER_INVOICE,
            payload,
            amount_minor=50_000_00,
            return_store=True,
        )
        adapter.permit_validator = PermitValidator(
            clock=lambda: PERMIT_ISSUED_AT,
            permit_store=permit_store,
            approval_authority=approval_authority,
        )

        with self.assertRaises(FortnoxProtectedOperation):
            adapter.create_supplier_invoice_draft(
                case_id="case_1",
                entity_id=ENTITY_ID,
                payload=payload,
                permit=permit,
            )

        with self.assertRaisesRegex(FortnoxProtectedOperation, "sent"):
            _assert_no_forbidden_payload_markers({"metadata": {"sent": True}})


class FortnoxPolicyProtectionTests(unittest.TestCase):
    def test_forbidden_fortnox_actions_are_policy_forbidden(self) -> None:
        for action_type in (
            ActionType.POST_VOUCHER,
            ActionType.SEND_INVOICE,
            ActionType.APPROVE_SUPPLIER_INVOICE,
            ActionType.START_PAYMENT,
            ActionType.DELETE_RECORD,
            ActionType.CHANGE_SETTINGS,
        ):
            decision = evaluate_policy(
                PolicyContext(action_type=action_type, client_id="client_123", currency_code="SEK")
            )
            self.assertEqual(
                PermissionMode.FORBIDDEN,
                decision.permission_mode,
                f"{action_type.value} should be blocked",
            )


def _supplier_invoice_payload(adapter: FortnoxAdapter) -> dict[str, Any]:
    return adapter.prepare_supplier_invoice_draft_payload(
        supplier_number="42",
        invoice_number="INV-123",
        invoice_date="2026-05-16",
        due_date="2026-06-15",
        total="1250.00",
        vat="250.00",
        rows=[{"account": 4010, "debit": "1000.00"}],
    )


def _permit_for(
    action_type: ActionType,
    payload: dict[str, Any],
    *,
    amount_minor: int = 1_250_00,
    return_store: bool = False,
):
    context = PolicyContext(
        action_type=action_type,
        client_id="client_123",
        currency_code="SEK",
        amount_minor=amount_minor,
        risk_evidence_complete=True,
    )
    permit, _, permit_store, approval_authority = issue_test_permit(
        context=context,
        case_id="case_1",
        payload=payload,
        now=PERMIT_ISSUED_AT,
        permit_id=f"permit_{action_type.value}",
        entity_id=ENTITY_ID,
    )
    if return_store:
        return permit, permit_store, approval_authority
    return permit


if __name__ == "__main__":
    unittest.main()
