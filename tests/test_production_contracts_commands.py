from __future__ import annotations

import json
import socket
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from accounting_agent.connector_contract import ConnectorEnvironment
from accounting_agent.contracts.commands import (
    ApprovalDecisionCommand,
    ApprovalDecisionOutcome,
    DraftComparisonStatus,
    DraftReadbackStatus,
    ExternalDraftCommand,
    ExternalDraftObservedState,
    ExternalDraftReceipt,
    ExternalDraftRecordType,
)
from accounting_agent.contracts.scope import (
    AuthenticationStrength,
    MembershipRole,
    TenantContext,
)


def _hash(character: str) -> str:
    return character * 64


def _context(**overrides: object) -> TenantContext:
    values: dict[str, object] = {
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "actor_id": "reviewer-001",
        "roles": (MembershipRole.REVIEWER,),
        "authentication_strength": AuthenticationStrength.MULTI_FACTOR,
        "request_id": "http-request-001",
    }
    values.update(overrides)
    return TenantContext(**values)  # type: ignore[arg-type]


def _approval(**overrides: object) -> ApprovalDecisionCommand:
    values: dict[str, object] = {
        "context": _context(),
        "approval_request_id": "approval-request-001",
        "approval_request_sha256": _hash("a"),
        "requestor_actor_id": "preparer-001",
        "acting_role": MembershipRole.REVIEWER,
        "outcome": ApprovalDecisionOutcome.APPROVE,
        "reason": "Evidence, policy, and supplier details independently reviewed.",
        "expected_version": 1,
        "idempotency_key": _hash("b"),
        "decided_at": datetime(2026, 7, 2, 8, tzinfo=UTC),
    }
    values.update(overrides)
    return ApprovalDecisionCommand(**values)  # type: ignore[arg-type]


