from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import accounting_agent.autonomy as autonomy_module
import accounting_agent.connector_contract as connector_module
from accounting_agent.autonomy import (
    AUTONOMY_LADDER,
    SAFE_PERMISSION_CEILING,
    AutonomyPlan,
    AutonomyRunState,
    AutonomyStage,
    CheckpointedAutonomyRunner,
    PreparationCapabilities,
    ProcessorCapabilityDenied,
    ProcessorResult,
    SQLiteAutonomyStore,
    StageCheckpoint,
    StageState,
    TrustedPreparationProcessor,
    trusted_preparation_processor,
)
from accounting_agent.connector_contract import (
    AuthReference,
    CapabilityDeclaration,
    CapabilityMode,
    ConnectorBinding,
    ConnectorCapability,
    ConnectorContractError,
    ConnectorEnvironment,
    ConnectorGuard,
    ConnectorHealth,
    ConnectorManifest,
    ConnectorPage,
    ConnectorReadRequest,
    HealthStatus,
    PaginationContract,
    PaginationMode,
    ProviderLifecycle,
    RetryMetadata,
    assert_v1_preview_registry_safe,
    evaluate_connector_conformance,
    get_connector_manifest,
    raw_snapshot_sha256,
    read_connector_page_guarded,
    require_guarded_read_request,
)
from accounting_agent.external_writes import FortnoxWriteAdapter
from accounting_agent.permits import PermitValidator
from accounting_agent.policy import ActionType, PermissionMode, PolicyContext
from accounting_agent.restricted_fortnox_mcp import (
    MCPPermissionMode,
    RestrictedFortnoxMCP,
    RestrictedToolForbidden,
    RestrictedToolMetadata,
    RestrictedToolPermitError,
    ToolCallAuditLog,
    UnknownRestrictedTool,
)
from tests.permit_approval_helpers import issue_test_permit

NOW = datetime(2026, 7, 11, 9, 0, tzinfo=UTC)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _plan(*, plan_id: str = "safety-plan") -> AutonomyPlan:
    return AutonomyPlan(
        plan_id=plan_id,
        client_id="synthetic-client",
        entity_id="synthetic-entity",
        case_id="synthetic-case",
        environment="preview",
        data_classification="synthetic",
        evidence_hashes=(_sha("evidence-a"), _sha("evidence-b")),
    )


def _trusted_processors(callback, *, environment: str = "preview"):
    processor = trusted_preparation_processor(callback, environment=environment)
    return {stage: processor for stage in AUTONOMY_LADDER}


