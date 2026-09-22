from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.supplier_invoice.extraction import as_decimal, extract_invoice_fields, money


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "supplier_invoices" / "01_normal_25_vat.json"


class InvoiceNumericQualityTests(unittest.TestCase):
    def test_non_finite_decimals_are_rejected(self) -> None:
        for value in (
            "NaN",
            "sNaN",
            "Infinity",
            "-Infinity",
            Decimal("NaN"),
            float("nan"),
            float("inf"),
        ):
            with self.subTest(value=value):
                self.assertIsNone(as_decimal(value))
                self.assertIsNone(money(value))

    def test_unquantizable_amount_is_treated_as_missing(self) -> None:
        self.assertIsNotNone(as_decimal("1e999999"))
        self.assertIsNone(money("1e999999"))

    def test_malformed_and_non_finite_vat_rates_normalize_to_missing(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for vat_rate in ("not-a-rate", "NaN", "Infinity", "-Infinity"):
            with self.subTest(vat_rate=vat_rate):
                fixture["mock_extraction"]["vat_rate"] = vat_rate
                self.assertIsNone(extract_invoice_fields(fixture)["vat_rate"])

    def test_invalid_amounts_and_vat_rate_normalize_to_missing(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["mock_extraction"]["amounts"] = {
            "net": "NaN",
            "vat": "Infinity",
            "gross": "1e999999",
        }
        fixture["mock_extraction"]["vat_rate"] = "-Infinity"

        extracted = extract_invoice_fields(fixture)

        self.assertEqual({"net": None, "vat": None, "gross": None}, extracted["amounts"])
        self.assertIsNone(extracted["vat_rate"])
        self.assertEqual(
            ["amounts.net", "amounts.vat", "amounts.gross"],
            extracted["missing_required_fields"],
        )

    def test_invalid_amounts_block_for_correction_without_crashing(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["scenario"] = "invalid_amount_values"
        fixture["mock_extraction"]["amounts"] = {
            "net": "not-a-number",
            "vat": "NaN",
            "gross": "Infinity",
        }

        with tempfile.TemporaryDirectory() as temp:
            fixture_path = Path(temp) / "invalid-numerics.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            packet = SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                entity_id="synthetic-entity",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture_path)

        self.assertEqual(
            {"net": None, "vat": None, "gross": None},
            packet["extracted_fields"]["amounts"],
        )
        self.assertEqual("manual_review", packet["vat_proposal"]["status"])
        self.assertEqual("forbidden", packet["policy_decision"]["mode"])
        self.assertEqual("blocked_by_journal_validation", packet["policy_decision"]["decision"])
        self.assertEqual("none_until_journal_corrected", packet["next_action"]["action"])
        self.assertIn("Correct the journal", packet["required_human_decision"])
        flag_codes = {flag["code"] for flag in packet["risk"]["flags"]}
        self.assertIn("missing_required_fields", flag_codes)
        self.assertTrue(packet["fortnox_draft_payload"]["blocked_from_live_use"])
        self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])

    def test_invalid_vat_rate_requires_review_without_crashing(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        fixture["scenario"] = "invalid_vat_rate"
        fixture["mock_extraction"]["vat_rate"] = "sNaN"

        with tempfile.TemporaryDirectory() as temp:
            fixture_path = Path(temp) / "invalid-rate.json"
            fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
            packet = SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                entity_id="synthetic-entity",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture_path)

        self.assertIsNone(packet["extracted_fields"]["vat_rate"])
        self.assertEqual("manual_review", packet["vat_proposal"]["status"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertEqual("blocked_until_human_review", packet["policy_decision"]["decision"])
        self.assertEqual("none_until_extraction_and_vat_reviewed", packet["next_action"]["action"])
        flag_codes = {flag["code"] for flag in packet["risk"]["flags"]}
        self.assertIn("unsupported_or_missing_vat_rate", flag_codes)
        self.assertTrue(packet["fortnox_draft_payload"]["blocked_from_live_use"])
        self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])


if __name__ == "__main__":
    unittest.main()