def _draft(**overrides: object) -> ExternalDraftCommand:
    values: dict[str, object] = {
        "draft_command_id": "draft-command-001",
        "tenant_id": "tenant-001",
        "client_id": "client-001",
        "legal_entity_id": "entity-se-001",
        "case_id": "case-001",
        "connection_id": "connection-001",
        "connection_revision": 3,
        "connection_sha256": _hash("c"),
        "provider_id": "fortnox",
        "environment": ConnectorEnvironment.SANDBOX,
        "record_type": ExternalDraftRecordType.SUPPLIER_INVOICE,
        "payload_sha256": _hash("d"),
        "evidence_hashes": (_hash("e"), _hash("f")),
        "policy_decision_sha256": _hash("1"),
        "approval_receipt_sha256": _hash("2"),
        "approval_decision_sha256": _hash("7"),
        "permit_id": "permit-001",
        "permit_sha256": _hash("3"),
        "idempotency_key": _hash("4"),
        "created_at": datetime(2026, 7, 2, 8, tzinfo=UTC),
        "expires_at": datetime(2026, 7, 2, 8, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return ExternalDraftCommand(**values)  # type: ignore[arg-type]


def _receipt(**overrides: object) -> ExternalDraftReceipt:
    command = _draft()
    values: dict[str, object] = {
        "receipt_id": "draft-receipt-001",
        "draft_command_id": command.draft_command_id,
        "draft_command_sha256": command.canonical_sha256(),
        "tenant_id": command.tenant_id,
        "client_id": command.client_id,
        "legal_entity_id": command.legal_entity_id,
        "case_id": command.case_id,
        "connection_id": command.connection_id,
        "connection_revision": command.connection_revision,
        "connection_sha256": command.connection_sha256,
        "provider_id": command.provider_id,
        "environment": command.environment,
        "payload_sha256": command.payload_sha256,
        "idempotency_key": command.idempotency_key,
        "provider_reference": "supplier-invoice-draft-001",
        "provider_response_sha256": _hash("5"),
        "readback_sha256": command.payload_sha256,
        "readback_status": DraftReadbackStatus.COMPLETED,
        "observed_state": ExternalDraftObservedState.UNBOOKED_REVERSIBLE,
        "comparison_status": DraftComparisonStatus.EXACT_MATCH,
        "attempted_at": datetime(2026, 7, 2, 8, 1, tzinfo=UTC),
        "readback_at": datetime(2026, 7, 2, 8, 2, tzinfo=UTC),
        "recorded_at": datetime(2026, 7, 2, 8, 3, tzinfo=UTC),
    }
    values.update(overrides)
    return ExternalDraftReceipt(**values)  # type: ignore[arg-type]


class ApprovalDecisionCommandTests(unittest.TestCase):
    def test_approval_is_frozen_exact_and_strictly_round_trips(self) -> None:
        command = _approval()
        self.assertEqual("reviewer-001", command.context.actor_id)
        self.assertEqual(MembershipRole.REVIEWER, command.acting_role)
        self.assertEqual(command, ApprovalDecisionCommand.from_dict(command.to_dict()))
        self.assertEqual(64, len(command.canonical_sha256()))
        with self.assertRaises(FrozenInstanceError):
            command.outcome = ApprovalDecisionOutcome.REJECT  # type: ignore[misc]

    def test_only_an_authenticated_reviewer_or_controller_can_act(self) -> None:
        controller = _approval(
            context=_context(
                actor_id="controller-001",
                roles=(MembershipRole.CONTROLLER,),
            ),
            acting_role=MembershipRole.CONTROLLER,
        )
        self.assertEqual(MembershipRole.CONTROLLER, controller.acting_role)

        for role in (
            MembershipRole.TENANT_ADMIN,
            MembershipRole.PREPARER,
            MembershipRole.AUDITOR,
            MembershipRole.CONNECTOR_ADMIN,
            MembershipRole.ARCHIVE_ADMIN,
            MembershipRole.SECURITY_ADMIN,
        ):
            with self.subTest(role=role):
                with self.assertRaisesRegex(ValueError, "reviewer or controller"):
                    _approval(
                        context=_context(roles=(role,)),
                        acting_role=role,
                    )

        with self.assertRaisesRegex(ValueError, "present in authenticated roles"):
            _approval(
                context=_context(roles=(MembershipRole.REVIEWER,)),
                acting_role=MembershipRole.CONTROLLER,
            )

        with self.assertRaisesRegex(ValueError, "service"):
            _approval(
                context=_context(
                    actor_id="worker-001",
                    roles=(MembershipRole.SERVICE_WORKER,),
                    authentication_strength=AuthenticationStrength.SERVICE_CREDENTIAL,
                ),
                acting_role=MembershipRole.REVIEWER,
            )

    def test_self_review_and_weak_authentication_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "self-review"):
            _approval(requestor_actor_id="reviewer-001")
        with self.assertRaisesRegex(ValueError, "multi-factor"):
            _approval(
                context=_context(authentication_strength=AuthenticationStrength.SINGLE_FACTOR)
            )

    def test_approval_validates_request_hash_version_reason_idempotency_and_time(self) -> None:
        for field_name, bad_value, message in (
            ("approval_request_sha256", "A" * 64, "approval_request_sha256"),
            ("expected_version", 0, "positive"),
            ("expected_version", True, "positive"),
            ("reason", " ", "reason"),
            ("idempotency_key", "short", "idempotency_key"),
            ("decided_at", datetime(2026, 7, 2, 8), "UTC"),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, message):
                    _approval(**{field_name: bad_value})

    def test_approval_wire_rejects_versions_unknown_fields_and_duplicate_keys(self) -> None:
        payload = _approval().to_dict()
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            ApprovalDecisionCommand.from_dict({**payload, "schema_version": "v2"})
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            ApprovalDecisionCommand.from_dict({**payload, "override_authority": True})
        duplicate = json.dumps(payload).replace(
            '"requestor_actor_id": "preparer-001",',
            '"requestor_actor_id": "preparer-001", "requestor_actor_id": "reviewer-001",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            ApprovalDecisionCommand.from_json(duplicate)


class ExternalDraftCommandTests(unittest.TestCase):
    def test_draft_is_frozen_hash_only_and_strictly_round_trips(self) -> None:
        command = _draft()
        self.assertEqual(command, ExternalDraftCommand.from_dict(command.to_dict()))
        self.assertEqual(64, len(command.canonical_sha256()))
        with self.assertRaises(FrozenInstanceError):
            command.provider_id = "netsuite"  # type: ignore[misc]

        forbidden_fields = {
            "action",
            "execute",
            "credentials",
            "access_token",
            "raw_data",
            "payload",
            "document_bytes",
            "document_text",
        }
        self.assertFalse(forbidden_fields & set(command.__dataclass_fields__))
        self.assertFalse(hasattr(command, "execute"))
        self.assertFalse(command.grants_authority)

    def test_only_supplier_invoice_drafts_are_representable(self) -> None:
        self.assertEqual(
            ExternalDraftRecordType.SUPPLIER_INVOICE,
            _draft().record_type,
        )
        with self.assertRaisesRegex(ValueError, "record type"):
            _draft(record_type="journal")
        with self.assertRaisesRegex(ValueError, "record type"):
            _draft(record_type="payment")

    def test_draft_binds_exact_scope_revision_hashes_and_strong_idempotency(self) -> None:
        for field_name, bad_value, message in (
            ("tenant_id", "unknown", "tenant_id"),
            ("client_id", "..", "client_id"),
            ("legal_entity_id", " entity", "legal_entity_id"),
            ("case_id", "case\nother", "case_id"),
            ("connection_revision", 0, "positive"),
            ("connection_sha256", "A" * 64, "connection_sha256"),
            ("environment", "maybe", "environment"),
            ("payload_sha256", "A" * 64, "payload_sha256"),
            ("policy_decision_sha256", "A" * 64, "policy_decision_sha256"),
            ("approval_receipt_sha256", "A" * 64, "approval_receipt_sha256"),
            ("approval_decision_sha256", "A" * 64, "approval_decision_sha256"),
            ("permit_sha256", "A" * 64, "permit_sha256"),
            ("idempotency_key", "weak", "idempotency_key"),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, message):
                    _draft(**{field_name: bad_value})

        with self.assertRaisesRegex(ValueError, "evidence_hashes must be a tuple"):
            _draft(evidence_hashes=[_hash("e")])
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            _draft(evidence_hashes=())
        with self.assertRaisesRegex(ValueError, "duplicates"):
            _draft(evidence_hashes=(_hash("e"), _hash("e")))

    def test_draft_times_are_utc_and_expiry_is_strictly_later(self) -> None:
        with self.assertRaisesRegex(ValueError, "created_at must be UTC"):
            _draft(created_at=datetime(2026, 7, 2, 8))
        with self.assertRaisesRegex(ValueError, "expires_at must be UTC"):
            _draft(expires_at=datetime(2026, 7, 2, 8, 5))
        with self.assertRaisesRegex(ValueError, "expire after"):
            _draft(expires_at=datetime(2026, 7, 2, 8, tzinfo=UTC))

    def test_draft_wire_rejects_versions_unknown_fields_and_duplicate_keys(self) -> None:
        payload = _draft().to_dict()
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            ExternalDraftCommand.from_dict({**payload, "schema_version": "v2"})
        for forbidden in ("action", "credentials", "payload", "execute"):
            with self.subTest(field=forbidden):
                with self.assertRaisesRegex(ValueError, "unexpected fields"):
                    ExternalDraftCommand.from_dict({**payload, forbidden: "forbidden"})
        duplicate = json.dumps(payload).replace(
            '"provider_id": "fortnox",',
            '"provider_id": "fortnox", "provider_id": "evil",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            ExternalDraftCommand.from_json(duplicate)


class ExternalDraftReceiptTests(unittest.TestCase):
    def test_only_exact_completed_unbooked_reversible_readback_is_safe(self) -> None:
        command = _draft()
        receipt = _receipt()
        self.assertFalse(receipt.is_frozen_for(command))
        self.assertFalse(receipt.requires_human_review_for(command))
        self.assertRegex(receipt.canonical_sha256(), r"^[0-9a-f]{64}$")
        self.assertNotEqual(
            receipt.canonical_sha256(),
            replace(
                receipt,
                observed_state=ExternalDraftObservedState.BOOKED,
            ).canonical_sha256(),
        )
        self.assertEqual(receipt, ExternalDraftReceipt.from_dict(receipt.to_dict()))
        receipt.assert_matches_command(command)
        self.assertTrue(
            receipt.is_frozen_for(
                replace(command, policy_decision_sha256=_hash("8"))
            )
        )
        with self.assertRaises(FrozenInstanceError):
            receipt.observed_state = ExternalDraftObservedState.BOOKED  # type: ignore[misc]

    def test_ambiguity_timeout_missing_and_mismatch_freeze_for_human_review(self) -> None:
        unsafe_receipts = (
            _receipt(
                provider_reference=None,
                provider_response_sha256=None,
                readback_sha256=None,
                readback_status=DraftReadbackStatus.AMBIGUOUS,
                observed_state=ExternalDraftObservedState.UNKNOWN,
                comparison_status=DraftComparisonStatus.NOT_AVAILABLE,
            ),
            _receipt(
                provider_reference=None,
                provider_response_sha256=None,
                readback_sha256=None,
                readback_status=DraftReadbackStatus.TIMEOUT,
                observed_state=ExternalDraftObservedState.UNKNOWN,
                comparison_status=DraftComparisonStatus.NOT_AVAILABLE,
            ),
            _receipt(
                provider_reference=None,
                provider_response_sha256=None,
                readback_sha256=None,
                readback_status=DraftReadbackStatus.MISSING,
                observed_state=ExternalDraftObservedState.MISSING,
                comparison_status=DraftComparisonStatus.NOT_AVAILABLE,
            ),
            _receipt(
                comparison_status=DraftComparisonStatus.MISMATCH,
                readback_sha256=_hash("6"),
            ),
            _receipt(comparison_status=DraftComparisonStatus.SCOPE_DRIFT),
        )
        for receipt in unsafe_receipts:
            with self.subTest(status=receipt.readback_status, comparison=receipt.comparison_status):
                self.assertTrue(receipt.is_frozen_for(_draft()))
                self.assertTrue(receipt.requires_human_review_for(_draft()))

    def test_booked_approved_sent_or_paid_states_always_freeze(self) -> None:
        for state in (
            ExternalDraftObservedState.BOOKED,
            ExternalDraftObservedState.APPROVED,
            ExternalDraftObservedState.SENT,
            ExternalDraftObservedState.PAID,
        ):
            with self.subTest(state=state):
                receipt = _receipt(observed_state=state)
                self.assertTrue(receipt.is_frozen_for(_draft()))
                self.assertTrue(receipt.requires_human_review_for(_draft()))

    def test_missing_readback_preserves_any_provider_creation_evidence(self) -> None:
        receipt = _receipt(
            readback_sha256=None,
            readback_status=DraftReadbackStatus.MISSING,
            observed_state=ExternalDraftObservedState.MISSING,
            comparison_status=DraftComparisonStatus.NOT_AVAILABLE,
        )
        self.assertEqual("supplier-invoice-draft-001", receipt.provider_reference)
        self.assertEqual(_hash("5"), receipt.provider_response_sha256)
        self.assertTrue(receipt.is_frozen_for(_draft()))
        self.assertTrue(receipt.requires_human_review_for(_draft()))

    def test_receipt_state_metadata_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "completed readback"):
            _receipt(provider_reference=None)
        with self.assertRaisesRegex(ValueError, "completed readback"):
            _receipt(readback_sha256=None)
        with self.assertRaisesRegex(ValueError, "non-completed readback"):
            _receipt(readback_status=DraftReadbackStatus.TIMEOUT)
        with self.assertRaisesRegex(ValueError, "missing readback"):
            _receipt(
                provider_reference=None,
                provider_response_sha256=None,
                readback_sha256=None,
                readback_status=DraftReadbackStatus.MISSING,
                observed_state=ExternalDraftObservedState.UNKNOWN,
                comparison_status=DraftComparisonStatus.NOT_AVAILABLE,
            )
        with self.assertRaisesRegex(ValueError, "exact match"):
            _receipt(readback_sha256=_hash("6"))
        with self.assertRaisesRegex(ValueError, "mismatch"):
            _receipt(comparison_status=DraftComparisonStatus.MISMATCH)

    def test_receipt_binds_exact_command_scope_and_attempt_window(self) -> None:
        receipt = _receipt()
        command = _draft()
        for field_name, bad_value in (
            ("draft_command_id", "draft-evil"),
            ("draft_command_sha256", _hash("9")),
            ("tenant_id", "tenant-evil"),
            ("client_id", "client-evil"),
            ("legal_entity_id", "entity-evil"),
            ("case_id", "case-evil"),
            ("connection_id", "connection-evil"),
            ("connection_revision", 4),
            ("connection_sha256", _hash("8")),
            ("provider_id", "netsuite"),
            ("environment", ConnectorEnvironment.PRODUCTION),
            ("idempotency_key", _hash("0")),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, "exact draft command"):
                    replace(receipt, **{field_name: bad_value}).assert_matches_command(command)

        with self.assertRaisesRegex(ValueError, "exact draft command"):
            replace(
                receipt,
                payload_sha256=_hash("7"),
                readback_sha256=_hash("7"),
            ).assert_matches_command(command)

        with self.assertRaisesRegex(ValueError, "valid command window"):
            replace(
                receipt,
                attempted_at=command.expires_at + timedelta(seconds=1),
                readback_at=command.expires_at + timedelta(seconds=2),
                recorded_at=command.expires_at + timedelta(seconds=3),
            ).assert_matches_command(command)

    def test_receipt_validates_hashes_references_and_monotonic_utc_times(self) -> None:
        for field_name, bad_value, message in (
            ("draft_command_sha256", "A" * 64, "draft_command_sha256"),
            ("provider_reference", " ", "provider_reference"),
            ("provider_response_sha256", "A" * 64, "provider_response_sha256"),
            ("readback_sha256", "A" * 64, "readback_sha256"),
            ("attempted_at", datetime(2026, 7, 2, 8, 1), "UTC"),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ValueError, message):
                    _receipt(**{field_name: bad_value})

        with self.assertRaisesRegex(ValueError, "monotonic"):
            _receipt(readback_at=datetime(2026, 7, 2, 8, tzinfo=UTC))
        with self.assertRaisesRegex(ValueError, "monotonic"):
            _receipt(recorded_at=datetime(2026, 7, 2, 8, 1, tzinfo=UTC))

    def test_receipt_wire_is_strict_duplicate_safe_and_network_free(self) -> None:
        receipt = _receipt()
        payload = receipt.to_dict()
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            ExternalDraftReceipt.from_dict({**payload, "schema_version": "v2"})
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            ExternalDraftReceipt.from_dict({**payload, "unfreeze": True})
        duplicate = json.dumps(payload).replace(
            '"observed_state": "unbooked_reversible",',
            '"observed_state": "unbooked_reversible", "observed_state": "paid",',
            1,
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            ExternalDraftReceipt.from_json(duplicate)

        with patch.object(socket, "socket", side_effect=AssertionError("network call")):
            self.assertEqual(receipt, ExternalDraftReceipt.from_dict(payload))
            self.assertEqual(_draft(), ExternalDraftCommand.from_dict(_draft().to_dict()))


if __name__ == "__main__":
    unittest.main()
