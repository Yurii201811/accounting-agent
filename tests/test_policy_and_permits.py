from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime

from accounting_agent import (
    ActionType,
    EmailWriteAdapter,
    ExecutionPermit,
    FortnoxWriteAdapter,
    InMemoryPermitStore,
    PermissionMode,
    PermitIssuer,
    PermitReviewRequired,
    PermitValidationError,
    PermitValidator,
    PolicyContext,
    PolicyDecision,
    SQLitePermitStore,
    canonical_payload_hash,
    evaluate_policy,
)


FIXED_NOW = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)


class PolicyDecisionTests(unittest.TestCase):
    def test_low_risk_draft_supplier_invoice_is_draft_only(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                amount_minor=1_500_00,
                supplier_known=True,
                duplicate_risk=0.0,
                vat_confidence=0.99,
                ocr_confidence=0.98,
                risk_evidence_complete=True,
            )
        )

        self.assertEqual(PermissionMode.DRAFT_ONLY, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)
        self.assertTrue(decision.is_external_write)

    def test_changed_bank_details_escalate(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.UPDATE_SUPPLIER_BANK_DETAILS,
                client_id="client_123",
                bank_details_changed=True,
            )
        )

        self.assertEqual(PermissionMode.ESCALATION_REQUIRED, decision.permission_mode)
        self.assertIn("senior_accountant_review", decision.required_reviews)
        self.assertIn("security_review", decision.required_reviews)

    def test_large_amount_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                amount_minor=50_000_00,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("accountant_review", decision.required_reviews)
        self.assertIn("amount_exceeds_draft_threshold", decision.reasons)

    def test_unknown_supplier_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                supplier_known=False,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("supplier_not_previously_known", decision.reasons)

    def test_vat_uncertainty_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                vat_confidence=0.71,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("vat_confidence_below_threshold", decision.reasons)

    def test_duplicate_risk_requires_approval(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                duplicate_risk=0.87,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("duplicate_risk", decision.reasons)

    def test_destructive_action_is_forbidden(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DELETE_RECORD,
                client_id="client_123",
                destructive_action=True,
            )
        )

        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)

    def test_payment_is_forbidden(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.START_PAYMENT,
                client_id="client_123",
                tax_filing_payment=True,
            )
        )

        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)

    def test_live_bank_reconciliation_is_forbidden(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.RECONCILE_BANK_TRANSACTION,
                client_id="client_123",
                amount_minor=1_500_00,
            )
        )

        self.assertEqual(PermissionMode.FORBIDDEN, decision.permission_mode)
        self.assertEqual((), decision.required_reviews)

    def test_tax_filing_escalates(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.FILE_TAX_RETURN,
                client_id="client_123",
                tax_filing_payment=True,
            )
        )

        self.assertEqual(PermissionMode.ESCALATION_REQUIRED, decision.permission_mode)
        self.assertIn("client_responsible_review", decision.required_reviews)


