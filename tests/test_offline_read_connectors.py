from __future__ import annotations

import ast
import hashlib
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
import json
from pathlib import Path
from collections.abc import Mapping

import accounting_agent
import accounting_agent.adapters as adapters
from accounting_agent.adapters.read_only import (
    FortnoxReadConnector,
    NetSuiteSuiteQLReadConnector,
    RawReadResponse,
    SemanticReadRequest,
    SemanticTransportIdentity,
    StrictReadDecodeError,
    decode_raw_json_object,
)
from accounting_agent.connector_contract import (
    AuthReference,
    ConnectorBinding,
    ConnectorCapability,
    ConnectorAdapter,
    ConnectorContractError,
    ConnectorEnvironment,
    ConnectorReadRequest,
    HealthStatus,
    RetryMetadata,
    raw_snapshot_sha256,
)
from accounting_agent.contracts import ConnectorConnection, ConnectorConnectionStatus


class OfflineReadConnectorPublicSurfaceTests(unittest.TestCase):
    def test_adapters_package_exposes_only_the_bounded_read_surface(self) -> None:
        for name in (
            "FortnoxReadConnector",
            "NetSuiteSuiteQLReadConnector",
            "RawReadResponse",
            "SemanticReadRequest",
            "SemanticReadTransport",
            "SemanticTransportIdentity",
            "StrictReadDecodeError",
            "decode_raw_json_object",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(adapters, name), name)

    def test_package_root_exports_the_bounded_read_surface(self) -> None:
        for name in (
            "FortnoxReadConnector",
            "NetSuiteSuiteQLReadConnector",
            "RawReadResponse",
            "SemanticReadRequest",
            "SemanticReadTransport",
            "SemanticTransportIdentity",
            "StrictReadDecodeError",
            "decode_raw_json_object",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(adapters, name), getattr(accounting_agent, name, None))
                self.assertIn(name, accounting_agent.__all__)

    def test_read_only_module_has_no_network_or_environment_credential_imports(self) -> None:
        path = Path(adapters.__file__).with_name("read_only.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(
            {"os", "socket", "urllib", "http", "httpx", "requests"}.isdisjoint(
                imported_roots
            )
        )


class StrictRawReadContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = ConnectorBinding(
            "tenant-001",
            "company-001",
            ConnectorEnvironment.SANDBOX,
            AuthReference("oauth-ref:connection-001"),
        )

    def test_semantic_request_is_immutable_hash_bound_and_has_no_url_or_sql_surface(self) -> None:
        request = SemanticReadRequest(
            connection_id="connection-001",
            connection_revision=2,
            connection_sha256="a" * 64,
            provider_id="fortnox",
            binding=self.binding,
            resource="accounts",
            capability=ConnectorCapability.READ_MASTER_DATA,
            operation_id="fortnox.accounts.v1",
            parameters=(("page", 1), ("page_size", 100)),
        )

        self.assertEqual(1, request.parameter_map["page"])
        self.assertEqual(100, request.parameter_map["page_size"])
        self.assertFalse(hasattr(request, "url"))
        self.assertFalse(hasattr(request, "headers"))
        self.assertFalse(hasattr(request, "query"))
        with self.assertRaises(FrozenInstanceError):
            request.provider_id = "netsuite"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            request.parameter_map["page"] = 2  # type: ignore[index]

    def test_semantic_request_hash_canonically_binds_every_authority_field(self) -> None:
        request = SemanticReadRequest(
            connection_id="connection-001",
            connection_revision=2,
            connection_sha256="a" * 64,
            provider_id="fortnox",
            binding=self.binding,
            resource="accounts",
            capability=ConnectorCapability.READ_MASTER_DATA,
            operation_id="fortnox.accounts.v1",
            parameters=(("page", 1), ("page_size", 100)),
        )
        expected_payload = {
            "schema": "accounting-agent-semantic-read-request-v1",
            "connection_id": "connection-001",
            "connection_revision": 2,
            "connection_sha256": "a" * 64,
            "provider_id": "fortnox",
            "binding": self.binding.to_dict(),
            "resource": "accounts",
            "capability": "read_master_data",
            "operation_id": "fortnox.accounts.v1",
            "parameters": [["page", 1], ["page_size", 100]],
        }
        expected = hashlib.sha256(
            json.dumps(
                expected_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(expected, request.canonical_sha256())
        variants = (
            replace(request, connection_id="connection-002"),
            replace(request, connection_revision=3),
            replace(request, connection_sha256="b" * 64),
            replace(request, provider_id="netsuite"),
            replace(request, binding=replace(self.binding, tenant_id="tenant-002")),
            replace(request, binding=replace(self.binding, company_id="company-002")),
            replace(
                request,
                binding=replace(
                    self.binding,
                    environment=ConnectorEnvironment.PRODUCTION,
                ),
            ),
            replace(
                request,
                binding=replace(
                    self.binding,
                    auth_reference=AuthReference("oauth-ref:connection-002"),
                ),
            ),
            replace(request, resource="suppliers"),
            replace(request, capability=ConnectorCapability.READ_PERIOD_LOCKS),
            replace(request, operation_id="fortnox.suppliers.v1"),
            replace(request, parameters=(("page", 2), ("page_size", 100))),
        )
        hashes = {request.canonical_sha256(), *(variant.canonical_sha256() for variant in variants)}
        self.assertEqual(1 + len(variants), len(hashes))

    def test_semantic_request_rejects_ambiguous_or_mutable_authority(self) -> None:
        values: dict[str, object] = {
            "connection_id": "connection-001",
            "connection_revision": 1,
            "connection_sha256": "a" * 64,
            "provider_id": "fortnox",
            "binding": self.binding,
            "resource": "accounts",
            "capability": ConnectorCapability.READ_MASTER_DATA,
            "operation_id": "fortnox.accounts.v1",
            "parameters": (("page", 1),),
        }
        for field_name, bad_value in (
            ("connection_revision", 0),
            ("connection_sha256", "not-a-hash"),
            ("provider_id", "fortnox\nother"),
            ("binding", object()),
            ("resource", "../accounts"),
            ("capability", ConnectorCapability.POST_JOURNAL),
            ("operation_id", ""),
            ("capability", "unknown_read"),
            ("parameters", [("page", 1)]),
            ("parameters", (("page",),)),
            ("parameters", (("page", True),)),
            ("parameters", (("page", ""),)),
            ("parameters", (("page", 1), ("page", 2))),
            ("parameters", (("url", "https://evil.invalid"),)),
        ):
            with self.subTest(field=field_name, bad=bad_value):
                candidate = dict(values)
                candidate[field_name] = bad_value
                with self.assertRaises((TypeError, ValueError)):
                    SemanticReadRequest(**candidate)  # type: ignore[arg-type]

    def test_raw_response_preserves_exact_immutable_bytes(self) -> None:
        raw = b'{"records":[]}'
        response = RawReadResponse(
            provider_id="fortnox",
            operation_id="fortnox.accounts.v1",
            request_sha256="a" * 64,
            status_code=200,
            content_type="application/json; charset=utf-8",
            body=raw,
            retry=RetryMetadata(1, 1, False),
        )

        self.assertIs(raw, response.body)
        self.assertEqual(raw, response.body)
        self.assertEqual("a" * 64, response.request_sha256)
        with self.assertRaises(FrozenInstanceError):
            response.body = b"{}"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            RawReadResponse(  # type: ignore[arg-type]
                provider_id="fortnox",
                operation_id="fortnox.accounts.v1",
                request_sha256="a" * 64,
                status_code=200,
                content_type="application/json",
                body=bytearray(raw),
                retry=RetryMetadata(1, 1, False),
            )

        valid: dict[str, object] = {
            "provider_id": "fortnox",
            "operation_id": "fortnox.accounts.v1",
            "request_sha256": "a" * 64,
            "status_code": 200,
            "content_type": "application/json",
            "body": raw,
            "retry": RetryMetadata(1, 1, False),
        }
        for field_name, bad_value in (
            ("status_code", True),
            ("status_code", 99),
            ("content_type", ""),
            ("content_type", " application/json"),
            ("retry", object()),
            ("request_sha256", "not-a-hash"),
        ):
            with self.subTest(field=field_name, bad=bad_value):
                candidate = dict(valid)
                candidate[field_name] = bad_value
                with self.assertRaises((TypeError, ValueError)):
                    RawReadResponse(**candidate)  # type: ignore[arg-type]

    def test_decoder_accepts_only_matching_successful_utf8_json_objects(self) -> None:
        response = RawReadResponse(
            provider_id="fortnox",
            operation_id="fortnox.accounts.v1",
            request_sha256="a" * 64,
            status_code=200,
            content_type="application/json",
            body=b'{"Accounts":[{"Number":"1930"}],"MetaInformation":{"@CurrentPage":1}}',
            retry=RetryMetadata(1, 1, False),
        )

        decoded = decode_raw_json_object(
            response,
            expected_provider_id="fortnox",
            expected_operation_id="fortnox.accounts.v1",
            expected_request_sha256="a" * 64,
        )

        self.assertEqual("1930", decoded["Accounts"][0]["Number"])  # type: ignore[index]

    def test_decoder_fails_closed_on_mismatch_malformed_or_oversized_data(self) -> None:
        cases = (
            ("provider", "netsuite", "fortnox.accounts.v1", 200, "application/json", b"{}"),
            ("operation", "fortnox", "fortnox.suppliers.v1", 200, "application/json", b"{}"),
            ("status", "fortnox", "fortnox.accounts.v1", 429, "application/json", b"{}"),
            ("media", "fortnox", "fortnox.accounts.v1", 200, "text/html", b"{}"),
            ("utf8", "fortnox", "fortnox.accounts.v1", 200, "application/json", b"\xff"),
            ("array", "fortnox", "fortnox.accounts.v1", 200, "application/json", b"[]"),
            (
                "duplicate",
                "fortnox",
                "fortnox.accounts.v1",
                200,
                "application/json",
                b'{"Accounts":[],"Accounts":[]}',
            ),
            ("constant", "fortnox", "fortnox.accounts.v1", 200, "application/json", b'{"n":NaN}'),
            (
                "positive_float_overflow",
                "fortnox",
                "fortnox.accounts.v1",
                200,
                "application/json",
                b'{"n":1e309}',
            ),
            (
                "negative_float_overflow",
                "fortnox",
                "fortnox.accounts.v1",
                200,
                "application/json",
                b'{"n":-1e309}',
            ),
            (
                "integer_overflow",
                "fortnox",
                "fortnox.accounts.v1",
                200,
                "application/json",
                b'{"n":9007199254740992}',
            ),
            ("oversized", "fortnox", "fortnox.accounts.v1", 200, "application/json", b'{"x":"123"}'),
        )
        for label, provider, operation, status, media_type, body in cases:
            with self.subTest(label=label):
                response = RawReadResponse(
                    provider_id=provider,
                    operation_id=operation,
                    request_sha256="a" * 64,
                    status_code=status,
                    content_type=media_type,
                    body=body,
                    retry=RetryMetadata(1, 1, False),
                )
                with self.assertRaises(StrictReadDecodeError):
                    decode_raw_json_object(
                        response,
                        expected_provider_id="fortnox",
                        expected_operation_id="fortnox.accounts.v1",
                        expected_request_sha256="a" * 64,
                        max_bytes=8 if label == "oversized" else 1024,
                    )

        replayed = replace(
            _raw_response("fortnox", "fortnox.accounts.v1", {}),
            request_sha256="b" * 64,
        )
        with self.assertRaisesRegex(StrictReadDecodeError, "request"):
            decode_raw_json_object(
                replayed,
                expected_provider_id="fortnox",
                expected_operation_id="fortnox.accounts.v1",
                expected_request_sha256="a" * 64,
            )

        with self.assertRaises(TypeError):
            decode_raw_json_object(  # type: ignore[arg-type]
                object(),
                expected_provider_id="fortnox",
                expected_operation_id="fortnox.accounts.v1",
                expected_request_sha256="a" * 64,
            )
        valid_response = _raw_response("fortnox", "fortnox.accounts.v1", {})
        for max_bytes in (0, True, 1.5):
            with self.subTest(max_bytes=max_bytes):
                with self.assertRaises(ValueError):
                    decode_raw_json_object(
                        valid_response,
                        expected_provider_id="fortnox",
                        expected_operation_id="fortnox.accounts.v1",
                        expected_request_sha256="0" * 64,
                        max_bytes=max_bytes,  # type: ignore[arg-type]
                    )


class _RecordingSemanticTransport:
    def __init__(
        self,
        responses: tuple[RawReadResponse, ...],
        *,
        connection: ConnectorConnection,
        bind_to_request: bool = True,
        identity: SemanticTransportIdentity | None = None,
        identity_after_read: SemanticTransportIdentity | None = None,
    ) -> None:
        self._responses = list(responses)
        self._bind_to_request = bind_to_request
        self._identity = identity or SemanticTransportIdentity(
            provider_id=connection.provider_id,
            connection_id=connection.connection_id,
            connection_revision=connection.revision,
            connection_sha256=connection.canonical_sha256(),
            binding=connection.binding,
        )
        self._identity_after_read = identity_after_read
        self.requests: list[SemanticReadRequest] = []

    @property
    def identity(self) -> SemanticTransportIdentity:
        return self._identity

    def read(self, request: SemanticReadRequest) -> RawReadResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("unexpected semantic transport read")
        response = self._responses.pop(0)
        if self._identity_after_read is not None:
            self._identity = self._identity_after_read
        if self._bind_to_request:
            return replace(response, request_sha256=request.canonical_sha256())
        return response


def _connection(
    provider_id: str,
    *,
    capabilities: tuple[ConnectorCapability, ...],
    status: ConnectorConnectionStatus = ConnectorConnectionStatus.ACTIVE,
) -> ConnectorConnection:
    return ConnectorConnection(
        connection_id=f"connection-{provider_id}-001",
        revision=3,
        tenant_id="tenant-001",
        client_id="client-001",
        legal_entity_id="entity-se-001",
        provider_id=provider_id,
        source_company_id=f"company-{provider_id}-001",
        environment=ConnectorEnvironment.SANDBOX,
        auth_reference=AuthReference(f"oauth-ref:{provider_id}-001"),
        capabilities=capabilities,
        status=status,
        recorded_at=datetime(2026, 7, 12, 8, tzinfo=UTC),
    )


def _raw_response(provider_id: str, operation_id: str, payload: object) -> RawReadResponse:
    return RawReadResponse(
        provider_id=provider_id,
        operation_id=operation_id,
        request_sha256="0" * 64,
        status_code=200,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        retry=RetryMetadata(1, 1, False),
    )


def _fortnox_payload(
    container: str,
    records: list[dict[str, object]],
    *,
    current_page: int = 1,
    total_pages: int = 1,
) -> dict[str, object]:
    return {
        container: records,
        "MetaInformation": {
            "@CurrentPage": current_page,
            "@TotalPages": total_pages,
            "@TotalResources": len(records) if total_pages == 1 else total_pages,
        },
    }


def _netsuite_payload(
    items: list[dict[str, object]],
    *,
    offset: int = 0,
    total_results: int | None = None,
) -> dict[str, object]:
    total = len(items) if total_results is None else total_results
    return {
        "links": [{"rel": "self", "href": "https://hostile.invalid/never-follow"}],
        "count": len(items),
        "hasMore": offset + len(items) < total,
        "items": items,
        "offset": offset,
        "totalResults": total,
    }


class FortnoxOfflineReadConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = _connection(
            "fortnox",
            capabilities=(ConnectorCapability.READ_MASTER_DATA,),
        )

    def test_reads_only_the_three_fixed_resources_and_hashes_exact_raw_bytes(self) -> None:
        examples = (
            (
                "accounts",
                "Accounts",
                {
                    "Active": True,
                    "BalanceBroughtForward": 0,
                    "CostCenter": "",
                    "CostCenterSettings": "Allowed",
                    "Description": "Bank account",
                    "Number": "1930",
                    "Project": "",
                    "ProjectSettings": "Allowed",
                    "SRU": 0,
                    "Year": 2026,
                },
                ConnectorCapability.READ_MASTER_DATA,
            ),
            (
                "suppliers",
                "Suppliers",
                {
                    "Active": True,
                    "Address1": "Synthetic Street 1",
                    "City": "Stockholm",
                    "CountryCode": "SE",
                    "Currency": "SEK",
                    "Email": "synthetic@example.invalid",
                    "Name": "Synthetic Supplier AB",
                    "OrganisationNumber": "556000-0000",
                    "SupplierNumber": "SYN-001",
                    "VATNumber": "SE556000000001",
                    "ZipCode": "11122",
                },
                ConnectorCapability.READ_MASTER_DATA,
            ),
            (
                "financial_years",
                "FinancialYears",
                {
                    "AccountingMethod": "ACCRUAL",
                    "FromDate": "2026-01-01",
                    "Id": 2026,
                    "ToDate": "2026-12-31",
                    "Year": 2026,
                },
                ConnectorCapability.READ_MASTER_DATA,
            ),
        )
        for resource, container, record, capability in examples:
            with self.subTest(resource=resource):
                response = _raw_response(
                    "fortnox",
                    f"fortnox.{resource}.v1",
                    _fortnox_payload(container, [record]),
                )
                transport = _RecordingSemanticTransport(
                    (response,),
                    connection=self.connection,
                )
                connector = FortnoxReadConnector(self.connection, transport)

                page = connector.read_page(
                    ConnectorReadRequest(
                        binding=self.connection.binding,
                        resource=resource,
                        cursor="page:1",
                        page_size=25,
                    )
                )

                self.assertEqual((record,), page.records)
                self.assertEqual(raw_snapshot_sha256(response.body), page.raw_snapshot_hash)
                self.assertEqual("page:1", page.source_cursor)
                self.assertIsNone(page.next_cursor)
                semantic = transport.requests[0]
                self.assertEqual(capability, semantic.capability)
                self.assertEqual(f"fortnox.{resource}.v1", semantic.operation_id)
                self.assertEqual({"page": 1, "page_size": 25}, dict(semantic.parameter_map))
                self.assertEqual(self.connection.canonical_sha256(), semantic.connection_sha256)

    def test_derives_next_page_from_metadata_and_never_from_a_hostile_link(self) -> None:
        payload = _fortnox_payload(
            "Accounts",
            [{"Number": "1930", "Description": "Bank"}],
            current_page=1,
            total_pages=2,
        )
        payload["links"] = [{"href": "https://hostile.invalid/page:999"}]
        response = _raw_response("fortnox", "fortnox.accounts.v1", payload)
        transport = _RecordingSemanticTransport(
            (response,),
            connection=self.connection,
        )
        connector = FortnoxReadConnector(self.connection, transport)

        page = connector.read_page(
            ConnectorReadRequest(self.connection.binding, "accounts", page_size=1)
        )

        self.assertEqual("page:2", page.next_cursor)
        self.assertEqual(1, len(transport.requests))

    def test_returned_records_are_recursively_immutable_evidence(self) -> None:
        response = _raw_response(
            "fortnox",
            "fortnox.accounts.v1",
            _fortnox_payload(
                "Accounts",
                [
                    {
                        "Number": "1930",
                        "Metadata": {
                            "labels": ["cash", {"source": "synthetic"}],
                            "flags": {"active": True},
                        },
                    }
                ],
            ),
        )
        connector = FortnoxReadConnector(
            self.connection,
            _RecordingSemanticTransport(
                (response,),
                connection=self.connection,
            ),
        )

        page = connector.read_page(
            ConnectorReadRequest(
                self.connection.binding,
                "accounts",
                cursor="page:1",
                page_size=1,
            )
        )
        record = page.records[0]
        metadata = record["Metadata"]
        self.assertIsInstance(record, Mapping)
        self.assertIsInstance(metadata, Mapping)
        labels = metadata["labels"]  # type: ignore[index]
        self.assertIsInstance(labels, tuple)
        original_hash = page.raw_snapshot_hash

        with self.assertRaises(TypeError):
            record["Number"] = "1940"  # type: ignore[index]
        with self.assertRaises(TypeError):
            metadata["flags"] = {}  # type: ignore[index]
        with self.assertRaises(TypeError):
            metadata["flags"]["active"] = False  # type: ignore[index]
        with self.assertRaises(TypeError):
            labels[1]["source"] = "changed"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            labels.append("changed")  # type: ignore[attr-defined]
        self.assertEqual(original_hash, page.raw_snapshot_hash)

    def test_rejects_cross_connection_scope_revision_and_request_replay(self) -> None:
        expected_request = SemanticReadRequest(
            connection_id=self.connection.connection_id,
            connection_revision=self.connection.revision,
            connection_sha256=self.connection.canonical_sha256(),
            provider_id="fortnox",
            binding=self.connection.binding,
            resource="accounts",
            capability=ConnectorCapability.READ_MASTER_DATA,
            operation_id="fortnox.accounts.v1",
            parameters=(("page", 1), ("page_size", 1)),
        )
        variants = (
            replace(expected_request, connection_id="connection-fortnox-replayed"),
            replace(expected_request, connection_revision=4),
            replace(expected_request, connection_sha256="f" * 64),
            replace(
                expected_request,
                binding=replace(self.connection.binding, tenant_id="tenant-replayed"),
            ),
            replace(
                expected_request,
                binding=replace(self.connection.binding, company_id="company-replayed"),
            ),
            replace(
                expected_request,
                binding=replace(
                    self.connection.binding,
                    environment=ConnectorEnvironment.PRODUCTION,
                ),
            ),
            replace(
                expected_request,
                binding=replace(
                    self.connection.binding,
                    auth_reference=AuthReference("oauth-ref:replayed"),
                ),
            ),
            replace(expected_request, resource="suppliers"),
            replace(expected_request, capability=ConnectorCapability.READ_PERIOD_LOCKS),
            replace(expected_request, operation_id="fortnox.suppliers.v1"),
            replace(
                expected_request,
                parameters=(("page", 2), ("page_size", 1)),
            ),
        )
        for replayed_request in variants:
            with self.subTest(replay_hash=replayed_request.canonical_sha256()):
                response = replace(
                    _raw_response(
                        "fortnox",
                        "fortnox.accounts.v1",
                        _fortnox_payload("Accounts", [{"Number": "1930"}]),
                    ),
                    request_sha256=replayed_request.canonical_sha256(),
                )
                transport = _RecordingSemanticTransport(
                    (response,),
                    connection=self.connection,
                    bind_to_request=False,
                )
                connector = FortnoxReadConnector(self.connection, transport)

                with self.assertRaisesRegex(StrictReadDecodeError, "request binding"):
                    connector.read_page(
                        ConnectorReadRequest(
                            self.connection.binding,
                            "accounts",
                            cursor="page:1",
                            page_size=1,
                        )
                    )
                self.assertEqual(1, len(transport.requests))

    def test_rejects_mismatched_transport_identity_before_any_read(self) -> None:
        expected = SemanticTransportIdentity(
            provider_id="fortnox",
            connection_id=self.connection.connection_id,
            connection_revision=self.connection.revision,
            connection_sha256=self.connection.canonical_sha256(),
            binding=self.connection.binding,
        )
        variants = (
            replace(expected, provider_id="netsuite"),
            replace(expected, connection_id="connection-fortnox-other"),
            replace(expected, connection_revision=4),
            replace(expected, connection_sha256="f" * 64),
            replace(
                expected,
                binding=replace(self.connection.binding, tenant_id="tenant-other"),
            ),
            replace(
                expected,
                binding=replace(self.connection.binding, company_id="company-other"),
            ),
            replace(
                expected,
                binding=replace(
                    self.connection.binding,
                    environment=ConnectorEnvironment.PRODUCTION,
                ),
            ),
            replace(
                expected,
                binding=replace(
                    self.connection.binding,
                    auth_reference=AuthReference("oauth-ref:other-connection"),
                ),
            ),
        )
        with self.assertRaises(FrozenInstanceError):
            expected.provider_id = "netsuite"  # type: ignore[misc]

        for identity in variants:
            with self.subTest(identity=identity):
                transport = _RecordingSemanticTransport(
                    (),
                    connection=self.connection,
                    identity=identity,
                )
                with self.assertRaisesRegex(
                    ConnectorContractError,
                    "transport identity",
                ):
                    FortnoxReadConnector(self.connection, transport)
                self.assertEqual([], transport.requests)

    def test_rejects_transport_identity_drift_after_the_read(self) -> None:
        drifted = SemanticTransportIdentity(
            provider_id="fortnox",
            connection_id=self.connection.connection_id,
            connection_revision=self.connection.revision,
            connection_sha256=self.connection.canonical_sha256(),
            binding=replace(
                self.connection.binding,
                environment=ConnectorEnvironment.PRODUCTION,
            ),
        )
        response = _raw_response(
            "fortnox",
            "fortnox.accounts.v1",
            _fortnox_payload("Accounts", [{"Number": "1930"}]),
        )
        transport = _RecordingSemanticTransport(
            (response,),
            connection=self.connection,
            identity_after_read=drifted,
        )
        connector = FortnoxReadConnector(self.connection, transport)

        with self.assertRaisesRegex(ConnectorContractError, "identity changed"):
            connector.read_page(
                ConnectorReadRequest(
                    self.connection.binding,
                    "accounts",
                    cursor="page:1",
                    page_size=1,
                )
            )
        self.assertEqual(1, len(transport.requests))

    def test_rejects_noncanonical_page_cursors_before_transport(self) -> None:
        for cursor in (
            "page:0",
            "page:-1",
            "page:01",
            "page:+1",
            "page: 1",
            "page:1 ",
            "page:1&url=https://evil.invalid",
            "offset:0",
            "https://evil.invalid",
            "PAGE:1",
        ):
            with self.subTest(cursor=cursor):
                transport = _RecordingSemanticTransport(
                    (),
                    connection=self.connection,
                )
                connector = FortnoxReadConnector(self.connection, transport)
                with self.assertRaisesRegex(ConnectorContractError, "page:<positive-int>"):
                    connector.read_page(
                        ConnectorReadRequest(
                            self.connection.binding,
                            "accounts",
                            cursor=cursor,
                        )
                    )
                self.assertEqual([], transport.requests)

    def test_rejects_scope_resource_and_capability_before_transport(self) -> None:
        cases = (
            (
                self.connection,
                ConnectorReadRequest(
                    ConnectorBinding(
                        "tenant-other",
                        self.connection.source_company_id,
                        ConnectorEnvironment.SANDBOX,
                    ),
                    "accounts",
                ),
            ),
            (self.connection, ConnectorReadRequest(self.connection.binding, "transactions")),
            (
                _connection(
                    "fortnox",
                    capabilities=(ConnectorCapability.READ_PERIOD_LOCKS,),
                ),
                ConnectorReadRequest(self.connection.binding, "accounts"),
            ),
        )
        for connection, request in cases:
            with self.subTest(resource=request.resource):
                transport = _RecordingSemanticTransport(
                    (),
                    connection=connection,
                )
                connector = FortnoxReadConnector(connection, transport)
                with self.assertRaises(ConnectorContractError):
                    connector.read_page(request)
                self.assertEqual([], transport.requests)

    def test_requires_an_active_provider_matching_connection_and_injected_transport(self) -> None:
        valid_transport = _RecordingSemanticTransport(
            (),
            connection=self.connection,
        )
        for connection in (
            _connection(
                "netsuite",
                capabilities=(ConnectorCapability.READ_MASTER_DATA,),
            ),
            _connection(
                "fortnox",
                capabilities=(ConnectorCapability.READ_MASTER_DATA,),
                status=ConnectorConnectionStatus.SUSPENDED,
            ),
        ):
            with self.subTest(connection=connection.provider_id, status=connection.status):
                with self.assertRaises(ConnectorContractError):
                    FortnoxReadConnector(connection, valid_transport)
        with self.assertRaises(TypeError):
            FortnoxReadConnector(self.connection, object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            FortnoxReadConnector(object(), valid_transport)  # type: ignore[arg-type]
        connector = FortnoxReadConnector(self.connection, valid_transport)
        with self.assertRaises(TypeError):
            connector.read_page(object())  # type: ignore[arg-type]

    def test_strictly_rejects_incoherent_provider_metadata(self) -> None:
        malformed_payloads = (
            {"Accounts": []},
            _fortnox_payload("Suppliers", [], current_page=1),
            _fortnox_payload("Accounts", [], current_page=2, total_pages=2),
            {
                "Accounts": [{"Number": "1930"}, {"Number": "1940"}],
                "MetaInformation": {
                    "@CurrentPage": 1,
                    "@TotalPages": 1,
                    "@TotalResources": 2,
                },
            },
            {
                "Accounts": "not-an-array",
                "MetaInformation": {
                    "@CurrentPage": 1,
                    "@TotalPages": 1,
                    "@TotalResources": 0,
                },
            },
            {"Accounts": [], "MetaInformation": []},
            {
                "Accounts": [],
                "MetaInformation": {
                    "@CurrentPage": 0,
                    "@TotalPages": 1,
                    "@TotalResources": 0,
                },
            },
            {
                "Accounts": [],
                "MetaInformation": {
                    "@CurrentPage": 1,
                    "@TotalPages": 1,
                    "@TotalResources": -1,
                },
            },
            {
                "Accounts": [{"Number": "1930"}],
                "MetaInformation": {
                    "@CurrentPage": 1,
                    "@TotalPages": 1,
                    "@TotalResources": 0,
                },
            },
        )
        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                response = _raw_response("fortnox", "fortnox.accounts.v1", payload)
                transport = _RecordingSemanticTransport(
                    (response,),
                    connection=self.connection,
                )
                connector = FortnoxReadConnector(self.connection, transport)
                with self.assertRaises(StrictReadDecodeError):
                    connector.read_page(
                        ConnectorReadRequest(
                            self.connection.binding,
                            "accounts",
                            cursor="page:1",
                            page_size=1,
                        )
                    )

    def test_rejects_total_pages_before_the_requested_current_page(self) -> None:
        response = _raw_response(
            "fortnox",
            "fortnox.accounts.v1",
            {
                "Accounts": [],
                "MetaInformation": {
                    "@CurrentPage": 2,
                    "@TotalPages": 1,
                    "@TotalResources": 0,
                },
            },
        )
        connector = FortnoxReadConnector(
            self.connection,
            _RecordingSemanticTransport(
                (response,),
                connection=self.connection,
            ),
        )

        with self.assertRaisesRegex(StrictReadDecodeError, "cannot precede"):
            connector.read_page(
                ConnectorReadRequest(
                    self.connection.binding,
                    "accounts",
                    cursor="page:2",
                )
            )


class NetSuiteOfflineReadConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = _connection(
            "netsuite",
            capabilities=(
                ConnectorCapability.READ_MASTER_DATA,
                ConnectorCapability.READ_PERIOD_LOCKS,
            ),
        )

    def test_reads_only_fixed_versioned_templates_with_offset_paging(self) -> None:
        examples = (
            ("subsidiaries", {"id": "1", "name": "Synthetic Sweden AB"}, ConnectorCapability.READ_MASTER_DATA),
            ("accounts", {"id": "1930", "acctNumber": "1930", "acctName": "Bank"}, ConnectorCapability.READ_MASTER_DATA),
            ("vendors", {"id": "42", "entityId": "SYN-001", "companyName": "Synthetic Supplier AB"}, ConnectorCapability.READ_MASTER_DATA),
            ("accounting_periods", {"id": "2026-01", "periodName": "Jan 2026", "isClosed": False}, ConnectorCapability.READ_PERIOD_LOCKS),
        )
        for resource, record, capability in examples:
            with self.subTest(resource=resource):
                provider_record = {
                    "links": [{"rel": "self", "href": "https://hostile.invalid/item"}],
                    **record,
                }
                operation = f"netsuite.suiteql.{resource}.v1"
                response = _raw_response(
                    "netsuite",
                    operation,
                    _netsuite_payload([provider_record], offset=0, total_results=2),
                )
                transport = _RecordingSemanticTransport(
                    (response,),
                    connection=self.connection,
                )
                connector = NetSuiteSuiteQLReadConnector(self.connection, transport)

                page = connector.read_page(
                    ConnectorReadRequest(
                        self.connection.binding,
                        resource,
                        cursor=None if resource == "subsidiaries" else "offset:0",
                        page_size=1,
                    )
                )

                self.assertEqual((record,), page.records)
                self.assertEqual("offset:1", page.next_cursor)
                self.assertEqual(raw_snapshot_sha256(response.body), page.raw_snapshot_hash)
                semantic = transport.requests[0]
                self.assertEqual(operation, semantic.operation_id)
                self.assertEqual(capability, semantic.capability)
                self.assertEqual({"offset": 0, "page_size": 1}, dict(semantic.parameter_map))
                self.assertFalse(hasattr(semantic, "query"))

    def test_resource_and_template_maps_are_immutable(self) -> None:
        connector = NetSuiteSuiteQLReadConnector(
            self.connection,
            _RecordingSemanticTransport(
                (),
                connection=self.connection,
            ),
        )

        self.assertEqual(
            "netsuite.suiteql.accounts.v1",
            connector.operation_ids["accounts"],
        )
        with self.assertRaises(TypeError):
            connector.operation_ids["accounts"] = "netsuite.suiteql.evil.v1"  # type: ignore[index]
        with self.assertRaises(TypeError):
            connector.resource_capabilities["accounts"] = ConnectorCapability.READ_TRANSACTIONS  # type: ignore[index]
        self.assertFalse(hasattr(connector, "execute_sql"))
        self.assertFalse(hasattr(connector, "query"))
        self.assertFalse(hasattr(connector, "complete_sync"))
        self.assertFalse(hasattr(connector, "reconcile"))

    def test_concrete_connectors_satisfy_protocol_report_offline_health_and_have_no_writes(self) -> None:
        connectors = (
            FortnoxReadConnector(
                _connection(
                    "fortnox",
                    capabilities=(ConnectorCapability.READ_MASTER_DATA,),
                ),
                _RecordingSemanticTransport(
                    (),
                    connection=_connection(
                        "fortnox",
                        capabilities=(ConnectorCapability.READ_MASTER_DATA,),
                    ),
                ),
            ),
            NetSuiteSuiteQLReadConnector(
                self.connection,
                _RecordingSemanticTransport(
                    (),
                    connection=self.connection,
                ),
            ),
        )
        for connector in connectors:
            with self.subTest(provider=connector.provider_id):
                self.assertIsInstance(connector, ConnectorAdapter)
                health = connector.check_health()
                self.assertEqual(HealthStatus.NOT_CONFIGURED, health.status)
                self.assertEqual("offline_transport_health_unavailable", health.detail_code)
                for forbidden_name in (
                    "approve",
                    "create_draft",
                    "execute_sql",
                    "post",
                    "query",
                    "send",
                    "write",
                ):
                    self.assertFalse(hasattr(connector, forbidden_name), forbidden_name)
                with self.assertRaises((AttributeError, FrozenInstanceError)):
                    connector._connection = _connection(  # type: ignore[attr-defined]
                        connector.provider_id,
                        capabilities=(ConnectorCapability.READ_MASTER_DATA,),
                    )

    def test_rejects_noncanonical_offsets_before_transport(self) -> None:
        for cursor in (
            "offset:-1",
            "offset:01",
            "offset:+1",
            "offset: 1",
            "offset:1 ",
            "offset:1&query=SELECT",
            "page:1",
            "https://evil.invalid",
            "OFFSET:0",
        ):
            with self.subTest(cursor=cursor):
                transport = _RecordingSemanticTransport(
                    (),
                    connection=self.connection,
                )
                connector = NetSuiteSuiteQLReadConnector(self.connection, transport)
                with self.assertRaisesRegex(
                    ConnectorContractError,
                    "offset:<non-negative-int>",
                ):
                    connector.read_page(
                        ConnectorReadRequest(
                            self.connection.binding,
                            "accounts",
                            cursor=cursor,
                        )
                    )
                self.assertEqual([], transport.requests)

    def test_rejects_offsets_not_divisible_by_page_size_before_transport(self) -> None:
        transport = _RecordingSemanticTransport(
            (),
            connection=self.connection,
        )
        connector = NetSuiteSuiteQLReadConnector(self.connection, transport)

        with self.assertRaisesRegex(ConnectorContractError, "divisible by page_size"):
            connector.read_page(
                ConnectorReadRequest(
                    self.connection.binding,
                    "accounts",
                    cursor="offset:1",
                    page_size=50,
                )
            )

        self.assertEqual([], transport.requests)

    def test_rejects_partial_nonterminal_pages(self) -> None:
        response = _raw_response(
            "netsuite",
            "netsuite.suiteql.accounts.v1",
            _netsuite_payload([{"id": "1"}], offset=0, total_results=3),
        )
        connector = NetSuiteSuiteQLReadConnector(
            self.connection,
            _RecordingSemanticTransport(
                (response,),
                connection=self.connection,
            ),
        )

        with self.assertRaisesRegex(StrictReadDecodeError, "full page"):
            connector.read_page(
                ConnectorReadRequest(
                    self.connection.binding,
                    "accounts",
                    cursor="offset:0",
                    page_size=2,
                )
            )

    def test_rejects_resource_scope_and_capability_before_transport(self) -> None:
        no_master = _connection(
            "netsuite",
            capabilities=(ConnectorCapability.READ_PERIOD_LOCKS,),
        )
        cases = (
            (self.connection, ConnectorReadRequest(self.connection.binding, "transactions")),
            (no_master, ConnectorReadRequest(no_master.binding, "accounts")),
            (
                self.connection,
                ConnectorReadRequest(
                    ConnectorBinding(
                        "tenant-evil",
                        self.connection.source_company_id,
                        ConnectorEnvironment.SANDBOX,
                    ),
                    "accounts",
                ),
            ),
        )
        for connection, request in cases:
            with self.subTest(resource=request.resource):
                transport = _RecordingSemanticTransport(
                    (),
                    connection=connection,
                )
                connector = NetSuiteSuiteQLReadConnector(connection, transport)
                with self.assertRaises(ConnectorContractError):
                    connector.read_page(request)
                self.assertEqual([], transport.requests)

    def test_rejects_inactive_wrong_provider_and_non_transport_instances(self) -> None:
        for connection in (
            _connection(
                "fortnox",
                capabilities=(ConnectorCapability.READ_MASTER_DATA,),
            ),
            _connection(
                "netsuite",
                capabilities=(ConnectorCapability.READ_MASTER_DATA,),
                status=ConnectorConnectionStatus.REVOKED,
            ),
        ):
            with self.subTest(provider=connection.provider_id, status=connection.status):
                with self.assertRaises(ConnectorContractError):
                    NetSuiteSuiteQLReadConnector(
                        connection,
                        _RecordingSemanticTransport((), connection=connection),
                    )
        with self.assertRaises(TypeError):
            NetSuiteSuiteQLReadConnector(self.connection, object())  # type: ignore[arg-type]

    def test_strictly_rejects_incoherent_suiteql_envelopes(self) -> None:
        malformed_payloads = (
            {"items": [], "count": 0, "hasMore": False, "offset": 0, "totalResults": 0},
            _netsuite_payload([{"id": "1"}], offset=1, total_results=2),
            {
                "links": [],
                "count": 0,
                "hasMore": False,
                "items": "not-an-array",
                "offset": 0,
                "totalResults": 0,
            },
            {
                "links": [],
                "count": -1,
                "hasMore": False,
                "items": [],
                "offset": 0,
                "totalResults": 0,
            },
            {
                "links": [],
                "count": 0,
                "hasMore": "false",
                "items": [],
                "offset": 0,
                "totalResults": 0,
            },
            {
                "links": [],
                "count": 1,
                "hasMore": False,
                "items": [{"id": "1"}],
                "offset": 0,
                "totalResults": 2,
            },
            {
                "links": [],
                "count": 2,
                "hasMore": False,
                "items": [{"id": "1"}],
                "offset": 0,
                "totalResults": 1,
            },
            {
                "links": [],
                "count": 0,
                "hasMore": True,
                "items": [],
                "offset": 0,
                "totalResults": 1,
            },
            {
                "links": [],
                "count": 2,
                "hasMore": False,
                "items": [{"id": "1"}, {"id": "2"}],
                "offset": 0,
                "totalResults": 2,
            },
        )
        for payload in malformed_payloads:
            with self.subTest(payload=payload):
                response = _raw_response(
                    "netsuite",
                    "netsuite.suiteql.accounts.v1",
                    payload,
                )
                transport = _RecordingSemanticTransport(
                    (response,),
                    connection=self.connection,
                )
                connector = NetSuiteSuiteQLReadConnector(self.connection, transport)
                with self.assertRaises(StrictReadDecodeError):
                    connector.read_page(
                        ConnectorReadRequest(
                            self.connection.binding,
                            "accounts",
                            cursor="offset:0",
                            page_size=1,
                        )
                    )


if __name__ == "__main__":
    unittest.main()
