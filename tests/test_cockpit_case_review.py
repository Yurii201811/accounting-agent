from __future__ import annotations

import json
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
from accounting_agent.operations_cockpit import (
    OperationsCockpitData,
    _build_review_queues,
    _collect_review_items,
    _prioritized_review_items,
    render_operations_cockpit,
)
from accounting_agent.supplier_invoice import SupplierInvoicePipeline


ROOT = Path(__file__).resolve().parents[1]
SUPPLIER_FIXTURE = ROOT / "fixtures" / "supplier_invoices" / "01_normal_25_vat.json"


class CockpitCaseReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temp.cleanup)
        cls.repo_root = Path(cls._temp.name).resolve()
        cls.evidence_dir = cls.repo_root / "evidence"
        cls.evidence_dir.mkdir()

        missing_bank = cls._supplier_case(
            "missing_bank_details",
            supplier_name='Företag Å & <Test> "AB"',
            invoice_number="INV-Å&<42>",
            bankgiro=None,
        )
        identity_conflict = cls._supplier_case(
            "supplier_identity_conflict",
            supplier_name="Nordic Office Supplies AB",
            supplier_org_number="559900-1122",
            bankgiro="987-6543",
        )
        invalid_amount = cls._supplier_case(
            "invalid_amount",
            amounts={"net": "1000.00", "vat": "250.00", "gross": "NaN"},
        )
        senior_vat = cls._supplier_case(
            "senior_vat_and_missing_evidence",
            bankgiro="000-0000",
            vat_rate="17",
        )
        senior_vat["summary"]["fortnox_adapter_payload_status"] = "not_prepared"
        cls.supplier_cases = [
            missing_bank,
            identity_conflict,
            invalid_amount,
            senior_vat,
        ]
        cls.missing_bank_id = missing_bank["summary"]["case_id"]
        cls.identity_conflict_id = identity_conflict["summary"]["case_id"]
        cls.invalid_amount_id = invalid_amount["summary"]["case_id"]
        cls.senior_vat_id = senior_vat["summary"]["case_id"]

        transaction = BankTransaction(
            transaction_id="TX-TIED-6",
            date=date(2026, 7, 10),
            amount_minor=1_234_567,
            currency="SEK",
            counterparty="Betalare Ö & <Kund>",
            reference="PAY-Å&<6>",
            bank_account="1930",
            source="synthetic_fixture",
        )
        targets = [
            MatchTarget(
                target_id=f"CI-TIED-{index}",
                target_type=MatchTargetType.CUSTOMER_INVOICE,
                date=date(2026, 7, 10),
                amount_minor=1_234_567,
                remaining_amount_minor=1_234_567,
                currency="SEK",
                counterparty="Betalare Ö & <Kund>",
                reference="PAY-Å&<6>",
                source="synthetic_fixture",
            )
            for index in range(1, 7)
        ]
        cls.bank_proposal = BankReconciliationPipeline(
            output_dir=cls.evidence_dir / "bank"
        ).process([transaction], targets)[0]
        cls.bank_case_id = cls.bank_proposal["case"]["case_id"]

        review_items = _collect_review_items(
            supplier_cases=cls.supplier_cases,
            bank_proposals=[cls.bank_proposal],
            fake_manifest={},
            root=cls.repo_root,
        )
        cls.review_queues = _build_review_queues(review_items)
        cls.prioritized = _prioritized_review_items(cls.review_queues)
        cls.items_by_id = {item.item_id: item for item in cls.prioritized}
        data = OperationsCockpitData(
            generated_at="2026-09-22T10:00:00+00:00",
            repo_root=str(cls.repo_root),
            output_path=str(cls.repo_root / "reports" / "operations_cockpit" / "index.html"),
            last_run="2026-09-22T09:55:00+00:00",
            local_readiness="local_fake_client_dry_run_complete",
            demo_readiness="local_demo_complete",
            live_counters={},
            queue_counts={},
            workflow=(),
            review_queues=cls.review_queues,
            artifacts=(),
        )
        cls.html = render_operations_cockpit(data)

    @classmethod
    def _supplier_case(cls, scenario: str, **updates: object) -> dict:
        fixture = json.loads(SUPPLIER_FIXTURE.read_text(encoding="utf-8"))
        fixture["scenario"] = scenario
        fixture["mock_extraction"].update(updates)
        fixture_path = cls.repo_root / "fixtures" / f"{scenario}.json"
        fixture_path.parent.mkdir(exist_ok=True)
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
        packet = SupplierInvoicePipeline(
            db_path=None,
            output_dir=None,
            entity_id="synthetic-cockpit-entity",
            evaluation_date=date(2026, 5, 16),
        ).process_fixture(fixture_path)
        packet_path = cls.evidence_dir / f"{scenario}.approval_packet.json"
        packet_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "summary": {
                "case_id": packet["case"]["case_id"],
                "scenario": scenario,
                "execution_gate_mode": packet["policy_decision"]["mode"],
            },
            "packet": packet,
            "packet_path": packet_path,
        }

    def test_supplier_context_survives_category_dedup_and_is_escaped(self) -> None:
        item = self.items_by_id[self.missing_bank_id]

        self.assertEqual(
            ("Approval required", "Missing bank details"),
            item.categories,
        )
        self.assertIsNotNone(item.context)
        assert item.context is not None
        self.assertEqual('Företag Å & <Test> "AB"', item.context.party)
        self.assertEqual("INV-Å&<42>", item.context.reference)
        self.assertEqual("1,250.00 SEK", item.context.amount)
        self.assertEqual(1, sum(entry.item_id == self.missing_bank_id for entry in self.prioritized))

        row = _review_row(self.html, self.missing_bank_id)
        self.assertIn(
            'class="review-party">Företag Å &amp; &lt;Test&gt; &quot;AB&quot;</p>',
            row,
        )
        self.assertIn("INV-Å&amp;&lt;42&gt;", row)
        self.assertNotIn("<Test>", row)
        self.assertNotIn("INV-Å&<42>", row)

    def test_supplier_review_reasons_are_explicit_in_both_languages(self) -> None:
        missing_row = _review_row(self.html, self.missing_bank_id)
        identity_row = _review_row(self.html, self.identity_conflict_id)

        self.assertIn(
            "Supply and verify payment details on both the invoice and supplier record.",
            missing_row,
        )
        self.assertIn(
            "Komplettera och verifiera betalningsuppgifterna på fakturan och i leverantörsregistret.",
            missing_row,
        )
        self.assertIn(
            "Check the organisation number against the supplier registry. A matching name is not enough.",
            identity_row,
        )
        self.assertIn(
            "Kontrollera organisationsnummer och leverantörsregister. Ett matchande namn räcker inte.",
            identity_row,
        )

    def test_tied_bank_match_keeps_all_candidates_and_remains_read_only(self) -> None:
        self.assertIsNone(self.bank_proposal["selected_candidate"])
        self.assertIsNone(self.bank_proposal["selected_target"])
        self.assertIsNone(self.bank_proposal["reconciliation_payload"]["matched_target"])

        item = self.items_by_id[self.bank_case_id]
        self.assertIsNotNone(item.context)
        assert item.context is not None
        self.assertEqual(6, len(item.context.candidates))
        self.assertEqual(
            {f"CI-TIED-{index}" for index in range(1, 7)},
            {reference for reference, _score in item.context.candidates},
        )

        row = _review_row(self.html, self.bank_case_id)
        self.assertIn('class="case-review-details"', row)
        self.assertIn("Tied candidates · none selected", row)
        self.assertIn(
            "Read-only review. Opening this case does not approve it or change its status.",
            row,
        )
        for index in range(1, 7):
            self.assertIn(f"CI-TIED-{index}", row)
        self.assertEqual(6, row.count("<tr><td>CI-TIED-"))
        self.assertEqual(6, row.count("<td>99%</td>"))

    def test_evidence_link_is_available_in_guided_case_review(self) -> None:
        row = _review_row(self.html, self.missing_bank_id)
        action_start = row.index('<div class="attention-action">')
        action = row[action_start : row.index("</div>", action_start)]

        self.assertIn("Open evidence", action)
        self.assertIn("Öppna underlag", action)
        self.assertIn("href=", action)
        self.assertNotIn("expert-only", action)

    def test_senior_instruction_survives_specific_vat_and_evidence_checks(self) -> None:
        item = self.items_by_id[self.senior_vat_id]
        self.assertEqual("escalation_required", item.mode)
        self.assertIn("Uncertain VAT", item.categories)
        self.assertIn("Missing info", item.categories)

        row = _review_row(self.html, self.senior_vat_id)
        self.assertIn("A senior accountant must review this case.", row)
        self.assertIn("En senior redovisningskunnig person måste granska ärendet.", row)
        self.assertIn(
            "An accountant must confirm the VAT treatment and supporting evidence.",
            row,
        )
        self.assertIn(
            "Supply or verify the missing evidence before continuing.",
            row,
        )

    def test_invalid_amounts_stay_blank_and_source_counts_use_unique_cases(self) -> None:
        invalid_item = self.items_by_id[self.invalid_amount_id]
        self.assertIsNotNone(invalid_item.context)
        assert invalid_item.context is not None
        self.assertEqual("", invalid_item.context.amount)
        invalid_row = _review_row(self.html, self.invalid_amount_id)
        self.assertNotIn('class="review-amount"', invalid_row)
        self.assertEqual(
            "Missing or invalid",
            next(fact.value for fact in invalid_item.context.facts if fact.label == "Invoice total"),
        )
        self.assertNotIn("NaN", invalid_row)

        self.assertEqual(5, len(self.prioritized))
        self.assertIn(
            'data-review-source="all" aria-pressed="true" aria-controls="attention-list review-empty"><span data-i18n data-en="All work" data-sv="Alla ärenden">All work</span><span class="source-count">5</span>',
            self.html,
        )
        self.assertIn(
            'data-review-source="supplier" aria-pressed="false" aria-controls="attention-list review-empty"><span data-i18n data-en="Supplier invoices" data-sv="Leverantörsfakturor">Supplier invoices</span><span class="source-count">4</span>',
            self.html,
        )
        self.assertIn(
            'data-review-source="bank" aria-pressed="false" aria-controls="attention-list review-empty"><span data-i18n data-en="Bank transactions" data-sv="Banktransaktioner">Bank transactions</span><span class="source-count">1</span>',
            self.html,
        )
        self.assertNotIn('data-review-source="other"', self.html)


def _review_row(markup: str, case_id: str) -> str:
    case_at = markup.index(case_id)
    row_start = markup.rfind('<li class="attention-row"', 0, case_at)
    if row_start < 0:
        raise AssertionError(f"Review row not found for {case_id}")
    next_row = markup.find('<li class="attention-row"', case_at + len(case_id))
    list_end = markup.index("</ol>", case_at)
    row_end = min(end for end in (next_row, list_end) if end >= 0)
    return markup[row_start:row_end]


if __name__ == "__main__":
    unittest.main()
