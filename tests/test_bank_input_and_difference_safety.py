from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from accounting_agent.bank_reconciliation import (
    BankReconciliationPipeline,
    BankTransaction,
    MatchTarget,
    MatchTargetType,
)


class BankInputAndDifferenceSafetyTests(unittest.TestCase):
    def transaction(
        self,
        amount_minor: int,
        *,
        currency: str = "SEK",
        transaction_id: str = "TX-1",
    ) -> BankTransaction:
        return BankTransaction(
            transaction_id=transaction_id,
            date=date(2026, 7, 10),
            amount_minor=amount_minor,
            currency=currency,
            counterparty="Example AB",
            reference="INV-1",
            bank_account="1930",
            source="synthetic_fixture",
        )

    def target(
        self,
        amount_minor: int,
        *,
        currency: str = "SEK",
    ) -> MatchTarget:
        target_type = (
            MatchTargetType.CUSTOMER_INVOICE
            if amount_minor > 0
            else MatchTargetType.SUPPLIER_INVOICE
        )
        return MatchTarget(
            target_id="ITEM-1",
            target_type=target_type,
            date=date(2026, 7, 10),
            amount_minor=amount_minor,
            remaining_amount_minor=amount_minor,
            currency=currency,
            counterparty="Example AB",
            reference="INV-1",
            source="synthetic_fixture",
        )

    def test_transaction_currency_must_be_explicit_and_supported(self) -> None:
        for currency in (None, "", "   ", "ZZZ"):
            with self.subTest(currency=currency), self.assertRaises(ValueError):
                self.transaction(10_000, currency=currency)  # type: ignore[arg-type]

        data = {
            "transaction_id": "TX-1",
            "date": "2026-07-10",
            "amount_minor": 10_000,
            "counterparty": "Example AB",
            "reference": "INV-1",
            "bank_account": "1930",
            "source": "synthetic_fixture",
        }
        with self.assertRaisesRegex(ValueError, "currency must be explicitly provided"):
            BankTransaction.from_dict(data)

    def test_target_currency_must_be_explicit_and_supported(self) -> None:
        for currency in (None, "", "   ", "ZZZ"):
            with self.subTest(currency=currency), self.assertRaises(ValueError):
                self.target(10_000, currency=currency)  # type: ignore[arg-type]

        data = {
            "target_id": "ITEM-1",
            "target_type": "customer_invoice",
            "date": "2026-07-10",
            "amount_minor": 10_000,
            "remaining_amount_minor": 10_000,
            "counterparty": "Example AB",
            "reference": "INV-1",
            "source": "synthetic_fixture",
        }
        with self.assertRaisesRegex(ValueError, "currency must be explicitly provided"):
            MatchTarget.from_dict(data)

    def test_supplied_lowercase_currency_is_canonicalized(self) -> None:
        transaction = self.transaction(10_000, currency=" sek ")
        target = self.target(10_000, currency="sek")

        self.assertEqual("SEK", transaction.currency)
        self.assertEqual("SEK", target.currency)
        proposal = BankReconciliationPipeline(output_dir=None).process(
            [transaction],
            [target],
        )[0]
        self.assertEqual("exact_match_proposed", proposal["case"]["status"])

    def test_one_minor_unit_overpayment_requires_review_for_both_directions(self) -> None:
        for open_amount, transaction_amount, expected_residual in (
            (10_000, 10_001, -1),
            (-10_000, -10_001, 1),
        ):
            with self.subTest(open_amount=open_amount):
                proposal = BankReconciliationPipeline(output_dir=None).process(
                    [self.transaction(transaction_amount)],
                    [self.target(open_amount)],
                )[0]

                self.assertEqual(
                    "small_amount_delta",
                    proposal["selected_candidate"]["flags"][0],
                )
                self.assertEqual("candidate_match_review_required", proposal["case"]["status"])
                self.assertEqual("approval_required", proposal["policy_decision"]["mode"])
                self.assertIn(
                    "risk_evidence_incomplete",
                    proposal["policy_decision"]["reasons"],
                )
                self.assertIn("approval_packet", proposal)
                self.assertEqual(
                    expected_residual,
                    proposal["reconciliation_payload"]["residual_amount_minor"],
                )

    def test_exact_signed_matches_remain_local_drafts(self) -> None:
        for amount_minor in (10_000, -10_000):
            with self.subTest(amount_minor=amount_minor):
                proposal = BankReconciliationPipeline(output_dir=None).process(
                    [self.transaction(amount_minor)],
                    [self.target(amount_minor)],
                )[0]

                self.assertEqual("exact_match_proposed", proposal["case"]["status"])
                self.assertEqual("draft_only", proposal["policy_decision"]["mode"])
                self.assertNotIn("approval_packet", proposal)
                self.assertEqual(
                    0,
                    proposal["reconciliation_payload"]["residual_amount_minor"],
                )

    def test_date_distance_only_exact_match_remains_local_draft(self) -> None:
        distant_target = replace(
            self.target(-100_000),
            date=date(2026, 6, 1),
        )

        proposal = BankReconciliationPipeline(output_dir=None).process(
            [self.transaction(-100_000)],
            [distant_target],
        )[0]

        self.assertEqual(["date_distance"], proposal["selected_candidate"]["flags"])
        self.assertEqual(0.95, proposal["confidence"])
        self.assertEqual("exact_match_proposed", proposal["case"]["status"])
        self.assertEqual("draft_only", proposal["policy_decision"]["mode"])
        self.assertNotIn("risk_evidence_incomplete", proposal["policy_decision"]["reasons"])
        self.assertNotIn("approval_packet", proposal)

    def test_residual_is_not_computed_for_incompatible_amounts(self) -> None:
        cases = (
            (
                self.transaction(10_000, currency="EUR"),
                self.target(10_000),
                "escalation_required",
            ),
            (self.transaction(-10_000), self.target(10_000), "approval_required"),
            (self.transaction(0), self.target(10_000), "approval_required"),
        )
        for transaction, target, expected_mode in cases:
            with self.subTest(
                transaction_currency=transaction.currency,
                transaction_amount=transaction.amount_minor,
            ):
                proposal = BankReconciliationPipeline(output_dir=None).process(
                    [transaction],
                    [target],
                )[0]

                self.assertIsNotNone(proposal["selected_candidate"])
                self.assertIsNone(
                    proposal["reconciliation_payload"]["residual_amount_minor"]
                )
                self.assertEqual(expected_mode, proposal["policy_decision"]["mode"])


if __name__ == "__main__":
    unittest.main()