class PermitAndExternalWriteTests(unittest.TestCase):
    def test_external_write_requires_valid_execution_permit(self) -> None:
        adapter = FortnoxWriteAdapter()
        payload = {"supplier_id": "supplier_1", "amount_minor": 1_500_00}

        with self.assertRaises(PermitValidationError):
            adapter.execute(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                case_id="case_1",
                payload=payload,
                permit=None,
            )

    def test_valid_draft_permit_allows_adapter_boundary(self) -> None:
        store = InMemoryPermitStore()
        issuer = PermitIssuer(
            store,
            clock=lambda: FIXED_NOW,
            id_factory=lambda: "permit_test_1",
        )
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            amount_minor=1_500_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)
        payload = {"supplier_id": "supplier_1", "amount_minor": 1_500_00}

        permit = issuer.issue(
            decision=decision,
            context=context,
            case_id="case_1",
            payload=payload,
        )
        result = FortnoxWriteAdapter(
            PermitValidator(accepted_policy_version=decision.policy_version, clock=lambda: FIXED_NOW)
        ).execute(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            case_id="case_1",
            payload=payload,
            permit=permit,
        )

        self.assertEqual("permit_validated_no_live_write", result.status)
        self.assertEqual(permit.idempotency_key, result.idempotency_key)
        self.assertEqual(permit, store.get("permit_test_1"))

    def test_payload_change_invalidates_permit(self) -> None:
        issuer = PermitIssuer(clock=lambda: FIXED_NOW, id_factory=lambda: "permit_test_2")
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            amount_minor=1_500_00,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)
        permit = issuer.issue(
            decision=decision,
            context=context,
            case_id="case_1",
            payload={"supplier_id": "supplier_1", "amount_minor": 1_500_00},
        )

        with self.assertRaises(PermitValidationError):
            FortnoxWriteAdapter(
                PermitValidator(accepted_policy_version=decision.policy_version, clock=lambda: FIXED_NOW)
            ).execute(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                case_id="case_1",
                payload={"supplier_id": "supplier_1", "amount_minor": 1_600_00},
                permit=permit,
            )

    def test_approval_required_decision_cannot_issue_without_review(self) -> None:
        issuer = PermitIssuer(clock=lambda: FIXED_NOW, id_factory=lambda: "permit_test_3")
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            amount_minor=50_000_00,
        )
        decision = evaluate_policy(context)

        with self.assertRaises(PermitReviewRequired):
            issuer.issue(
                decision=decision,
                context=context,
                case_id="case_1",
                payload={"amount_minor": 50_000_00},
            )

    def test_email_adapter_validates_permit_but_does_not_send(self) -> None:
        issuer = PermitIssuer(clock=lambda: FIXED_NOW, id_factory=lambda: "permit_test_4")
        context = PolicyContext(
            action_type=ActionType.SEND_EMAIL,
            client_id="client_123",
            external_communication=True,
        )
        decision = evaluate_policy(context)
        payload = {"to": "reviewer@example.invalid", "subject": "Missing receipt"}
        permit = issuer.issue(
            decision=decision,
            context=context,
            case_id="case_2",
            payload=payload,
            approved_reviews=("accountant_review",),
        )

        result = EmailWriteAdapter(
            PermitValidator(accepted_policy_version=decision.policy_version, clock=lambda: FIXED_NOW)
        ).execute(
            action_type=ActionType.SEND_EMAIL,
            case_id="case_2",
            payload=payload,
            permit=permit,
        )

        self.assertEqual("permit_validated_no_email_sent", result.status)

    def test_sqlite_store_round_trips_permit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLitePermitStore(f"{temp_dir}/permits.sqlite")
            issuer = PermitIssuer(
                store,
                clock=lambda: FIXED_NOW,
                id_factory=lambda: "permit_test_5",
            )
            context = PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                amount_minor=1_500_00,
                risk_evidence_complete=True,
            )
            decision = evaluate_policy(context)
            permit = issuer.issue(
                decision=decision,
                context=context,
                case_id="case_1",
                payload={"amount_minor": 1_500_00},
            )

            self.assertEqual(permit, store.get("permit_test_5"))

    def test_missing_risk_evidence_fails_closed_for_external_draft(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="client_123",
                amount_minor=1_500_00,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("risk_evidence_incomplete", decision.reasons)

    def test_unmapped_client_fails_closed_for_external_draft(self) -> None:
        decision = evaluate_policy(
            PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id="unmapped",
                amount_minor=1_500_00,
                risk_evidence_complete=True,
            )
        )

        self.assertEqual(PermissionMode.APPROVAL_REQUIRED, decision.permission_mode)
        self.assertIn("client_mapping_unmapped", decision.reasons)

    def test_forged_policy_decision_cannot_issue_permit(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="client_123",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        real_decision = evaluate_policy(context)
        forged_decision = PolicyDecision(
            action_type=real_decision.action_type,
            client_id=real_decision.client_id,
            permission_mode=PermissionMode.DRAFT_ONLY,
            policy_version=real_decision.policy_version,
            amount_thresholds=real_decision.amount_thresholds,
            required_reviews=(),
            reasons=("forged",),
            is_external_write=real_decision.is_external_write,
        )

        with self.assertRaises(PermitValidationError):
            PermitIssuer(clock=lambda: FIXED_NOW).issue(
                decision=forged_decision,
                context=context,
                case_id="case_forged",
                payload={"amount_minor": 50_000_00},
            )

    def test_direct_permit_with_empty_idempotency_key_is_rejected(self) -> None:
        payload = {"supplier_id": "supplier_1", "amount_minor": 1_500_00}
        permit = ExecutionPermit(
            permit_id="permit_direct",
            case_id="case_direct",
            client_id="client_123",
            allowed_action=ActionType.DRAFT_SUPPLIER_INVOICE,
            payload_hash=canonical_payload_hash(payload),
            policy_version="accounting-policy-v1",
            required_reviews=(),
            permission_mode=PermissionMode.DRAFT_ONLY,
            expires_at=datetime(2026, 5, 16, 12, 30, tzinfo=UTC),
            idempotency_key="",
            issued_at=FIXED_NOW,
        )

        with self.assertRaises(PermitValidationError):
            FortnoxWriteAdapter(
                PermitValidator(clock=lambda: FIXED_NOW)
            ).execute(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                case_id="case_direct",
                payload=payload,
                permit=permit,
            )


if __name__ == "__main__":
    unittest.main()
