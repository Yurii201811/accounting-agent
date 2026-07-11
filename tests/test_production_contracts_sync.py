from __future__ import annotations

import json
import socket
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from accounting_agent.connector_contract import (
    AuthReference,
    ConnectorCapability,
    ConnectorEnvironment,
)
from accounting_agent.contracts.sync import (
    ConnectorConnection,
    ConnectorConnectionStatus,
    ReconciliationStatus,
    SourceReconciliation,
    SyncCheckpoint,
    SyncRun,
    SyncRunStatus,
)
from accounting_agent.contracts._wire import canonical_json_sha256


def _hash(character: str) -> str:
    return character * 64


def _connection(**overrides: object) -> ConnectorConnection:
    values: dict[str, object] = {
        "connection_id": "connection-001",
        "revision": 1,
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "provider_id": "fortnox",
        "source_company_id": "fortnox-company-001",
        "environment": ConnectorEnvironment.SANDBOX,
        "auth_reference": AuthReference("oauth-ref:fortnox-001"),
        "capabilities": (
            ConnectorCapability.READ_MASTER_DATA,
            ConnectorCapability.READ_TRANSACTIONS,
        ),
        "status": ConnectorConnectionStatus.ACTIVE,
        "recorded_at": datetime(2026, 7, 1, 8, tzinfo=UTC),
    }
    values.update(overrides)
    return ConnectorConnection(**values)  # type: ignore[arg-type]


def _checkpoint(
    *,
    sequence: int = 1,
    resource: str = "suppliers",
    count: int = 2,
    digest: str | None = None,
    source_cursor: str | None = None,
    next_cursor: str | None = None,
    captured_at: datetime | None = None,
    **overrides: object,
) -> SyncCheckpoint:
    values: dict[str, object] = {
        "checkpoint_id": f"checkpoint-{sequence:03d}",
        "sync_run_id": "sync-run-001",
        "connection_id": "connection-001",
        "connection_revision": 1,
        "connection_sha256": _connection().canonical_sha256(),
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "provider_id": "fortnox",
        "source_company_id": "fortnox-company-001",
        "environment": ConnectorEnvironment.SANDBOX,
        "resource": resource,
        "sequence": sequence,
        "source_cursor": source_cursor,
        "next_cursor": next_cursor,
        "record_count": count,
        "raw_snapshot_sha256": _hash("a" if sequence % 2 else "b"),
        "canonical_record_set_sha256": digest or _hash(str(sequence)),
        "captured_at": captured_at or datetime(2026, 7, 1, 8, sequence, tzinfo=UTC),
    }
    values.update(overrides)
    return SyncCheckpoint(**values)  # type: ignore[arg-type]


