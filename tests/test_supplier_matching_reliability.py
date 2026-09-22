from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from accounting_agent.local_demo import run_supplier_invoice_autopilot_demo
from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.supplier_invoice.rules import SUPPLIERS


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/supplier_invoices/01_normal_25_vat.json"
)


class SupplierMatchingReliabilityTests(unittest.TestCase):
    def process_invoice(self, **fields: object) -> dict:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["mock_extraction"].update(fields)
        with tempfile.TemporaryDirectory() as temp:
            invoice_path = Path(temp) / "synthetic-invoice.json"
            invoice_path.write_text(json.dumps(fixture), encoding="utf-8")
            return SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                entity_id="synthetic-entity",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(invoice_path)

    def assert_requires_review(self, packet: dict) -> None:
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertEqual("blocked_until_human_review", packet["policy_decision"]["decision"])
        self.assertIn("accountant_review", packet["policy_decision"]["required_reviews"])
        self.assertEqual("approval_required", packet["fortnox_draft_payload"]["policy_mode"])
        self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])
        self.assertFalse(packet["fortnox_draft_payload"]["bankgiro_matches_known"])
        self.assertIn("risk_evidence_incomplete", packet["policy_decision"]["canonical_policy_reasons"])

    def test_name_without_organisation_number_is_only_a_review_candidate(self) -> None:
        for org_number in (None, "", "   ", "not extracted"):
            with self.subTest(org_number=org_number):
                packet = self.process_invoice(supplier_org_number=org_number)
                self.assert_requires_review(packet)
                match = packet["supplier_match"]
                self.assertEqual("unknown", match["status"])
                self.assertEqual("SUP-001", match["candidate_supplier_id"])
                self.assertEqual("Nordic Office Supplies AB", match["candidate_name"])
                self.assertIsNone(match["supplier_id"])
                self.assertIsNone(packet["fortnox_draft_payload"]["supplier_id"])
                self.assertEqual("none_until_supplier_created_or_matched", packet["next_action"]["action"])

    def test_name_cannot_override_unknown_or_conflicting_organisation_number(self) -> None:
        for org_number in ("555555-0000", "559900-1122"):
            with self.subTest(org_number=org_number):
                packet = self.process_invoice(supplier_org_number=org_number)
                self.assert_requires_review(packet)
                match = packet["supplier_match"]
                self.assertEqual("identity_conflict", match["match_basis"])
                self.assertIsNone(match["supplier_id"])
                self.assertIsNone(packet["fortnox_draft_payload"]["supplier_id"])
                self.assertEqual("SUP-001", match["candidate_supplier_id"])
                self.assertIn("supplier_identity_conflict", {flag["code"] for flag in packet["risk"]["flags"]})

    def test_missing_invoice_bank_details_are_unknown_and_require_review(self) -> None:
        for bankgiro in (None, "", "   "):
            with self.subTest(bankgiro=bankgiro):
                packet = self.process_invoice(bankgiro=bankgiro)
                self.assert_requires_review(packet)
                self.assertEqual("matched", packet["supplier_match"]["status"])
                self.assertEqual("unknown", packet["supplier_match"]["bank_details_status"])
                self.assertIn("missing_bank_details", {flag["code"] for flag in packet["risk"]["flags"]})
                self.assertEqual("none_until_bank_details_verified", packet["next_action"]["action"])

    def test_missing_registry_bank_details_require_review(self) -> None:
        with patch.dict(SUPPLIERS["5566778899"], {"bankgiro": None}):
            packet = self.process_invoice()
        self.assert_requires_review(packet)
        self.assertEqual("unknown", packet["supplier_match"]["bank_details_status"])
        self.assertEqual("none_until_bank_details_verified", packet["next_action"]["action"])

    def test_normalized_organisation_number_and_bank_details_remain_draft_only(self) -> None:
        packet = self.process_invoice(
            supplier_org_number="556677 8899",
            supplier_name="  NORDIC OFFICE SUPPLIES AB  ",
            bankgiro="123- 4567",
        )
        self.assertEqual("draft_only", packet["policy_decision"]["mode"])
        self.assertEqual("SUP-001", packet["supplier_match"]["supplier_id"])
        self.assertEqual("organisation_number", packet["supplier_match"]["match_basis"])
        self.assertTrue(packet["fortnox_draft_payload"]["bankgiro_matches_known"])
        self.assertEqual([], packet["risk"]["flags"])

    def test_demo_with_missing_bank_details_does_not_issue_an_execution_permit(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["scenario"] = "missing_bank_details"
        fixture["mock_extraction"]["bankgiro"] = None
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixtures = root / "fixtures"
            fixtures.mkdir()
            (fixtures / "invoice.json").write_text(json.dumps(fixture), encoding="utf-8")
            output = root / "demo"
            run_supplier_invoice_autopilot_demo(
                supplier_fixture_dir=fixtures,
                output_dir=output,
            )
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            record = json.loads(
                (output / "fortnox_dry_run_payloads/missing_bank_details.json").read_text(
                    encoding="utf-8"
                )
            )
        self.assertEqual(0, summary["execution_permits_issued"])
        self.assertEqual("not_issued_review_required", record["execution_permit"]["status"])
        self.assertEqual("prepared_but_review_blocked", record["adapter_payload_status"])
        self.assertFalse(record["live_api_call"])


if __name__ == "__main__":
    unittest.main()
