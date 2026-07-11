from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import accounting_agent.approvals as approvals
import accounting_agent.evidence as evidence
import accounting_agent.permits as permits
from accounting_agent.policy import (
    ActionType,
    PermissionMode,
    PolicyContext,
    evaluate_policy,
)
from tests.permit_approval_helpers import issue_test_permit

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
CLIENT_ID = "synthetic-client"
ENTITY_ID = "synthetic-entity"
CASE_ID = "synthetic-case"
PAYLOAD = {"supplier": "synthetic", "amount_minor": 125_00}


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _binding(**changes: Any) -> approvals.ApprovalBinding:
    values: dict[str, Any] = {
        "client_id": CLIENT_ID,
        "entity_id": ENTITY_ID,
        "case_id": CASE_ID,
        "proposal_hash": _digest("proposal"),
        "evidence_hashes": (_digest("evidence"),),
        "policy_hash": _digest("policy"),
        "provider_id": "synthetic-provider",
        "environment": "test",
    }
    values.update(changes)
    return approvals.ApprovalBinding(**values)


def _request(**changes: Any) -> approvals.ApprovalRequest:
    values: dict[str, Any] = {
        "request_id": "synthetic-request",
        "binding": _binding(),
        "action": ActionType.DRAFT_SUPPLIER_INVOICE.value,
        "requestor_id": "synthetic-requestor",
        "required_roles": (approvals.ReviewerRole.REVIEWER,),
        "created_at": NOW - timedelta(minutes=10),
        "expires_at": NOW + timedelta(minutes=30),
    }
    values.update(changes)
    return approvals.ApprovalRequest(**values)


def _draft_material() -> tuple[
    permits.ExecutionPermit,
    PolicyContext,
    Any,
    dict[str, Any],
    permits.InMemoryPermitStore,
]:
    context = PolicyContext(
        action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
        client_id=CLIENT_ID,
        currency_code="SEK",
        risk_evidence_complete=True,
    )
    decision = evaluate_policy(context)
    store = permits.InMemoryPermitStore()
    permit = permits.PermitIssuer(
        store,
        clock=lambda: NOW,
        id_factory=lambda: "permit-synthetic-draft",
    ).issue(
        decision=decision,
        context=context,
        case_id=CASE_ID,
        entity_id=ENTITY_ID,
        payload=PAYLOAD,
    )
    return permit, context, decision, PAYLOAD, store


def _receipt(**changes: Any) -> permits.PermitApprovalReceipt:
    values: dict[str, Any] = {
        "request_id": "synthetic-approval",
        "binding_digest": _digest("binding"),
        "request_digest": _digest("request"),
        "client_id": CLIENT_ID,
        "entity_id": ENTITY_ID,
        "case_id": CASE_ID,
        "action": ActionType.DRAFT_SUPPLIER_INVOICE.value,
        "payload_hash": permits.canonical_payload_hash(PAYLOAD),
        "policy_hash": _digest("policy"),
        "decision_ids": ("decision-synthetic",),
        "verified_at": NOW,
    }
    values.update(changes)
    return permits.PermitApprovalReceipt(**values)


