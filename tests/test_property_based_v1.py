from __future__ import annotations

import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hypothesis import given, settings, strategies as st

from accounting_agent.accounting.money import Money
from accounting_agent.client_identity import client_id_from_storage_key, client_storage_key
from accounting_agent.approvals import (
    ApprovalBinding,
    ApprovalRequest,
    ReviewerRole,
    SQLiteApprovalStore,
)
from accounting_agent.connector_contract import PaginationContract, PaginationMode, RetryMetadata
from accounting_agent.ledger import (
    JournalDraft,
    JournalLine,
    JournalValidationPolicy,
)
from accounting_agent.policy import (
    ActionType,
    PermissionMode,
    PolicyContext,
    evaluate_policy,
)
from accounting_agent.permits import PermitIssuer, PermitValidationError, PermitValidator


PROPERTY_SETTINGS = settings(max_examples=100, derandomize=True, deadline=None)
MODE_SEVERITY = {
    PermissionMode.AUTO_ALLOWED: 0,
    PermissionMode.DRAFT_ONLY: 1,
    PermissionMode.APPROVAL_REQUIRED: 2,
    PermissionMode.ESCALATION_REQUIRED: 3,
    PermissionMode.FORBIDDEN: 4,
}
CURRENCIES = st.sampled_from(("SEK", "EUR", "USD", "JPY", "KWD", "BHD"))
CLIENT_IDS = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Lt", "Lo", "Nd")),
    min_size=1,
    max_size=30,
)
NOW = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PropertyBasedAccountingTests(unittest.TestCase):
    @PROPERTY_SETTINGS
    @given(minor=st.integers(min_value=-(10**12), max_value=10**12), currency=CURRENCIES)
    def test_money_major_minor_round_trip_respects_registered_precision(
        self,
        minor: int,
        currency: str,
    ) -> None:
        money = Money(minor, currency)
        self.assertEqual(money, Money.from_major(money.major, currency))

    @PROPERTY_SETTINGS
    @given(client_id=CLIENT_IDS)
    def test_client_storage_key_round_trip_is_reversible_and_path_safe(
        self,
        client_id: str,
    ) -> None:
        storage_key = client_storage_key(client_id)
        self.assertEqual(client_id, client_id_from_storage_key(storage_key))
        self.assertRegex(storage_key, r"^v1-[a-z2-7]+$")
        self.assertNotIn("/", storage_key)
        self.assertNotIn("\\", storage_key)

    @PROPERTY_SETTINGS
    @given(
        first=st.integers(min_value=0, max_value=200_000_00),
        second=st.integers(min_value=0, max_value=200_000_00),
    )
    def test_supplier_draft_policy_never_becomes_less_strict_as_amount_increases(
        self,
        first: int,
        second: int,
    ) -> None:
        low, high = sorted((first, second))
        common = {
            "action_type": ActionType.DRAFT_SUPPLIER_INVOICE,
            "client_id": "synthetic-client",
            "currency_code": "SEK",
            "risk_evidence_complete": True,
        }
        low_decision = evaluate_policy(PolicyContext(amount_minor=low, **common))
        high_decision = evaluate_policy(PolicyContext(amount_minor=high, **common))
        self.assertGreaterEqual(
            MODE_SEVERITY[high_decision.permission_mode],
            MODE_SEVERITY[low_decision.permission_mode],
        )

    @PROPERTY_SETTINGS
    @given(amount_minor=st.integers(min_value=1, max_value=10**10))
    def test_balanced_two_line_journal_remains_balanced_for_any_positive_amount(
        self,
        amount_minor: int,
    ) -> None:
        digest = "a" * 64
        draft = JournalDraft(
            journal_id="property-balanced",
            client_id="synthetic-client",
            entity_id="synthetic-entity",
            posting_date="2026-07-11",
            description="Synthetic property-based journal",
            source_document_hash=digest,
            lines=(
                JournalLine(
                    account="4010",
                    description="Debit",
                    debit=Money(amount_minor, "SEK"),
                    evidence_hashes=(digest,),
                ),
                JournalLine(
                    account="2440",
                    description="Credit",
                    credit=Money(amount_minor, "SEK"),
                    evidence_hashes=(digest,),
                ),
            ),
        )
        validation = draft.validate(
            JournalValidationPolicy(
                chart_id="bas-2026",
                allowed_accounts=frozenset({"4010", "2440"}),
            )
        )

        self.assertTrue(validation.is_valid, validation.error_codes)
        self.assertEqual(validation.debit_total, validation.credit_total)

    @PROPERTY_SETTINGS
    @given(
        max_page_size=st.integers(min_value=1, max_value=10_000),
        attempt=st.integers(min_value=1, max_value=50),
        remaining_attempts=st.integers(min_value=0, max_value=50),
        transient=st.booleans(),
        retry_after=st.one_of(st.none(), st.floats(min_value=0, max_value=3_600)),
    )
    def test_pagination_and_retry_metadata_round_trip_without_losing_bounds(
        self,
        max_page_size: int,
        attempt: int,
        remaining_attempts: int,
        transient: bool,
        retry_after: float | None,
    ) -> None:
        pagination = PaginationContract(
            PaginationMode.CURSOR,
            cursor_parameter="cursor",
            next_cursor_field="next_cursor",
            max_page_size=max_page_size,
        )
        retry = RetryMetadata(
            attempt_number=attempt,
            max_attempts=attempt + remaining_attempts,
            transient=transient,
            retry_after_seconds=retry_after,
        )

        self.assertEqual(max_page_size, pagination.to_dict()["max_page_size"])
        self.assertTrue(pagination.uses_cursor)
        self.assertLessEqual(retry.attempt_number, retry.max_attempts)
        self.assertEqual(retry_after, retry.retry_after_seconds)

    @settings(max_examples=30, derandomize=True, deadline=None)
    @given(mutated_hash=st.binary(min_size=1, max_size=64).map(lambda value: hashlib.sha256(value).hexdigest()))
    def test_approval_scope_mutation_invalidates_the_immutable_request(
        self,
        mutated_hash: str,
    ) -> None:
        original_hash = digest("original proposal")
        if mutated_hash == original_hash:
            return
        binding = ApprovalBinding(
            client_id="synthetic-client",
            entity_id="synthetic-entity",
            case_id="property-case",
            proposal_hash=original_hash,
            evidence_hashes=(digest("synthetic evidence"),),
            policy_hash=digest("synthetic policy"),
            provider_id="synthetic-provider",
            environment="test",
        )
        request = ApprovalRequest(
            request_id="property-approval",
            binding=binding,
            action="draft_supplier_invoice",
            requestor_id="property-requestor",
            required_roles=(ReviewerRole.REVIEWER,),
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteApprovalStore(Path(directory) / "approvals.sqlite")
            store.create_request(request)
            changed = replace(
                request,
                binding=replace(binding, proposal_hash=mutated_hash),
            )
            verification = store.verify(changed, now=NOW)

        self.assertFalse(verification.valid)
        self.assertIn("approval_request_mismatch", verification.errors)

    @PROPERTY_SETTINGS
    @given(
        changed_memo=st.text(min_size=1, max_size=80).filter(lambda value: value != "original")
    )
    def test_permit_payload_mutation_never_preserves_execution_authority(
        self,
        changed_memo: str,
    ) -> None:
        context = PolicyContext(
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            client_id="synthetic-client",
            currency_code="SEK",
            amount_minor=100,
            risk_evidence_complete=True,
        )
        decision = evaluate_policy(context)
        payload = {"amount_minor": 100, "memo": "original"}
        permit = PermitIssuer(
            clock=lambda: NOW,
            id_factory=lambda: "property-permit",
        ).issue(
            decision=decision,
            context=context,
            case_id="property-case",
            entity_id="synthetic-entity",
            payload=payload,
        )
        validator = PermitValidator(
            accepted_policy_version=decision.policy_version,
            clock=lambda: NOW,
        )
        validator.require_valid(
            permit=permit,
            case_id="property-case",
            entity_id="synthetic-entity",
            action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
            payload=payload,
        )

        with self.assertRaisesRegex(PermitValidationError, "payload hash"):
            validator.require_valid(
                permit=permit,
                case_id="property-case",
                entity_id="synthetic-entity",
                action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
                payload={"amount_minor": 100, "memo": changed_memo},
            )


if __name__ == "__main__":
    unittest.main()