def _reconciliation(
    *,
    resource: str = "suppliers",
    count: int = 2,
    digest: str = _hash("1"),
    status: ReconciliationStatus = ReconciliationStatus.VERIFIED,
    **overrides: object,
) -> SourceReconciliation:
    values: dict[str, object] = {
        "reconciliation_id": f"reconciliation-{resource}",
        "sync_run_id": "sync-run-001",
        "connection_id": "connection-001",
        "connection_revision": 1,
        "connection_sha256": _connection().canonical_sha256(),
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "provider_id": "fortnox",
        "source_company_id": "fortnox-company-001",
        "environment": ConnectorEnvironment.SANDBOX,
        "resource": resource,
        "source_count": count,
        "observed_count": count,
        "source_sha256": digest,
        "observed_sha256": digest,
        "checkpoint_chain_sha256": SyncCheckpoint.chain_sha256((_checkpoint(),)),
        "status": status,
        "recorded_at": datetime(2026, 7, 1, 8, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return SourceReconciliation(**values)  # type: ignore[arg-type]


def _run(**overrides: object) -> SyncRun:
    values: dict[str, object] = {
        "sync_run_id": "sync-run-001",
        "revision": 1,
        "connection_id": "connection-001",
        "connection_revision": 1,
        "connection_sha256": _connection().canonical_sha256(),
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "provider_id": "fortnox",
        "source_company_id": "fortnox-company-001",
        "environment": ConnectorEnvironment.SANDBOX,
        "requested_resources": ("suppliers",),
        "status": SyncRunStatus.PLANNED,
        "checkpoints": (),
        "reconciliations": (),
        "created_at": datetime(2026, 7, 1, 8, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 1, 8, tzinfo=UTC),
    }
    values.update(overrides)
    return SyncRun(**values)  # type: ignore[arg-type]


class ConnectorConnectionContractTests(unittest.TestCase):
    def test_connection_is_frozen_and_binds_the_legacy_connector_scope(self) -> None:
        connection = _connection()
        self.assertEqual("tenant-001", connection.binding.tenant_id)
        self.assertEqual("fortnox-company-001", connection.binding.company_id)
        self.assertEqual(ConnectorEnvironment.SANDBOX, connection.binding.environment)
        self.assertEqual(connection.auth_reference, connection.binding.auth_reference)
        self.assertEqual(
            (
                ConnectorCapability.READ_MASTER_DATA,
                ConnectorCapability.READ_TRANSACTIONS,
            ),
            connection.capabilities,
        )
        with self.assertRaises(FrozenInstanceError):
            connection.provider_id = "netsuite"  # type: ignore[misc]

    def test_connection_rejects_write_authority_and_ambiguous_scope(self) -> None:
        for capability in (
            ConnectorCapability.CREATE_EXTERNAL_DRAFT,
            ConnectorCapability.POST_JOURNAL,
            ConnectorCapability.APPROVE_TRANSACTION,
            ConnectorCapability.SEND_DOCUMENT,
            ConnectorCapability.START_PAYMENT,
            ConnectorCapability.FILE_TAX,
            ConnectorCapability.DELETE_RECORD,
            ConnectorCapability.CHANGE_SETTINGS,
        ):
            with self.subTest(capability=capability):
                with self.assertRaisesRegex(ValueError, "write capability"):
                    _connection(capabilities=(capability,))

        for field_name, bad_value in (
            ("tenant_id", "unknown"),
            ("client_id", ".."),
            ("legal_entity_id", " entity-001"),
            ("provider_id", "fortnox\nother"),
            ("source_company_id", "company/other"),
            ("environment", "maybe-production"),
        ):
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    _connection(**{field_name: bad_value})

        with self.assertRaisesRegex(ValueError, "auth_reference"):
            _connection(auth_reference="oauth-ref:fortnox-001")
        with self.assertRaisesRegex(ValueError, "capabilities must be a tuple"):
            _connection(capabilities=[ConnectorCapability.READ_MASTER_DATA])
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            _connection(capabilities=())
        with self.assertRaisesRegex(ValueError, "duplicates"):
            _connection(
                capabilities=(
                    ConnectorCapability.READ_MASTER_DATA,
                    ConnectorCapability.READ_MASTER_DATA,
                )
            )

    def test_connection_successor_keeps_authority_scope_immutable(self) -> None:
        previous = _connection()
        rotated = replace(
            previous,
            revision=2,
            auth_reference=AuthReference("oauth-ref:fortnox-rotated"),
            recorded_at=previous.recorded_at + timedelta(minutes=1),
        )
        rotated.assert_successor_of(previous)

        for field_name, bad_value in (
            ("connection_id", "connection-evil"),
            ("tenant_id", "tenant-evil"),
            ("client_id", "client-evil"),
            ("legal_entity_id", "entity-evil"),
            ("provider_id", "netsuite"),
            ("source_company_id", "company-evil"),
            ("environment", ConnectorEnvironment.PRODUCTION),
            ("capabilities", (ConnectorCapability.READ_PERIOD_LOCKS,)),
        ):
            with self.subTest(field=field_name):
                candidate = replace(
                    previous,
                    revision=2,
                    recorded_at=previous.recorded_at + timedelta(minutes=1),
                    **{field_name: bad_value},
                )
                with self.assertRaisesRegex(ValueError, "immutable"):
                    candidate.assert_successor_of(previous)

        with self.assertRaisesRegex(ValueError, "exactly one"):
            replace(previous, revision=3).assert_successor_of(previous)
        with self.assertRaisesRegex(ValueError, "cannot move backwards"):
            replace(
                previous, revision=2, recorded_at=previous.recorded_at - timedelta(1)
            ).assert_successor_of(previous)

    def test_revoked_connection_cannot_reactivate(self) -> None:
        active = _connection()
        revoked = replace(
            active,
            revision=2,
            status=ConnectorConnectionStatus.REVOKED,
            recorded_at=active.recorded_at + timedelta(minutes=1),
        )
        revoked.assert_successor_of(active)
        reactivated = replace(
            revoked,
            revision=3,
            status=ConnectorConnectionStatus.ACTIVE,
            recorded_at=revoked.recorded_at + timedelta(minutes=1),
        )
        with self.assertRaisesRegex(ValueError, "revoked"):
            reactivated.assert_successor_of(revoked)

        with self.assertRaisesRegex(ValueError, "transition"):
            replace(
                active,
                revision=2,
                status=ConnectorConnectionStatus.PENDING,
                recorded_at=active.recorded_at + timedelta(minutes=1),
            ).assert_successor_of(active)

    def test_connection_wire_round_trip_is_strict_and_duplicate_safe(self) -> None:
        connection = _connection()
        payload = connection.to_dict()
        self.assertEqual("v1", payload["schema_version"])
        self.assertEqual(connection, ConnectorConnection.from_dict(payload))
        self.assertRegex(connection.canonical_sha256(), r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            connection.canonical_sha256(),
            replace(
                connection,
                status=ConnectorConnectionStatus.SUSPENDED,
            ).canonical_sha256(),
        )

        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            ConnectorConnection.from_dict({**payload, "schema_version": "v2"})
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            ConnectorConnection.from_dict({**payload, "access_token": "secret"})
        duplicate = json.dumps(payload).replace(
            '"tenant_id": "tenant-001",',
            '"tenant_id": "tenant-001", "tenant_id": "tenant-evil",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            ConnectorConnection.from_json(duplicate)


class SyncCheckpointContractTests(unittest.TestCase):
    def test_checkpoint_round_trips_and_matches_exact_connection_scope(self) -> None:
        checkpoint = _checkpoint()
        self.assertEqual(checkpoint, SyncCheckpoint.from_dict(checkpoint.to_dict()))
        checkpoint.assert_matches_connection(_connection())

        for field_name, bad_value in (
            ("sequence", 0),
            ("connection_revision", 0),
            ("record_count", -1),
            ("raw_snapshot_sha256", "A" * 64),
            ("canonical_record_set_sha256", "A" * 64),
            ("source_cursor", " cursor"),
            ("next_cursor", "cursor\nother"),
            ("captured_at", datetime(2026, 7, 1, 8)),
        ):
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    _checkpoint(**{field_name: bad_value})

        with self.assertRaisesRegex(ValueError, "connection scope"):
            checkpoint.assert_matches_connection(_connection(client_id="client-evil"))

    def test_checkpoint_wire_is_strict_and_duplicate_safe(self) -> None:
        payload = _checkpoint().to_dict()
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            SyncCheckpoint.from_dict({**payload, "schema_version": "v7"})
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            SyncCheckpoint.from_dict({**payload, "raw_records": []})
        duplicate = json.dumps(payload).replace(
            '"resource": "suppliers",',
            '"resource": "suppliers", "resource": "payments",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            SyncCheckpoint.from_json(duplicate)

    def test_checkpoint_hash_binds_cursors_and_raw_and_canonical_hashes(self) -> None:
        checkpoint = _checkpoint(next_cursor="cursor-001")
        digest = checkpoint.canonical_sha256()
        self.assertEqual(
            canonical_json_sha256(checkpoint.to_dict(), "SyncCheckpoint"),
            digest,
        )
        for field_name, bad_value in (
            ("source_cursor", "cursor-source"),
            ("next_cursor", "cursor-002"),
            ("raw_snapshot_sha256", _hash("c")),
            ("canonical_record_set_sha256", _hash("d")),
        ):
            with self.subTest(field=field_name):
                self.assertNotEqual(
                    digest,
                    replace(checkpoint, **{field_name: bad_value}).canonical_sha256(),
                )

    def test_checkpoint_chain_hash_binds_order_and_rejects_mixed_resources(self) -> None:
        first = _checkpoint(next_cursor="cursor-001")
        second = _checkpoint(
            sequence=2,
            count=4,
            digest=_hash("2"),
            source_cursor="cursor-001",
        )
        digest = SyncCheckpoint.chain_sha256((first, second))
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(ValueError, "ordered"):
            SyncCheckpoint.chain_sha256((second, first))
        with self.assertRaisesRegex(ValueError, "cursor"):
            SyncCheckpoint.chain_sha256(
                (first, replace(second, source_cursor="cursor-forged"))
            )
        with self.assertRaisesRegex(ValueError, "one resource"):
            SyncCheckpoint.chain_sha256((first, replace(second, resource="accounts")))


class SourceReconciliationContractTests(unittest.TestCase):
    def test_verified_reconciliation_requires_exact_count_and_hash_equality(self) -> None:
        verified = _reconciliation()
        self.assertTrue(verified.is_verified)
        self.assertEqual(verified, SourceReconciliation.from_dict(verified.to_dict()))
        self.assertRegex(verified.canonical_sha256(), r"^[0-9a-f]{64}$")
        verified.assert_matches_checkpoint(_checkpoint())

        for field_name, bad_value in (
            ("observed_count", 3),
            ("observed_sha256", _hash("2")),
            ("source_count", None),
            ("source_sha256", None),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, "verified"):
                    _reconciliation(**{field_name: bad_value})

    def test_mismatch_and_unsupported_states_cannot_claim_verification(self) -> None:
        mismatch = _reconciliation(
            status=ReconciliationStatus.MISMATCH,
            observed_count=3,
        )
        self.assertFalse(mismatch.is_verified)
        with self.assertRaisesRegex(ValueError, "must differ"):
            _reconciliation(status=ReconciliationStatus.MISMATCH)

        unsupported = _reconciliation(
            status=ReconciliationStatus.UNSUPPORTED,
            source_count=None,
            source_sha256=None,
        )
        self.assertFalse(unsupported.is_verified)
        self.assertEqual(
            unsupported,
            SourceReconciliation.from_dict(unsupported.to_dict()),
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            _reconciliation(
                status=ReconciliationStatus.UNSUPPORTED,
                source_count=2,
            )

    def test_reconciliation_wire_is_strict_and_duplicate_safe(self) -> None:
        payload = _reconciliation().to_dict()
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            SourceReconciliation.from_dict({**payload, "schema_version": "v2"})
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            SourceReconciliation.from_dict({**payload, "trusted": True})
        duplicate = json.dumps(payload).replace(
            '"status": "verified",',
            '"status": "verified", "status": "unsupported",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            SourceReconciliation.from_json(duplicate)

    def test_reconciliation_requires_a_strict_checkpoint_chain_hash(self) -> None:
        with self.assertRaisesRegex(ValueError, "checkpoint_chain_sha256"):
            _reconciliation(checkpoint_chain_sha256="A" * 64)


class SyncRunContractTests(unittest.TestCase):
    def test_completed_run_requires_contiguous_checkpoints_and_reconciliation(self) -> None:
        checkpoint = _checkpoint()
        reconciliation = _reconciliation()
        completed = _run(
            status=SyncRunStatus.COMPLETED,
            checkpoints=(checkpoint,),
            reconciliations=(reconciliation,),
            updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
        )
        self.assertEqual(completed, SyncRun.from_dict(completed.to_dict()))
        completed.assert_matches_connection(_connection())
        checkpoint.assert_matches_run(completed)
        reconciliation.assert_matches_run(completed)

        same_revision_different_connection = _connection(
            auth_reference=AuthReference("oauth-ref:fortnox-rotated")
        )
        for record in (completed, checkpoint, reconciliation):
            with self.subTest(record=type(record).__name__):
                with self.assertRaisesRegex(ValueError, "connection"):
                    record.assert_matches_connection(same_revision_different_connection)

        for field_name, bad_value, message in (
            ("checkpoints", (), "checkpoint"),
            ("reconciliations", (), "reconciliation"),
            (
                "reconciliations",
                (
                    _reconciliation(
                        status=ReconciliationStatus.UNSUPPORTED,
                        source_count=None,
                        source_sha256=None,
                    ),
                ),
                "verified",
            ),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, message):
                    values = {
                        "status": SyncRunStatus.COMPLETED,
                        "checkpoints": (checkpoint,),
                        "reconciliations": (reconciliation,),
                        "updated_at": datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
                    }
                    values[field_name] = bad_value
                    _run(**values)

    def test_run_rejects_gaps_backward_time_and_decreasing_resource_counts(self) -> None:
        first = _checkpoint(count=3, next_cursor="cursor-001")
        second = _checkpoint(
            sequence=2,
            count=4,
            digest=_hash("2"),
            source_cursor="cursor-001",
            next_cursor=None,
        )
        _run(
            status=SyncRunStatus.RUNNING,
            checkpoints=(first, second),
            updated_at=datetime(2026, 7, 1, 8, 3, tzinfo=UTC),
        )

        with self.assertRaisesRegex(ValueError, "contiguous"):
            _run(
                status=SyncRunStatus.RUNNING,
                checkpoints=(first, replace(second, sequence=3)),
                updated_at=datetime(2026, 7, 1, 8, 3, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "timestamps"):
            _run(
                status=SyncRunStatus.RUNNING,
                checkpoints=(
                    first,
                    replace(second, captured_at=first.captured_at - timedelta(seconds=1)),
                ),
                updated_at=datetime(2026, 7, 1, 8, 3, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "cannot decrease"):
            _run(
                status=SyncRunStatus.RUNNING,
                checkpoints=(first, replace(second, record_count=2)),
                updated_at=datetime(2026, 7, 1, 8, 3, tzinfo=UTC),
            )

    def test_run_rejects_broken_cursor_continuity_and_unfinished_completion(self) -> None:
        first = _checkpoint(next_cursor="cursor-001")
        disconnected = _checkpoint(
            sequence=2,
            count=3,
            digest=_hash("2"),
            source_cursor="cursor-evil",
        )
        with self.assertRaisesRegex(ValueError, "cursor chain"):
            _run(
                status=SyncRunStatus.RUNNING,
                checkpoints=(first, disconnected),
                updated_at=datetime(2026, 7, 1, 8, 3, tzinfo=UTC),
            )

        with self.assertRaisesRegex(ValueError, "next cursor"):
            _run(
                status=SyncRunStatus.COMPLETED,
                checkpoints=(first,),
                reconciliations=(
                    _reconciliation(checkpoint_chain_sha256=SyncCheckpoint.chain_sha256((first,))),
                ),
                updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
            )

    def test_run_rejects_unbound_or_predated_evidence_in_every_state(self) -> None:
        reconciliation = _reconciliation()
        with self.assertRaisesRegex(ValueError, "checkpoint evidence"):
            _run(
                status=SyncRunStatus.RUNNING,
                reconciliations=(reconciliation,),
                updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "created_at"):
            _run(
                status=SyncRunStatus.RUNNING,
                checkpoints=(_checkpoint(captured_at=datetime(2026, 7, 1, 7, 59, tzinfo=UTC)),),
                updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "checkpoint chain"):
            checkpoint = _checkpoint()
            _run(
                status=SyncRunStatus.RUNNING,
                checkpoints=(checkpoint,),
                reconciliations=(_reconciliation(checkpoint_chain_sha256=_hash("e")),),
                updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
            )

    def test_completion_rejects_a_forged_checkpoint_chain_digest(self) -> None:
        checkpoint = _checkpoint()
        with self.assertRaisesRegex(ValueError, "checkpoint chain"):
            _run(
                status=SyncRunStatus.COMPLETED,
                checkpoints=(checkpoint,),
                reconciliations=(_reconciliation(checkpoint_chain_sha256=_hash("f")),),
                updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
            )

    def test_run_requires_exact_requested_resource_coverage(self) -> None:
        supplier_checkpoint = _checkpoint()
        account_checkpoint = _checkpoint(
            sequence=2,
            resource="accounts",
            count=1,
            digest=_hash("2"),
            next_cursor=None,
        )
        supplier_reconciliation = _reconciliation()
        account_reconciliation = _reconciliation(
            resource="accounts",
            count=1,
            digest=_hash("2"),
            checkpoint_chain_sha256=SyncCheckpoint.chain_sha256((account_checkpoint,)),
        )
        _run(
            requested_resources=("suppliers", "accounts"),
            status=SyncRunStatus.COMPLETED,
            checkpoints=(supplier_checkpoint, account_checkpoint),
            reconciliations=(supplier_reconciliation, account_reconciliation),
            updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
        )

        with self.assertRaisesRegex(ValueError, "sync run scope"):
            _run(
                status=SyncRunStatus.RUNNING,
                checkpoints=(replace(supplier_checkpoint, resource="payments"),),
                updated_at=datetime(2026, 7, 1, 8, 2, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            _run(
                requested_resources=("suppliers", "accounts"),
                status=SyncRunStatus.COMPLETED,
                checkpoints=(supplier_checkpoint, account_checkpoint),
                reconciliations=(supplier_reconciliation,),
                updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "latest checkpoint"):
            _run(
                status=SyncRunStatus.COMPLETED,
                checkpoints=(supplier_checkpoint,),
                reconciliations=(_reconciliation(observed_count=9, source_count=9),),
                updated_at=datetime(2026, 7, 1, 8, 11, tzinfo=UTC),
            )

    def test_run_lifecycle_is_strict_append_only_and_terminal(self) -> None:
        planned = _run()
        running = replace(
            planned,
            revision=2,
            status=SyncRunStatus.RUNNING,
            updated_at=planned.updated_at + timedelta(minutes=1),
        )
        running.assert_successor_of(planned)
        progressed = replace(
            running,
            revision=3,
            checkpoints=(_checkpoint(),),
            updated_at=running.updated_at + timedelta(minutes=2),
        )
        progressed.assert_successor_of(running)
        completed = replace(
            progressed,
            revision=4,
            status=SyncRunStatus.COMPLETED,
            reconciliations=(_reconciliation(),),
            updated_at=progressed.updated_at + timedelta(minutes=8),
        )
        completed.assert_successor_of(progressed)

        with self.assertRaisesRegex(ValueError, "terminal"):
            replace(
                completed,
                revision=5,
                updated_at=completed.updated_at + timedelta(1),
            ).assert_successor_of(completed)
        with self.assertRaisesRegex(ValueError, "transition"):
            replace(
                planned,
                revision=2,
                status=SyncRunStatus.COMPLETED,
                checkpoints=(_checkpoint(),),
                reconciliations=(_reconciliation(),),
                updated_at=planned.updated_at + timedelta(minutes=11),
            ).assert_successor_of(planned)
        with self.assertRaisesRegex(ValueError, "append-only"):
            replace(
                progressed,
                revision=4,
                checkpoints=(),
                updated_at=progressed.updated_at + timedelta(1),
            ).assert_successor_of(progressed)

    def test_planned_run_cannot_contain_observed_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "planned"):
            _run(checkpoints=(_checkpoint(),))
        with self.assertRaisesRegex(ValueError, "planned"):
            _run(reconciliations=(_reconciliation(),))

    def test_run_wire_is_strict_duplicate_safe_and_side_effect_free(self) -> None:
        run = _run()
        payload = run.to_dict()
        self.assertRegex(run.canonical_sha256(), r"^[0-9a-f]{64}$")
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            SyncRun.from_dict({**payload, "schema_version": "v2"})
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            SyncRun.from_dict({**payload, "provider_response": {}})
        duplicate = json.dumps(payload).replace(
            '"sync_run_id": "sync-run-001",',
            '"sync_run_id": "sync-run-001", "sync_run_id": "evil",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            SyncRun.from_json(duplicate)

        with patch.object(socket, "socket", side_effect=AssertionError("network call")):
            self.assertEqual(run, SyncRun.from_dict(payload))
            self.assertEqual(_connection(), ConnectorConnection.from_dict(_connection().to_dict()))


if __name__ == "__main__":
    unittest.main()
