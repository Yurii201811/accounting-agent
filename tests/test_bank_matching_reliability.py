from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from accounting_agent.bank_reconciliation import (
    BankReconciliationPipeline,
    BankTransaction,
    MatchTarget,
    MatchTargetType,
)


class BankMatchingReliabilityTests(unittest.TestCase):
    def transaction(
        self,
        transaction_id: str,
        *,
        amount_minor: int = 10_000,
        reference: str = "INV-1",
    ) -> BankTransaction:
        return BankTransaction(
            transaction_id=transaction_id,
            date=date(2026, 7, 10),
            amount_minor=amount_minor,
            currency="SEK",
            counterparty="Example AB",
            reference=reference,
            bank_account="1930",
            source="synthetic_fixture",
        )

    def target(
        self,
        target_id: str,
        *,
        amount_minor: int = 10_000,
        reference: str = "INV-1",
    ) -> MatchTarget:
        return MatchTarget(
            target_id=target_id,
            target_type=MatchTargetType.CUSTOMER_INVOICE,
            date=date(2026, 7, 10),
            amount_minor=amount_minor,
            remaining_amount_minor=amount_minor,
            currency="SEK",
            counterparty="Example AB",
            reference=reference,
            source="synthetic_fixture",
        )

    def test_exact_top_score_tie_requires_human_selection(self) -> None:
        proposal = BankReconciliationPipeline(output_dir=None).process(
            [self.transaction("TX-1")],
            [self.target("CI-A"), self.target("CI-B")],
        )[0]

        self.assertEqual(["CI-A", "CI-B"], [item["target_id"] for item in proposal["candidates"]])
        self.assertIsNone(proposal["selected_candidate"])
        self.assertIsNone(proposal["selected_target"])
        self.assertEqual("ambiguous_match_review_required", proposal["case"]["status"])
        self.assertTrue(proposal["risk"]["ambiguous_match"])
        self.assertIn(
            "ambiguous_match",
            {flag["code"] for flag in proposal["risk"]["flags"]},
        )
        self.assertEqual("approval_required", proposal["policy_decision"]["mode"])
        self.assertIn("risk_evidence_incomplete", proposal["policy_decision"]["reasons"])
        self.assertIn("approval_packet", proposal)
        self.assertEqual(
            ["CI-A", "CI-B"],
            [item["target_id"] for item in proposal["approval_packet"]["alternatives"]],
        )
        self.assertEqual(
            "none_until_match_selected",
            proposal["reconciliation_payload"]["proposal_action"],
        )
        self.assertIsNone(proposal["reconciliation_payload"]["matched_target"])
        self.assertIn("Choose or reject", proposal["required_human_decision"])

    def test_exact_top_score_tie_is_unresolved_in_either_target_order(self) -> None:
        targets = [self.target("CI-A"), self.target("CI-B")]

        forward = BankReconciliationPipeline(output_dir=None).process(
            [self.transaction("TX-1")],
            targets,
        )[0]
        reversed_order = BankReconciliationPipeline(output_dir=None).process(
            [self.transaction("TX-1")],
            list(reversed(targets)),
        )[0]

        for proposal in (forward, reversed_order):
            self.assertIsNone(proposal["selected_candidate"])
            self.assertEqual("ambiguous_match_review_required", proposal["case"]["status"])
            self.assertEqual(
                {"CI-A", "CI-B"},
                {item["target_id"] for item in proposal["approval_packet"]["alternatives"]},
            )

    def test_unique_top_candidate_remains_selected_above_tied_lower_candidates(self) -> None:
        proposal = BankReconciliationPipeline(output_dir=None).process(
            [self.transaction("TX-1", reference="INV-EXACT")],
            [
                self.target("CI-EXACT", reference="INV-EXACT"),
                self.target("CI-LOW-A", reference="OTHER"),
                self.target("CI-LOW-B", reference="OTHER"),
            ],
        )[0]

        self.assertEqual("CI-EXACT", proposal["selected_candidate"]["target_id"])
        self.assertFalse(proposal["risk"]["ambiguous_match"])
        self.assertEqual("exact_match_proposed", proposal["case"]["status"])

    def test_approval_packet_retains_every_tied_top_candidate(self) -> None:
        targets = [self.target(f"CI-{index}") for index in range(6)]

        proposal = BankReconciliationPipeline(output_dir=None).process(
            [self.transaction("TX-1")],
            targets,
        )[0]

        self.assertEqual(6, len(proposal["approval_packet"]["alternatives"]))
        self.assertEqual(
            {target.target_id for target in targets},
            {
                candidate["target_id"]
                for candidate in proposal["approval_packet"]["alternatives"]
            },
        )

    def test_duplicate_transaction_identifier_fails_before_packet_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "packets"
            pipeline = BankReconciliationPipeline(output_dir=output_dir)

            with self.assertRaisesRegex(
                ValueError,
                "Duplicate bank transaction identifiers: TX-DUP",
            ):
                pipeline.process(
                    [
                        self.transaction("TX-DUP", amount_minor=10_000, reference="INV-1"),
                        self.transaction("TX-DUP", amount_minor=20_000, reference="INV-2"),
                    ],
                    [
                        self.target("CI-1", amount_minor=10_000, reference="INV-1"),
                        self.target("CI-2", amount_minor=20_000, reference="INV-2"),
                    ],
                )

            self.assertFalse(output_dir.exists())

    def test_empty_transaction_identifier_fails_before_packet_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "packets"
            pipeline = BankReconciliationPipeline(output_dir=output_dir)

            with self.assertRaisesRegex(
                ValueError,
                "Bank transaction identifiers must be non-empty",
            ):
                pipeline.process([self.transaction("  ")], [self.target("CI-1")])

            self.assertFalse(output_dir.exists())

    def test_packet_filename_collision_fails_before_packet_output(self) -> None:
        for transaction_ids in (("TX/A", "TX?A"), ("TX-A", "tx-a")):
            with self.subTest(transaction_ids=transaction_ids), tempfile.TemporaryDirectory() as temp:
                output_dir = Path(temp) / "packets"
                pipeline = BankReconciliationPipeline(output_dir=output_dir)

                with self.assertRaisesRegex(
                    ValueError,
                    "Bank transaction identifiers produce duplicate packet filenames",
                ):
                    pipeline.process(
                        [self.transaction(item) for item in transaction_ids],
                        [self.target("CI-1")],
                    )

                self.assertFalse(output_dir.exists())

    def test_open_item_identifiers_must_be_nonempty_and_unique(self) -> None:
        pipeline = BankReconciliationPipeline(output_dir=None)

        with self.assertRaisesRegex(ValueError, "Open item identifiers must be non-empty"):
            pipeline.process([self.transaction("TX-1")], [self.target("")])

        with self.assertRaisesRegex(ValueError, "Duplicate open item identifiers: CI-DUP"):
            pipeline.process(
                [self.transaction("TX-1")],
                [self.target("CI-DUP"), self.target("CI-DUP")],
            )


if __name__ == "__main__":
    unittest.main()