class AutonomySafetyBranchTests(unittest.TestCase):
    def test_plan_and_processor_validation_fail_closed(self) -> None:
        base = _plan()
        invalid_changes = (
            {"data_classification": "client_data"},
            {"stages": tuple(reversed(AUTONOMY_LADDER))},
            {"permission_ceiling": SAFE_PERMISSION_CEILING + ("post_journal",)},
            {"evidence_hashes": ()},
            {"evidence_hashes": (_sha("duplicate"), _sha("duplicate"))},
            {"evidence_hashes": ("A" * 64,)},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    replace(base, **changes)

        with self.assertRaises(TypeError):
            ProcessorResult("not an object", [])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ProcessorResult(
                "conflicting outcome",
                {},
                requires_review=True,
                blocked_reason="also blocked",
            )
        with self.assertRaises(TypeError):
            trusted_preparation_processor(None, environment="preview")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            TrustedPreparationProcessor(
                lambda context: ProcessorResult("unused", {}),
                environment="preview",
                _factory_token=object(),
            )

        capabilities = PreparationCapabilities(SAFE_PERMISSION_CEILING)
        capabilities.require("read_fixture_evidence")
        self.assertEqual((), capabilities.denied)

    def test_store_rejects_tampering_stale_leases_and_unknown_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "autonomy.sqlite"
            store = SQLiteAutonomyStore(database)
            plan = _plan()
            run_id = store.create(plan, created_at=NOW)

            self.assertEqual(run_id, store.create(plan, created_at=NOW))
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "UPDATE autonomy_runs SET plan_digest = ? WHERE run_id = ?",
                    (_sha("forged-plan"), run_id),
                )
            with self.assertRaises(RuntimeError):
                store.create(plan, created_at=NOW)
            with self.assertRaises(RuntimeError):
                store.load_plan(run_id)
            with self.assertRaises(KeyError):
                store.state("run_unknown")
            with self.assertRaises(KeyError):
                store.cancel_run(
                    "run_unknown",
                    plan,
                    reason="synthetic operator cancellation",
                    updated_at=NOW,
                )

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "leases.sqlite")
            plan = _plan(plan_id="lease-plan")
            run_id = store.create(plan, created_at=NOW)
            with self.assertRaises(ValueError):
                store.acquire_execution_lease(
                    run_id,
                    lease_token="invalid-expiry",
                    updated_at=NOW,
                    expires_at=NOW,
                )
            self.assertTrue(
                store.acquire_execution_lease(
                    run_id,
                    lease_token="active-worker",
                    updated_at=NOW,
                    expires_at=NOW + timedelta(seconds=30),
                )
            )
            with self.assertRaises(ValueError):
                store.heartbeat_execution_lease(
                    run_id,
                    lease_token="active-worker",
                    updated_at=NOW + timedelta(seconds=1),
                    expires_at=NOW + timedelta(seconds=1),
                )
            stale = StageCheckpoint(
                stage=AutonomyStage.COLLECT,
                state=StageState.COMPLETED,
                summary="stale worker output",
                output_hash=_sha("stale-output"),
                attempt=1,
                completed_at=NOW + timedelta(seconds=1),
            )
            self.assertFalse(
                store.commit_checkpoint_if_leased(
                    run_id,
                    stale,
                    lease_token="stolen-worker-token",
                    output={"synthetic": True},
                    run_state=AutonomyRunState.RUNNING,
                )
            )
            self.assertEqual((), store.checkpoints(run_id))

    def test_cancellation_preserves_completed_work_and_marks_failed_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "cancel.sqlite")
            plan = _plan(plan_id="cancel-checkpoints")
            run_id = store.create(plan, created_at=NOW)
            self.assertTrue(
                store.acquire_execution_lease(
                    run_id,
                    lease_token="worker",
                    updated_at=NOW,
                    expires_at=NOW + timedelta(minutes=1),
                )
            )
            completed = StageCheckpoint(
                stage=AutonomyStage.COLLECT,
                state=StageState.COMPLETED,
                summary="collection checkpointed",
                output_hash=_sha("collect-output"),
                attempt=1,
                completed_at=NOW + timedelta(seconds=1),
            )
            self.assertTrue(
                store.commit_checkpoint_if_leased(
                    run_id,
                    completed,
                    lease_token="worker",
                    output={"stage": "collect"},
                    run_state=AutonomyRunState.RUNNING,
                )
            )
            failed = StageCheckpoint(
                stage=AutonomyStage.EXTRACT,
                state=StageState.FAILED,
                summary="synthetic crash",
                output_hash=None,
                attempt=2,
                completed_at=NOW + timedelta(seconds=2),
                error="worker_crash",
            )
            self.assertTrue(
                store.commit_checkpoint_if_leased(
                    run_id,
                    failed,
                    lease_token="worker",
                    output=None,
                    run_state=AutonomyRunState.INTERRUPTED,
                )
            )

            store.cancel_run(
                run_id,
                plan,
                reason="authorized synthetic stop",
                updated_at=NOW + timedelta(seconds=3),
            )
            checkpoints = {item.stage: item for item in store.checkpoints(run_id)}
            self.assertIs(checkpoints[AutonomyStage.COLLECT].state, StageState.COMPLETED)
            self.assertIs(checkpoints[AutonomyStage.EXTRACT].state, StageState.CANCELLED)
            self.assertEqual(2, checkpoints[AutonomyStage.EXTRACT].attempt)
            self.assertTrue(
                all(
                    item.state is StageState.CANCELLED
                    for stage, item in checkpoints.items()
                    if stage is not AutonomyStage.COLLECT
                )
            )

    def test_legacy_store_adds_both_lease_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    """
                    CREATE TABLE autonomy_runs (
                        run_id TEXT PRIMARY KEY,
                        plan_id TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        plan_digest TEXT NOT NULL,
                        plan_json TEXT NOT NULL,
                        state TEXT NOT NULL,
                        cancel_reason TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
            SQLiteAutonomyStore(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(autonomy_runs)"
                    ).fetchall()
                }
            self.assertIn("lease_token", columns)
            self.assertIn("lease_expires_at", columns)

    def test_runner_blocks_missing_or_environment_mismatched_processors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "runner.sqlite")
            missing_runner = CheckpointedAutonomyRunner(
                store,
                processors={},
                clock=lambda: NOW,
            )
            missing_id = missing_runner.create_run(_plan(plan_id="missing-processor"))
            missing = missing_runner.run(
                run_id=missing_id,
                client_id="synthetic-client",
            )
            self.assertIs(missing.state, AutonomyRunState.BLOCKED)
            self.assertEqual("processor_missing", missing.stages[-1].error)

            mismatch_runner = CheckpointedAutonomyRunner(
                store,
                processors=_trusted_processors(
                    lambda context: ProcessorResult("unused", {}),
                    environment="local",
                ),
                clock=lambda: NOW,
            )
            mismatch_id = mismatch_runner.create_run(
                _plan(plan_id="environment-mismatch")
            )
            mismatch = mismatch_runner.run(
                run_id=mismatch_id,
                client_id="synthetic-client",
            )
            self.assertIs(mismatch.state, AutonomyRunState.BLOCKED)
            self.assertEqual("processor_environment_mismatch", mismatch.stages[-1].error)

    def test_runner_detects_caught_capability_denial_and_invalid_result(self) -> None:
        def catches_denial(context):
            try:
                context.capabilities.require("post_journal")
            except ProcessorCapabilityDenied:
                pass
            return ProcessorResult("pretended success", {"synthetic": True})

        for label, callback, error_name in (
            ("caught-denial", catches_denial, "ProcessorCapabilityDenied"),
            ("invalid-result", lambda context: {"not": "a result"}, "TypeError"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                store = SQLiteAutonomyStore(Path(directory) / "runner.sqlite")
                runner = CheckpointedAutonomyRunner(
                    store,
                    processors=_trusted_processors(callback),
                    clock=lambda: NOW,
                )
                run_id = runner.create_run(_plan(plan_id=label))
                report = runner.run(
                    run_id=run_id,
                    client_id="synthetic-client",
                )
                self.assertIs(report.state, AutonomyRunState.INTERRUPTED)
                self.assertIn(error_name, report.stages[-1].error or "")

    def test_runner_persists_blocked_result_and_rejects_lost_lease_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "blocked.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=_trusted_processors(
                    lambda context: ProcessorResult(
                        "locked accounting period",
                        {"period_locked": True},
                        blocked_reason="period_locked",
                    )
                ),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(_plan(plan_id="blocked-result"))
            report = runner.run(run_id=run_id, client_id="synthetic-client")
            self.assertIs(report.state, AutonomyRunState.BLOCKED)
            self.assertIs(report.stages[-1].state, StageState.BLOCKED)

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "lost-lease.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=_trusted_processors(
                    lambda context: ProcessorResult("unused", {})
                ),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(_plan(plan_id="lost-lease"))
            report = runner._run_leased(run_id, store.load_plan(run_id), "not-owner")
            self.assertIs(report.state, AutonomyRunState.CREATED)
            self.assertEqual((), report.stages)

    def test_runner_reports_stale_commit_timeout_and_failed_heartbeat(self) -> None:
        class StaleCommitStore(SQLiteAutonomyStore):
            def commit_checkpoint_if_leased(self, *args, **kwargs):
                return False

        with tempfile.TemporaryDirectory() as directory:
            store = StaleCommitStore(Path(directory) / "stale.sqlite")
            runner = CheckpointedAutonomyRunner(
                store,
                processors=_trusted_processors(
                    lambda context: ProcessorResult("valid but stale", {"ok": True})
                ),
                clock=lambda: NOW,
            )
            run_id = runner.create_run(_plan(plan_id="stale-commit"))
            report = runner.run(run_id=run_id, client_id="synthetic-client")
            self.assertIs(report.state, AutonomyRunState.RUNNING)
            self.assertEqual((), report.stages)

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteAutonomyStore(Path(directory) / "timeout.sqlite")
            runner = CheckpointedAutonomyRunner(store, processors={}, clock=lambda: NOW)
            run_id = runner.create_run(_plan(plan_id="lease-timeout"))
            with (
                patch.object(store, "acquire_execution_lease", return_value=False),
                patch.object(store, "state", return_value=AutonomyRunState.RUNNING),
                patch.object(autonomy_module, "ACTIVE_EXECUTION_WAIT_SECONDS", 0.0),
            ):
                with self.assertRaises(TimeoutError):
                    runner._acquire_or_wait_for_execution(run_id, "contender")

            class NeverStopped:
                def wait(self, timeout: float) -> bool:
                    return False

            with patch.object(
                store,
                "heartbeat_execution_lease",
                return_value=False,
            ) as heartbeat:
                runner._heartbeat_execution(
                    run_id,
                    "expired-owner",
                    NeverStopped(),  # type: ignore[arg-type]
                )
            heartbeat.assert_called_once()


class _SyntheticConnectorAdapter:
    def __init__(
        self,
        *,
        provider_id: str = "fortnox",
        binding: object,
        manifest: object,
    ) -> None:
        self.provider_id = provider_id
        self.binding = binding
        self.manifest = manifest
        self.read_calls = 0

    def check_health(self):
        return ConnectorHealth(
            provider_id=self.provider_id,
            binding=self.binding,
            status=HealthStatus.HEALTHY,
            checked_at=NOW,
            detail_code="synthetic_ok",
        )

    def read_page(self, request):
        self.read_calls += 1
        return ConnectorPage(
            provider_id=self.provider_id,
            binding=request.binding,
            resource=request.resource,
            schema_version=self.manifest.schema_version,
            mapping_version=self.manifest.mapping_version,
            raw_snapshot_hash=raw_snapshot_sha256(b"{}"),
            records=(),
            source_cursor=request.cursor,
            next_cursor=None,
            retry=RetryMetadata(1, 1, False),
        )


def _local_manifest(*, provider_id: str = "synthetic_local") -> ConnectorManifest:
    return ConnectorManifest(
        provider_id=provider_id,
        display_name="Synthetic local fixture",
        lifecycle=ProviderLifecycle.LOCAL_SUPPORTED,
        schema_version="fixture-v1",
        mapping_version="canonical-v1",
        pagination=PaginationContract(PaginationMode.NONE, max_page_size=100),
        capabilities=connector_module._declarations(ProviderLifecycle.LOCAL_SUPPORTED),
    )


class ConnectorSafetyBranchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = ConnectorBinding(
            "synthetic-tenant",
            "synthetic-company",
            ConnectorEnvironment.SANDBOX,
        )

    def test_metadata_and_request_validation_rejects_ambiguous_values(self) -> None:
        with self.assertRaises(ConnectorContractError):
            AuthReference("env-ref:contains space")
        with self.assertRaises(ConnectorContractError):
            ConnectorManifest(
                provider_id="synthetic",
                display_name=" ",
                lifecycle=ProviderLifecycle.DECLARATION_ONLY,
                schema_version="1",
                mapping_version="1",
                pagination=PaginationContract(PaginationMode.NONE),
                capabilities=(),
            )
        with self.assertRaises(ConnectorContractError):
            replace(get_connector_manifest("fortnox"), schema_version=" 1")
        with self.assertRaises(ConnectorContractError):
            ConnectorReadRequest(self.binding, "accounts", page_size=True)
        with self.assertRaises(ConnectorContractError):
            ConnectorReadRequest(self.binding, "accounts", cursor="")
        with self.assertRaises(TypeError):
            raw_snapshot_sha256("not bytes")  # type: ignore[arg-type]

        unsafe_guard = ConnectorGuard(dry_run_only=False)
        with self.assertRaises(ConnectorContractError):
            unsafe_guard.require(ConnectorCapability.READ_TRANSACTIONS)

        undeclared = replace(get_connector_manifest("fortnox"), capabilities=())
        declaration = undeclared.capability(ConnectorCapability.READ_TRANSACTIONS)
        self.assertIs(declaration.mode, CapabilityMode.FORBIDDEN)

    def test_page_cursor_types_are_validated_independently(self) -> None:
        base = dict(
            provider_id="fortnox",
            binding=self.binding,
            resource="accounts",
            schema_version="1",
            mapping_version="bas-v1",
            raw_snapshot_hash=raw_snapshot_sha256(b"{}"),
            records=(),
            retry=RetryMetadata(1, 1, False),
        )
        with self.assertRaises(ConnectorContractError):
            ConnectorPage(**base, source_cursor=1, next_cursor=None)  # type: ignore[arg-type]
        with self.assertRaises(ConnectorContractError):
            ConnectorPage(**base, source_cursor=None, next_cursor=1)  # type: ignore[arg-type]

    def test_guarded_read_rejects_protocol_request_manifest_and_binding_types(self) -> None:
        request = ConnectorReadRequest(self.binding, "accounts")
        with self.assertRaises(ConnectorContractError):
            require_guarded_read_request(object(), request)  # type: ignore[arg-type]

        valid = _SyntheticConnectorAdapter(
            binding=self.binding,
            manifest=get_connector_manifest("fortnox"),
        )
        with self.assertRaises(TypeError):
            require_guarded_read_request(valid, object())  # type: ignore[arg-type]

        bad_manifest = _SyntheticConnectorAdapter(
            binding=self.binding,
            manifest=object(),
        )
        with self.assertRaisesRegex(ConnectorContractError, "manifest"):
            require_guarded_read_request(bad_manifest, request)

        bad_binding = _SyntheticConnectorAdapter(
            binding=object(),
            manifest=get_connector_manifest("fortnox"),
        )
        with self.assertRaisesRegex(ConnectorContractError, "binding"):
            require_guarded_read_request(bad_binding, request)

    def test_non_paginated_local_connector_rejects_cursor_before_read(self) -> None:
        manifest = _local_manifest()
        adapter = _SyntheticConnectorAdapter(
            provider_id=manifest.provider_id,
            binding=self.binding,
            manifest=manifest,
        )
        request = ConnectorReadRequest(
            self.binding,
            "transactions",
            cursor="unexpected-cursor",
        )
        with self.assertRaisesRegex(ConnectorContractError, "non-paginated"):
            read_connector_page_guarded(adapter, request)
        self.assertEqual(0, adapter.read_calls)

    def test_registry_safety_detects_guard_manifest_and_write_tampering(self) -> None:
        safe = _local_manifest(provider_id="synthetic_registry")
        unsafe_guard = replace(safe, guard=ConnectorGuard(dry_run_only=False))
        incomplete = replace(safe, capabilities=safe.capabilities[:-1])
        write_exposed = replace(
            safe,
            capabilities=tuple(
                CapabilityDeclaration(item.capability, CapabilityMode.READ_ONLY, "forged")
                if item.capability is ConnectorCapability.POST_JOURNAL
                else item
                for item in safe.capabilities
            ),
        )
        for label, manifest in (
            ("unsafe_guard", unsafe_guard),
            ("incomplete", incomplete),
            ("write_exposed", write_exposed),
        ):
            with self.subTest(label=label), patch.dict(
                connector_module.CONNECTOR_MANIFESTS,
                {manifest.provider_id: manifest},
                clear=True,
            ):
                with self.assertRaises(ConnectorContractError):
                    assert_v1_preview_registry_safe()

    def test_conformance_reports_protocol_scope_guard_and_capability_tampering(self) -> None:
        protocol_report = evaluate_connector_conformance(object())  # type: ignore[arg-type]
        self.assertEqual(("adapter_protocol_mismatch",), protocol_report.issue_codes)

        base = get_connector_manifest("fortnox")
        unsafe = replace(
            base,
            guard=ConnectorGuard(read_only=False),
            capabilities=tuple(
                CapabilityDeclaration(item.capability, CapabilityMode.READ_ONLY, "forged")
                if item.capability is ConnectorCapability.POST_JOURNAL
                else item
                for item in base.capabilities[:-1]
            ),
        )
        adapter = _SyntheticConnectorAdapter(
            provider_id="different-provider",
            binding=self.binding,
            manifest=unsafe,
        )
        other_binding = ConnectorBinding(
            "other-tenant",
            "other-company",
            ConnectorEnvironment.SANDBOX,
        )
        health = ConnectorHealth(
            provider_id="health-provider",
            binding=other_binding,
            status=HealthStatus.DEGRADED,
            checked_at=NOW,
            detail_code="synthetic_mismatch",
        )
        report = evaluate_connector_conformance(adapter, health=health)
        self.assertTrue(
            {
                "adapter_provider_mismatch",
                "unsafe_guard",
                "capability_manifest_incomplete",
                "write_capability_exposed",
                "health_provider_mismatch",
                "health_binding_mismatch",
            }.issubset(set(report.issue_codes)),
            report.issue_codes,
        )

    def test_conformance_rejects_next_cursor_for_non_paginated_connector(self) -> None:
        manifest = _local_manifest(provider_id="synthetic_cursor")
        adapter = _SyntheticConnectorAdapter(
            provider_id=manifest.provider_id,
            binding=self.binding,
            manifest=manifest,
        )
        page = ConnectorPage(
            provider_id=manifest.provider_id,
            binding=self.binding,
            resource="accounts",
            schema_version=manifest.schema_version,
            mapping_version=manifest.mapping_version,
            raw_snapshot_hash=raw_snapshot_sha256(b"{}"),
            records=(),
            source_cursor=None,
            next_cursor="cursor-that-must-not-exist",
            retry=RetryMetadata(1, 1, False),
        )
        report = evaluate_connector_conformance(adapter, sample_page=page)
        self.assertIn("unexpected_next_cursor", report.issue_codes)


LOW_RISK = {
    "entity_id": "synthetic-entity",
    "currency": "SEK",
    "amount_minor": 125_00,
    "supplier_known": True,
    "customer_known": True,
    "bank_details_changed": False,
    "duplicate_risk": 0.0,
    "vat_confidence": 1.0,
    "ocr_confidence": 1.0,
    "period_locked": False,
    "new_supplier": False,
    "destructive_action": False,
    "external_communication": False,
    "tax_filing_payment": False,
}


def _draft_payload(**changes: object) -> dict[str, object]:
    return {
        "client_id": "synthetic-client",
        "supplier_id": "synthetic-supplier",
        **LOW_RISK,
        **changes,
    }


def _mcp() -> RestrictedFortnoxMCP:
    return RestrictedFortnoxMCP(
        audit_log=ToolCallAuditLog(),
        fortnox_adapter=FortnoxWriteAdapter(PermitValidator(clock=lambda: NOW)),
    )


def _permit(payload: dict[str, object], *, permit_id: str = "safety-permit"):
    context = PolicyContext(
        action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
        client_id=str(payload["client_id"]),
        currency_code=str(payload["currency"]),
        amount_minor=int(payload["amount_minor"]),
        supplier_known=bool(payload["supplier_known"]),
        customer_known=bool(payload["customer_known"]),
        bank_details_changed=bool(payload["bank_details_changed"]),
        duplicate_risk=float(payload["duplicate_risk"]),
        vat_confidence=float(payload["vat_confidence"]),
        ocr_confidence=float(payload["ocr_confidence"]),
        period_locked=bool(payload["period_locked"]),
        new_supplier=bool(payload["new_supplier"]),
        destructive_action=bool(payload["destructive_action"]),
        external_communication=bool(payload["external_communication"]),
        tax_filing_payment=bool(payload["tax_filing_payment"]),
        risk_evidence_complete=True,
    )
    return issue_test_permit(
        context=context,
        case_id="synthetic-case",
        payload=payload,
        now=NOW,
        permit_id=permit_id,
        entity_id=str(payload["entity_id"]),
    )


class RestrictedMCPSafetyBranchTests(unittest.TestCase):
    def test_hidden_non_forbidden_tool_and_unimplemented_read_are_denied_and_logged(self) -> None:
        mcp = _mcp()
        with self.assertRaises(RestrictedToolForbidden):
            mcp.call_tool(
                "fortnox_update_supplier",
                {"client_id": "synthetic-client"},
                case_id="synthetic-case",
            )
        self.assertEqual("denied", mcp.audit_log.entries[-1].status)

        custom = RestrictedToolMetadata(
            tool_name="fortnox_custom_read",
            external_system="fortnox",
            action_type=ActionType.READ_ANALYSIS,
            permission_mode=MCPPermissionMode.READ_SAFE,
            required_permit=None,
            forbidden_conditions=(),
        )
        custom_mcp = RestrictedFortnoxMCP(
            registry={custom.tool_name: custom},
            audit_log=ToolCallAuditLog(),
        )
        with self.assertRaises(UnknownRestrictedTool):
            custom_mcp.call_tool(
                custom.tool_name,
                {"client_id": "synthetic-client"},
            )
        self.assertEqual("denied", custom_mcp.audit_log.entries[-1].status)

    def test_list_accounts_read_succeeds_and_missing_client_is_denied(self) -> None:
        mcp = _mcp()
        result = mcp.call_tool(
            "fortnox_list_accounts",
            {"client_id": "synthetic-client"},
        )
        self.assertEqual(3, len(result["accounts"]))
        self.assertEqual("allowed", mcp.audit_log.entries[-1].status)

        with self.assertRaises(ValueError):
            mcp.call_tool("fortnox_list_accounts", {})
        denied = mcp.audit_log.entries[-1]
        self.assertEqual("denied", denied.status)
        self.assertIsNone(denied.client_id)

    def test_write_preflight_rejects_case_entity_and_forbidden_policy(self) -> None:
        cases = (
            ("missing-case", _draft_payload(), None, RestrictedToolPermitError),
            (
                "missing-entity",
                _draft_payload(entity_id=""),
                "synthetic-case",
                RestrictedToolPermitError,
            ),
            (
                "locked-period",
                _draft_payload(period_locked=True),
                "synthetic-case",
                RestrictedToolForbidden,
            ),
        )
        for label, payload, case_id, error_type in cases:
            with self.subTest(label=label):
                mcp = _mcp()
                with self.assertRaises(error_type):
                    mcp.call_tool(
                        "fortnox_prepare_supplier_invoice_draft",
                        payload,
                        case_id=case_id,
                    )
                self.assertEqual("denied", mcp.audit_log.entries[-1].status)

    def test_mutated_permit_scope_policy_and_reviews_fail_before_adapter(self) -> None:
        payload = _draft_payload()
        permit, decision, _, _ = _permit(payload)
        self.assertIs(decision.permission_mode, PermissionMode.DRAFT_ONLY)
        mutations = (
            ("client_id", replace(permit, client_id="different-client")),
            (
                "permission mode",
                replace(permit, permission_mode=PermissionMode.APPROVAL_REQUIRED),
            ),
            (
                "required reviews",
                replace(permit, required_reviews=("accountant_review",)),
            ),
        )
        for label, mutated in mutations:
            with self.subTest(label=label):
                mcp = _mcp()
                with self.assertRaisesRegex(RestrictedToolPermitError, label):
                    mcp.call_tool(
                        "fortnox_prepare_supplier_invoice_draft",
                        payload,
                        case_id="synthetic-case",
                        permit=mutated,
                    )
                self.assertEqual("denied", mcp.audit_log.entries[-1].status)

    def test_primitive_risk_evidence_types_fail_closed_and_are_audited(self) -> None:
        invalid = (
            ("client_id", ""),
            ("supplier_known", "yes"),
            ("amount_minor", True),
            ("duplicate_risk", True),
        )
        for field, value in invalid:
            with self.subTest(field=field):
                mcp = _mcp()
                with self.assertRaises(ValueError):
                    mcp.call_tool(
                        "fortnox_prepare_supplier_invoice_draft",
                        _draft_payload(**{field: value}),
                        case_id="synthetic-case",
                    )
                self.assertEqual("denied", mcp.audit_log.entries[-1].status)

    def test_valid_permit_replay_remains_dry_run_and_idempotency_bound(self) -> None:
        payload = _draft_payload()
        permit, _, permit_store, approval_authority = _permit(
            payload,
            permit_id="replay-permit",
        )
        mcp = _mcp()
        mcp.fortnox_adapter.permit_validator = PermitValidator(
            clock=lambda: NOW,
            permit_store=permit_store,
            approval_authority=approval_authority,
        )
        first = mcp.call_tool(
            "fortnox_prepare_supplier_invoice_draft",
            payload,
            case_id="synthetic-case",
            permit=permit,
        )
        second = mcp.call_tool(
            "fortnox_prepare_supplier_invoice_draft",
            payload,
            case_id="synthetic-case",
            permit=permit,
        )
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertEqual(
            "supplier_invoice_draft_prepared_no_live_write",
            second["status"],
        )
        self.assertEqual(["allowed", "allowed"], [entry.status for entry in mcp.audit_log.entries])


if __name__ == "__main__":
    unittest.main()
