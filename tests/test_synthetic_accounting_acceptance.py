"""Invented cases inspired by upstream accounting validation workflows.

See docs/review_workflow_checkpoint.md for the primary-source references.
No upstream financial records or datasets are copied here.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from accounting_agent.bank_reconciliation import (
    BankReconciliationPipeline, BankTransaction, MatchTarget, MatchTargetType,
)
from accounting_agent.supplier_invoice import SupplierInvoicePipeline


class SyntheticAccountingAcceptanceTests(unittest.TestCase):
    def test_similar_payments_are_retained_and_source_replay_preserves_prior_packets(self) -> None:
        payment = BankTransaction(
            transaction_id="SRC-9001", date=date(2026, 5, 10),
            amount_minor=-64_000, currency="SEK", counterparty="Fiktiv Resepartner AB",
            reference="TRAVEL-77", bank_account="1930", source="synthetic_acceptance",
        )
        invoice = MatchTarget(
            target_id="TRAVEL-77", target_type=MatchTargetType.SUPPLIER_INVOICE,
            date=payment.date, amount_minor=payment.amount_minor, currency="SEK",
            counterparty=payment.counterparty, reference=payment.reference,
            source="synthetic_acceptance",
        )
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "packets"
            pipeline = BankReconciliationPipeline(output_dir=output)
            proposals = pipeline.process(
                [payment, replace(payment, transaction_id="SRC-9002")], [invoice],
            )
            self.assertEqual(
                {"SRC-9001", "SRC-9002"},
                {proposal["transaction"]["transaction_id"] for proposal in proposals},
            )
            self.assertEqual(2, len(list(output.glob("*.json"))))
            for proposal in proposals:
                self.assertEqual("approval_required", proposal["policy_decision"]["mode"])
                self.assertIn("duplicate_looking_transaction", {flag["code"] for flag in proposal["risk"]["flags"]})
                self.assertFalse(proposal["reconciliation_payload"]["reconciles_in_fortnox"])
            before = {path.name: path.read_bytes() for path in output.glob("*.json")}
            with self.assertRaisesRegex(ValueError, "Duplicate bank transaction identifiers"):
                pipeline.process([payment, payment], [invoice])
            self.assertEqual(before, {path.name: path.read_bytes() for path in output.glob("*.json")})

    def test_invalid_and_unbalanced_amounts_require_correction_before_a_draft(self) -> None:
        fixture_path = Path(__file__).resolve().parents[1] / "fixtures/supplier_invoices/01_normal_25_vat.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for gross, expected in (("NaN", "forbidden"), ("Infinity", "forbidden"), ("1240.00", "forbidden"), ("1250.00", "draft_only")):
                with self.subTest(gross=gross):
                    fixture["mock_extraction"]["amounts"]["gross"] = gross
                    path = root / "synthetic-invoice.json"
                    path.write_text(json.dumps(fixture), encoding="utf-8")
                    # Each independent assessment uses a fresh in-memory pipeline.
                    packet = SupplierInvoicePipeline(
                        db_path=None, output_dir=None, entity_id="synthetic-acceptance",
                        evaluation_date=date(2026, 5, 16),
                    ).process_fixture(path)
                    self.assertEqual(expected, packet["policy_decision"]["mode"])
                    self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])
                    self.assertTrue(packet["fortnox_draft_payload"]["blocked_from_live_use"])
                    if expected == "forbidden":
                        self.assertEqual("none_until_journal_corrected", packet["next_action"]["action"])


if __name__ == "__main__":
    unittest.main()