class PermitSafetyBranchTests(unittest.TestCase):
    def test_approval_receipt_rejects_every_noncanonical_identity_shape(self) -> None:
        invalid_values = (
            {"request_id": " synthetic-approval"},
            {"client_id": "e\u0301"},
            {"entity_id": "e\u0301"},
            {"case_id": " synthetic-case"},
            {"action": "draft_supplier_invoice "},
            {"decision_ids": ()},
            {"decision_ids": ("same", "same")},
            {"decision_ids": (" decision",)},
        )
        for changes in invalid_values:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _receipt(**changes)

    def test_review_requirement_mapping_rejects_empty_unknown_and_duplicate_roles(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id=CLIENT_ID,
            currency_code="SEK",
            risk_evidence_complete=True,
        )
        base = evaluate_policy(context)
        for reviews in (
            (),
            ("unsupported_review",),
            ("accountant_review", "accountant_review"),
        ):
            with self.subTest(reviews=reviews), self.assertRaises(permits.PermitReviewRequired):
                permits.build_permit_approval_request(
                    request_id="approval-mapping-test",
                    decision=replace(base, required_reviews=reviews),
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    payload=PAYLOAD,
                    evidence_hashes=(_digest("evidence"),),
                    provider_id="synthetic-provider",
                    environment="test",
                    requestor_id="synthetic-requestor",
                    created_at=NOW - timedelta(minutes=1),
                    expires_at=NOW + timedelta(minutes=10),
                )

    def test_issuer_fails_closed_for_forbidden_mismatched_and_stale_decisions(self) -> None:
        permit, context, decision, payload, _ = _draft_material()
        del permit

        forbidden_context = PolicyContext(
            action_type=ActionType.DELETE_RECORD,
            client_id=CLIENT_ID,
            currency_code="SEK",
            destructive_action=True,
        )
        with self.assertRaises(permits.PermitForbidden):
            permits.PermitIssuer(clock=lambda: NOW).issue(
                decision=evaluate_policy(forbidden_context),
                context=forbidden_context,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                payload=payload,
            )

        early_mismatches = (
            replace(decision, action_type=ActionType.DRAFT_VOUCHER),
            replace(decision, client_id="other-client"),
        )
        for candidate in early_mismatches:
            with (
                self.subTest(candidate=candidate),
                self.assertRaises(permits.PermitValidationError),
            ):
                permits.PermitIssuer(clock=lambda: NOW).issue(
                    decision=candidate,
                    context=context,
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    payload=payload,
                )

        stale_decisions = (
            replace(decision, permission_mode=PermissionMode.APPROVAL_REQUIRED),
            replace(decision, policy_version="stale-policy"),
            replace(decision, currency_code="EUR"),
            replace(decision, amount_thresholds=None),
            replace(decision, is_external_write=False),
        )
        for candidate in stale_decisions:
            with (
                self.subTest(candidate=candidate),
                self.assertRaisesRegex(permits.PermitValidationError, "current policy"),
            ):
                permits.PermitIssuer(clock=lambda: NOW).issue(
                    decision=candidate,
                    context=context,
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    payload=payload,
                )

    def test_issuer_requires_persistence_for_review_and_rejects_spurious_approval(self) -> None:
        with tempfile.TemporaryDirectory():
            reviewed_context = PolicyContext(
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                client_id=CLIENT_ID,
                currency_code="SEK",
                amount_minor=50_000_00,
                risk_evidence_complete=True,
            )
            _, decision, _, authority = issue_test_permit(
                context=reviewed_context,
                case_id=CASE_ID,
                payload=PAYLOAD,
                now=NOW,
                permit_id="permit-review-source",
                entity_id=ENTITY_ID,
            )
            assert authority is not None
            request = authority.get_request("approval_permit-review-source")
            assert request is not None
            with self.assertRaisesRegex(permits.PermitReviewRequired, "persistence"):
                permits.PermitIssuer(
                    approval_authority=authority,
                    clock=lambda: NOW,
                ).issue(
                    decision=decision,
                    context=reviewed_context,
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    payload=PAYLOAD,
                    approval_request=request,
                )

            _, draft_context, draft_decision, payload, _ = _draft_material()
            with self.assertRaisesRegex(permits.PermitValidationError, "zero-review"):
                permits.PermitIssuer(clock=lambda: NOW).issue(
                    decision=draft_decision,
                    context=draft_context,
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    payload=payload,
                    approval_request=request,
                )

    def test_issuer_rejects_invalid_verification_even_when_all_digests_match(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id=CLIENT_ID,
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        permit, decision, _, authority = issue_test_permit(
            context=context,
            case_id=CASE_ID,
            payload=PAYLOAD,
            now=NOW,
            permit_id="permit-invalid-only-verification",
            entity_id=ENTITY_ID,
        )
        assert authority is not None
        assert permit.approval_receipt is not None
        request = authority.get_request(permit.approval_receipt.request_id)
        assert request is not None

        class InvalidOnlyAuthority:
            def get_request(self, request_id: str) -> approvals.ApprovalRequest | None:
                return authority.get_request(request_id)

            def verify(
                self, expected_request: approvals.ApprovalRequest, *, now: datetime
            ) -> approvals.ApprovalVerification:
                return replace(
                    authority.verify(expected_request, now=now),
                    valid=False,
                    errors=(),
                )

        with self.assertRaisesRegex(permits.PermitReviewRequired, "not valid"):
            permits.PermitIssuer(
                permits.InMemoryPermitStore(),
                approval_authority=InvalidOnlyAuthority(),
                clock=lambda: NOW,
                id_factory=lambda: "permit-invalid-only-result",
            ).issue(
                decision=decision,
                context=context,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                payload=PAYLOAD,
                approval_request=request,
            )

    def test_issuer_rejects_each_isolated_approval_verification_mismatch(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id=CLIENT_ID,
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        permit, decision, _, authority = issue_test_permit(
            context=context,
            case_id=CASE_ID,
            payload=PAYLOAD,
            now=NOW,
            permit_id="permit-isolated-issuer-mismatches",
            entity_id=ENTITY_ID,
        )
        assert authority is not None
        assert permit.approval_receipt is not None
        request = authority.get_request(permit.approval_receipt.request_id)
        assert request is not None

        for changes in (
            {"valid": False},
            {"request_id": "synthetic-other-request"},
            {"binding_digest": _digest("synthetic-other-binding")},
            {"request_digest": _digest("synthetic-other-request-digest")},
            {"missing_roles": (approvals.ReviewerRole.REVIEWER,)},
            {"decision_ids": ()},
            {"errors": ("synthetic_isolated_error",)},
        ):
            class MismatchAuthority:
                def get_request(
                    self, request_id: str
                ) -> approvals.ApprovalRequest | None:
                    return authority.get_request(request_id)

                def verify(
                    self,
                    expected_request: approvals.ApprovalRequest,
                    *,
                    now: datetime,
                ) -> approvals.ApprovalVerification:
                    return replace(
                        authority.verify(expected_request, now=now),
                        **changes,
                    )

            with (
                self.subTest(changes=changes),
                self.assertRaises(permits.PermitReviewRequired),
            ):
                permits.PermitIssuer(
                    permits.InMemoryPermitStore(),
                    approval_authority=MismatchAuthority(),
                    clock=lambda: NOW,
                    id_factory=lambda: "permit-isolated-issuer-result",
                ).issue(
                    decision=decision,
                    context=context,
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    payload=PAYLOAD,
                    approval_request=request,
                )

        for approval_authority, approval_request in (
            (None, request),
            (authority, None),
        ):
            with self.assertRaises(permits.PermitReviewRequired):
                permits.PermitIssuer(
                    permits.InMemoryPermitStore(),
                    approval_authority=approval_authority,
                    clock=lambda: NOW,
                ).issue(
                    decision=decision,
                    context=context,
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    payload=PAYLOAD,
                    approval_request=approval_request,
                )

    def test_validator_rejects_malformed_and_scope_mutated_permits(self) -> None:
        base, _, _, payload, _ = _draft_material()
        dummy_receipt = _receipt(policy_hash=base.policy_decision_hash)
        malformed = (
            (replace(base, permit_id=" "), CASE_ID, ENTITY_ID, base.allowed_action, payload),
            (replace(base, case_id=" "), CASE_ID, ENTITY_ID, base.allowed_action, payload),
            (replace(base, client_id=" "), CASE_ID, ENTITY_ID, base.allowed_action, payload),
            (replace(base, idempotency_key=" "), CASE_ID, ENTITY_ID, base.allowed_action, payload),
            (
                replace(base, allowed_action=ActionType.READ_ANALYSIS),
                CASE_ID,
                ENTITY_ID,
                ActionType.READ_ANALYSIS,
                payload,
            ),
            (
                replace(base, permission_mode=PermissionMode.AUTO_ALLOWED),
                CASE_ID,
                ENTITY_ID,
                base.allowed_action,
                payload,
            ),
            (
                replace(base, permission_mode=PermissionMode.APPROVAL_REQUIRED),
                CASE_ID,
                ENTITY_ID,
                base.allowed_action,
                payload,
            ),
            (
                replace(
                    base,
                    permission_mode=PermissionMode.APPROVAL_REQUIRED,
                    required_reviews=("accountant_review",),
                ),
                CASE_ID,
                ENTITY_ID,
                base.allowed_action,
                payload,
            ),
            (
                replace(base, approval_receipt=dummy_receipt),
                CASE_ID,
                ENTITY_ID,
                base.allowed_action,
                payload,
            ),
            (base, "other-case", ENTITY_ID, base.allowed_action, payload),
            (base, CASE_ID, ENTITY_ID, ActionType.DRAFT_VOUCHER, payload),
            (
                replace(base, issued_at=base.expires_at),
                CASE_ID,
                ENTITY_ID,
                base.allowed_action,
                payload,
            ),
            (
                replace(
                    base,
                    issued_at=NOW - timedelta(hours=2),
                    expires_at=NOW,
                ),
                CASE_ID,
                ENTITY_ID,
                base.allowed_action,
                payload,
            ),
            (
                replace(base, idempotency_key=_digest("wrong-key")),
                CASE_ID,
                ENTITY_ID,
                base.allowed_action,
                payload,
            ),
        )
        for candidate, case_id, entity_id, action, attempted_payload in malformed:
            with (
                self.subTest(candidate=candidate),
                self.assertRaises(permits.PermitValidationError),
            ):
                permits.PermitValidator(clock=lambda: NOW).require_valid(
                    permit=candidate,
                    case_id=case_id,
                    entity_id=entity_id,
                    action_type=action,
                    payload=attempted_payload,
                )

        for entity_id in (" e", "e\u0301"):
            candidate = base if entity_id.startswith(" ") else replace(base, entity_id=entity_id)
            with (
                self.subTest(entity_id=entity_id),
                self.assertRaises(permits.PermitValidationError),
            ):
                permits.PermitValidator(clock=lambda: NOW).require_valid(
                    permit=candidate,
                    case_id=CASE_ID,
                    entity_id=entity_id if entity_id.startswith(" ") else "\u00e9",
                    action_type=base.allowed_action,
                    payload=payload,
                )

        with self.assertRaisesRegex(permits.PermitValidationError, "policy version"):
            permits.PermitValidator(
                accepted_policy_version="other-policy",
                clock=lambda: NOW,
            ).require_valid(
                permit=base,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=base.allowed_action,
                payload=payload,
            )
        with self.assertRaisesRegex(permits.PermitValidationError, "payload hash"):
            permits.PermitValidator(clock=lambda: NOW).require_valid(
                permit=base,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=base.allowed_action,
                payload={"different": True},
            )
        with self.assertRaisesRegex(permits.PermitValidationError, "policy_decision_hash"):
            permits.PermitValidator(clock=lambda: NOW).require_valid(
                permit=replace(base, policy_decision_hash="invalid"),
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=base.allowed_action,
                payload=payload,
            )

    def test_reviewed_permit_revalidation_rejects_mutated_trust_material(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id=CLIENT_ID,
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        permit, _, trusted_permits, authority = issue_test_permit(
            context=context,
            case_id=CASE_ID,
            payload=PAYLOAD,
            now=NOW,
            permit_id="permit-reviewed-branches",
            entity_id=ENTITY_ID,
        )
        assert authority is not None
        assert permit.approval_receipt is not None
        request = authority.get_request(permit.approval_receipt.request_id)
        assert request is not None

        with self.assertRaisesRegex(permits.PermitValidationError, "verification time"):
            permits.PermitValidator(
                permit_store=trusted_permits,
                approval_authority=authority,
                clock=lambda: NOW,
            ).require_valid(
                permit=replace(
                    permit,
                    approval_receipt=replace(
                        permit.approval_receipt,
                        verified_at=NOW - timedelta(seconds=1),
                    ),
                ),
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=permit.allowed_action,
                payload=PAYLOAD,
            )

        with self.assertRaisesRegex(permits.PermitValidationError, "approval authority"):
            permits.PermitValidator(
                permit_store=trusted_permits,
                clock=lambda: NOW,
            ).require_valid(
                permit=permit,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=permit.allowed_action,
                payload=PAYLOAD,
            )

    def test_validator_rejects_each_isolated_authority_revalidation_mismatch(self) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id=CLIENT_ID,
            currency_code="SEK",
            amount_minor=50_000_00,
            risk_evidence_complete=True,
        )
        permit, _, trusted_permits, authority = issue_test_permit(
            context=context,
            case_id=CASE_ID,
            payload=PAYLOAD,
            now=NOW,
            permit_id="permit-isolated-validator-mismatches",
            entity_id=ENTITY_ID,
        )
        assert authority is not None
        assert permit.approval_receipt is not None
        request = authority.get_request(permit.approval_receipt.request_id)
        assert request is not None

        for changes in (
            {"valid": False},
            {"request_id": "synthetic-other-request"},
            {"binding_digest": _digest("synthetic-other-binding")},
            {"request_digest": _digest("synthetic-other-request-digest")},
            {"missing_roles": (approvals.ReviewerRole.REVIEWER,)},
            {"decision_ids": ("synthetic-other-decision",)},
            {"errors": ("synthetic_isolated_error",)},
        ):
            class MismatchAuthority:
                def get_request(
                    self, request_id: str
                ) -> approvals.ApprovalRequest | None:
                    return authority.get_request(request_id)

                def verify(
                    self,
                    expected_request: approvals.ApprovalRequest,
                    *,
                    now: datetime,
                ) -> approvals.ApprovalVerification:
                    return replace(
                        authority.verify(expected_request, now=now),
                        **changes,
                    )

            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(permits.PermitValidationError, "revalidation"),
            ):
                permits.PermitValidator(
                    permit_store=trusted_permits,
                    approval_authority=MismatchAuthority(),
                    clock=lambda: NOW,
                ).require_valid(
                    permit=permit,
                    case_id=CASE_ID,
                    entity_id=ENTITY_ID,
                    action_type=permit.allowed_action,
                    payload=PAYLOAD,
                )

        class RequestMismatchAuthority:
            def get_request(self, request_id: str) -> approvals.ApprovalRequest | None:
                return replace(request, action=ActionType.DRAFT_VOUCHER.value)

            def verify(
                self, expected_request: approvals.ApprovalRequest, *, now: datetime
            ) -> approvals.ApprovalVerification:
                return authority.verify(expected_request, now=now)

        with self.assertRaisesRegex(permits.PermitValidationError, "trusted approval request"):
            permits.PermitValidator(
                permit_store=trusted_permits,
                approval_authority=RequestMismatchAuthority(),
                clock=lambda: NOW,
            ).require_valid(
                permit=permit,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=permit.allowed_action,
                payload=PAYLOAD,
            )

        role_mutated = replace(permit, required_reviews=("security_review",))
        role_store = permits.InMemoryPermitStore()
        role_store.save(role_mutated)
        with self.assertRaisesRegex(permits.PermitValidationError, "roles"):
            permits.PermitValidator(
                permit_store=role_store,
                approval_authority=authority,
                clock=lambda: NOW,
            ).require_valid(
                permit=role_mutated,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=permit.allowed_action,
                payload=PAYLOAD,
            )

        class InvalidVerificationAuthority:
            def get_request(self, request_id: str) -> approvals.ApprovalRequest | None:
                return request

            def verify(
                self, expected_request: approvals.ApprovalRequest, *, now: datetime
            ) -> approvals.ApprovalVerification:
                return replace(
                    authority.verify(expected_request, now=now),
                    valid=False,
                    errors=("synthetic_revalidation_failure",),
                )

        with self.assertRaisesRegex(permits.PermitValidationError, "revalidation"):
            permits.PermitValidator(
                permit_store=trusted_permits,
                approval_authority=InvalidVerificationAuthority(),
                clock=lambda: NOW,
            ).require_valid(
                permit=permit,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=permit.allowed_action,
                payload=PAYLOAD,
            )

        class DecisionMismatchOnlyAuthority:
            def get_request(self, request_id: str) -> approvals.ApprovalRequest | None:
                return authority.get_request(request_id)

            def verify(
                self, expected_request: approvals.ApprovalRequest, *, now: datetime
            ) -> approvals.ApprovalVerification:
                return replace(
                    authority.verify(expected_request, now=now),
                    decision_ids=("synthetic-mismatched-decision",),
                    errors=(),
                )

        with self.assertRaisesRegex(permits.PermitValidationError, "revalidation"):
            permits.PermitValidator(
                permit_store=trusted_permits,
                approval_authority=DecisionMismatchOnlyAuthority(),
                clock=lambda: NOW,
            ).require_valid(
                permit=permit,
                case_id=CASE_ID,
                entity_id=ENTITY_ID,
                action_type=permit.allowed_action,
                payload=PAYLOAD,
            )

    def test_sqlite_store_translates_non_duplicate_integrity_failure(self) -> None:
        base, _, _, _, _ = _draft_material()
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "permits.sqlite"
            store = permits.SQLitePermitStore(database)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER synthetic_permit_rejection
                    BEFORE INSERT ON execution_permits
                    BEGIN
                        SELECT RAISE(ABORT, 'synthetic integrity failure');
                    END
                    """
                )
            with self.assertRaisesRegex(permits.PermitValidationError, "could not be persisted"):
                store.save(base)

    def test_permit_serialization_helpers_cover_datetime_enum_and_invalid_inputs(self) -> None:
        payload_hash = permits.canonical_payload_hash(
            {"permission": PermissionMode.DRAFT_ONLY, "created_at": NOW}
        )
        self.assertEqual(64, len(payload_hash))
        self.assertIs(permits._parse_datetime(NOW), NOW)
        self.assertEqual(UTC, permits._parse_datetime("2026-07-11T12:00:00").tzinfo)
        with self.assertRaises(ValueError):
            permits._require_sha256("not-a-digest", "synthetic")
        with self.assertRaises(ValueError):
            permits._require_aware(datetime(2026, 7, 11, 12, 0), "synthetic")


class ApprovalSafetyBranchTests(unittest.TestCase):
    def test_identity_binding_and_request_validation_fail_closed(self) -> None:
        identity_cases: tuple[dict[str, Any], ...] = (
            {"roles": ()},
            {"roles": (approvals.ReviewerRole.REVIEWER,) * 2},
            {"verified": 1},
            {"reviewer_id": " reviewer"},
        )
        for changes in identity_cases:
            values: dict[str, Any] = {
                "reviewer_id": "synthetic-reviewer",
                "client_id": CLIENT_ID,
                "roles": (approvals.ReviewerRole.REVIEWER,),
                "identity_provider": "synthetic-idp",
                "verified": True,
                "active": True,
            }
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                approvals.ReviewerIdentity(**values)

        binding_cases: tuple[dict[str, Any], ...] = (
            {"evidence_hashes": ()},
            {"evidence_hashes": (_digest("same"), _digest("same"))},
            {"environment": "production"},
            {"proposal_hash": "invalid"},
        )
        for changes in binding_cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _binding(**changes)

        request_cases: tuple[dict[str, Any], ...] = (
            {"required_roles": ()},
            {"required_roles": (approvals.ReviewerRole.REVIEWER,) * 2},
            {"expires_at": NOW - timedelta(minutes=10)},
            {"created_at": datetime(2026, 7, 11, 12, 0)},
        )
        for changes in request_cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                _request(**changes)

    def test_store_rejects_missing_request_bad_timing_and_unauthorized_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = approvals.SQLiteApprovalStore(
                Path(directory) / "approvals.sqlite",
                clock=lambda: NOW,
            )
            with self.assertRaisesRegex(approvals.ApprovalValidationError, "does not exist"):
                store.record_decision(
                    request_id="missing-request",
                    reviewer_id="missing-reviewer",
                    role=approvals.ReviewerRole.REVIEWER,
                    outcome=approvals.ApprovalOutcome.APPROVE,
                    reason="Synthetic test.",
                    decided_at=NOW,
                )

            request = _request()
            store.create_request(request)
            store.register_reviewer(
                approvals.ReviewerIdentity(
                    reviewer_id="synthetic-reviewer",
                    client_id=CLIENT_ID,
                    roles=(approvals.ReviewerRole.AUDITOR,),
                    identity_provider="synthetic-idp",
                    verified=True,
                    active=True,
                )
            )
            with self.assertRaisesRegex(approvals.ApprovalValidationError, "validity window"):
                store.record_decision(
                    request_id=request.request_id,
                    reviewer_id="synthetic-reviewer",
                    role=approvals.ReviewerRole.AUDITOR,
                    outcome=approvals.ApprovalOutcome.APPROVE,
                    reason="Synthetic test.",
                    decided_at=request.created_at - timedelta(seconds=1),
                )
            with self.assertRaisesRegex(approvals.ApprovalValidationError, "authorized"):
                store.record_decision(
                    request_id=request.request_id,
                    reviewer_id="synthetic-reviewer",
                    role=approvals.ReviewerRole.AUDITOR,
                    outcome=approvals.ApprovalOutcome.APPROVE,
                    reason="Synthetic test.",
                    decided_at=NOW,
                )

    def test_verification_rejects_wrong_type_missing_and_tampered_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "approvals.sqlite"
            store = approvals.SQLiteApprovalStore(database, clock=lambda: NOW)
            with self.assertRaises(TypeError):
                store.verify("not-a-request", now=NOW)  # type: ignore[arg-type]

            missing = store.verify(_request(), now=NOW)
            self.assertFalse(missing.valid)
            self.assertIn("approval_request_not_found", missing.errors[0])

            request = _request()
            store.create_request(request)
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE approval_requests SET binding_digest = ? WHERE request_id = ?",
                    (_digest("tampered-binding"), request.request_id),
                )
            with self.assertRaisesRegex(approvals.ApprovalValidationError, "integrity"):
                store.get_request(request.request_id)

    def test_second_schema_open_exercises_nonunique_index_migration_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "approvals.sqlite"
            approvals.SQLiteApprovalStore(database)
            approvals.SQLiteApprovalStore(database)
            with sqlite3.connect(database) as connection:
                rows = connection.execute("PRAGMA index_list(approval_requests)").fetchall()
            self.assertTrue(any(row[1] == "approval_requests_binding_lookup" for row in rows))


class EvidenceSafetyBranchTests(unittest.TestCase):
    def test_provenance_and_record_validation_rejects_ambiguous_metadata(self) -> None:
        provenance_cases: tuple[dict[str, Any], ...] = (
            {"field_path": " amount"},
            {"page": 0},
            {"bounding_box": (0.0, 1.0, 2.0)},
            {"source_hash": "invalid"},
        )
        for changes in provenance_cases:
            values: dict[str, Any] = {
                "source_hash": _digest("source"),
                "field_path": "invoice.amount",
                "extractor": "synthetic-parser",
                "extractor_version": "1",
            }
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                evidence.FieldProvenance(**values)

        record_values: dict[str, Any] = {
            "client_id": CLIENT_ID,
            "evidence_id": "ev_synthetic",
            "content_sha256": _digest("content"),
            "media_type": "text/plain",
            "size_bytes": 7,
            "created_at": NOW,
            "storage_key": "synthetic-key",
        }
        record_cases: tuple[dict[str, Any], ...] = (
            {"evidence_id": ""},
            {"size_bytes": -1},
            {"created_at": datetime(2026, 7, 11, 12, 0)},
        )
        for changes in record_cases:
            values = record_values | changes
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                evidence.EvidenceRecord(**values)

    def test_store_rejects_bad_input_existing_metadata_and_object_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = evidence.ContentAddressedEvidenceStore(directory, clock=lambda: NOW)
            with self.assertRaises(TypeError):
                store.put(client_id=CLIENT_ID, content=bytearray(b"bad"), media_type="text/plain")  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                store.put(client_id=CLIENT_ID, content=b"bad", media_type=" text/plain")

        for mode in ("scope", "media", "bytes"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                store = evidence.ContentAddressedEvidenceStore(directory, clock=lambda: NOW)
                record = store.put(
                    client_id=CLIENT_ID,
                    content=b"synthetic evidence",
                    media_type="text/plain",
                )
                object_path = store.path_for(client_id=CLIENT_ID, record=record)
                metadata_path = object_path.with_suffix(".json")
                if mode == "scope":
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    metadata["client_id"] = "other-client"
                    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
                    expected = "scope"
                    requested_media = "text/plain"
                elif mode == "media":
                    expected = "media type"
                    requested_media = "application/pdf"
                else:
                    object_path.write_bytes(b"tampered")
                    expected = "integrity"
                    requested_media = "text/plain"
                with self.assertRaisesRegex(evidence.EvidenceIntegrityError, expected):
                    store.put(
                        client_id=CLIENT_ID,
                        content=b"synthetic evidence",
                        media_type=requested_media,
                    )

    def test_read_detects_missing_size_and_storage_key_mutations(self) -> None:
        for mode in ("missing", "size", "storage"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                store = evidence.ContentAddressedEvidenceStore(directory, clock=lambda: NOW)
                record = store.put(
                    client_id=CLIENT_ID,
                    content=b"synthetic evidence",
                    media_type="text/plain",
                )
                if mode == "missing":
                    store.path_for(client_id=CLIENT_ID, record=record).unlink()
                    candidate = record
                    expected = "missing"
                elif mode == "size":
                    candidate = replace(record, size_bytes=record.size_bytes + 1)
                    expected = "size"
                else:
                    candidate = replace(record, storage_key="forged-key")
                    expected = "canonical"
                with self.assertRaisesRegex(evidence.EvidenceIntegrityError, expected):
                    store.read(client_id=CLIENT_ID, record=candidate)

    def test_invalid_metadata_is_translated_to_integrity_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = evidence.ContentAddressedEvidenceStore(directory, clock=lambda: NOW)
            content = b"synthetic evidence"
            content_hash = hashlib.sha256(content).hexdigest()
            object_path = store._object_path(CLIENT_ID, content_hash)
            metadata_path = object_path.with_suffix(".json")
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(evidence.EvidenceIntegrityError, "metadata"):
                store.put(client_id=CLIENT_ID, content=content, media_type="text/plain")

    def test_event_log_validates_labels_redacts_nested_values_and_skips_blanks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = evidence.HashChainedEventLog(
                Path(directory) / "events.jsonl",
                clock=lambda: NOW,
            )
            self.assertEqual((), log._read_unlocked())
            event_label_cases: tuple[dict[str, Any], ...] = (
                {"event_type": " bad"},
                {"actor_id": ""},
                {"object_id": "bad "},
            )
            for changes in event_label_cases:
                values: dict[str, Any] = {
                    "client_id": CLIENT_ID,
                    "event_type": "synthetic_event",
                    "actor_id": "synthetic-actor",
                    "object_id": "synthetic-object",
                }
                values.update(changes)
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    log.append(**values)

            event = log.append(
                client_id=CLIENT_ID,
                event_type="synthetic_event",
                actor_id="synthetic-actor",
                object_id="synthetic-object",
                details={
                    "nested": [NOW, "x" * 300],
                    "api_token": "synthetic-secret-placeholder",
                },
            )
            self.assertEqual("[redacted]", event.details["api_token"])
            self.assertEqual(NOW.isoformat(), event.details["nested"][0])
            self.assertTrue(event.details["nested"][1].endswith("..."))
            with log.path.open("a", encoding="utf-8") as handle:
                handle.write("\n")
            self.assertEqual(1, len(log.read()))

    def test_event_log_reports_invalid_json_sequence_and_previous_hash_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            invalid_log = evidence.HashChainedEventLog(Path(directory) / "invalid.jsonl")
            invalid_log.path.write_text("{not-json", encoding="utf-8")
            invalid = invalid_log.verify()
            self.assertFalse(invalid.valid)
            self.assertIn("event_log_invalid_json", invalid.errors)

            log = evidence.HashChainedEventLog(
                Path(directory) / "events.jsonl",
                clock=lambda: NOW,
            )
            for index in range(2):
                log.append(
                    client_id=CLIENT_ID,
                    event_type="synthetic_event",
                    actor_id="synthetic-actor",
                    object_id=f"synthetic-object-{index}",
                )
            rows = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
            rows[1]["sequence"] = 99
            rows[1]["previous_hash"] = _digest("forged-previous")
            log.path.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
                encoding="utf-8",
            )
            verification = log.verify()
            self.assertFalse(verification.valid)
            self.assertIn("event_sequence_mismatch:2", verification.errors)
            self.assertIn("event_previous_hash_mismatch:2", verification.errors)


if __name__ == "__main__":
    unittest.main()
