from __future__ import annotations

import html
import json
import re
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
    ReviewFact,
    _build_review_queues,
    _collect_review_items,
    _prioritized_review_items,
    render_operations_cockpit,
)
from accounting_agent.supplier_invoice import SupplierInvoicePipeline


ROOT = Path(__file__).resolve().parents[1]
SUPPLIER_FIXTURE = ROOT / "fixtures" / "supplier_invoices" / "01_normal_25_vat.json"


class CockpitAmountEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temp.cleanup)
        cls.repo_root = Path(cls._temp.name).resolve()
        cls.evidence_dir = cls.repo_root / "evidence"
        cls.evidence_dir.mkdir()

        cls.supplier_case = cls._invalid_supplier_case()
        cls.supplier_case_id = cls.supplier_case["summary"]["case_id"]
        cls.bank_proposals = {
            "partial_inflow": cls._bank_case(
                "partial-inflow",
                transaction_amount=40_000,
                target_amount=100_000,
                target_type=MatchTargetType.CUSTOMER_INVOICE,
                reference="INV-Ö & <Partial>",
            ),
            "partial_outflow": cls._bank_case(
                "partial-outflow",
                transaction_amount=-40_000,
                target_amount=-100_000,
                target_type=MatchTargetType.SUPPLIER_INVOICE,
                reference="SUP-OUT-1",
            ),
            "overpayment": cls._bank_case(
                "overpayment",
                transaction_amount=125_000,
                target_amount=100_000,
                target_type=MatchTargetType.CUSTOMER_INVOICE,
                reference="INV-OVER-1",
            ),
            "currency_mismatch": cls._bank_case(
                "currency-mismatch",
                transaction_amount=100_000,
                transaction_currency="SEK",
                target_amount=100_000,
                target_currency="EUR",
                target_type=MatchTargetType.CUSTOMER_INVOICE,
                reference="INV-CURRENCY-1",
            ),
            "direction_mismatch": cls._bank_case(
                "direction-mismatch",
                transaction_amount=100_000,
                target_amount=-100_000,
                target_type=MatchTargetType.SUPPLIER_INVOICE,
                reference="SUP-DIRECTION-1",
            ),
        }

        review_items = _collect_review_items(
            supplier_cases=[cls.supplier_case],
            bank_proposals=list(cls.bank_proposals.values()),
            fake_manifest={},
            root=cls.repo_root,
        )
        cls.review_queues = _build_review_queues(review_items)
        cls.prioritized = _prioritized_review_items(cls.review_queues)
        cls.items_by_id = {item.item_id: item for item in cls.prioritized}
        cls.proposal_ids = {
            name: proposal["case"]["case_id"]
            for name, proposal in cls.bank_proposals.items()
        }
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
        cls.markup = render_operations_cockpit(data)

    @classmethod
    def _invalid_supplier_case(cls) -> dict:
        fixture = json.loads(SUPPLIER_FIXTURE.read_text(encoding="utf-8"))
        fixture["scenario"] = "invalid_supplier_total"
        fixture["mock_extraction"]["invoice_number"] = "INV-SUPPLIER-INVALID"
        fixture["mock_extraction"]["amounts"] = {
            "net": "1000.00",
            "vat": "250.00",
            "gross": "NaN",
        }
        fixture_path = cls.repo_root / "fixtures" / "invalid-supplier-total.json"
        fixture_path.parent.mkdir()
        fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
        packet = SupplierInvoicePipeline(
            db_path=None,
            output_dir=None,
            entity_id="synthetic-amount-evidence",
            evaluation_date=date(2026, 5, 16),
        ).process_fixture(fixture_path)
        packet_path = cls.evidence_dir / "invalid-supplier-total.json"
        packet_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "summary": {
                "case_id": packet["case"]["case_id"],
                "scenario": fixture["scenario"],
                "execution_gate_mode": packet["policy_decision"]["mode"],
            },
            "packet": packet,
            "packet_path": packet_path,
        }

    @classmethod
    def _bank_case(
        cls,
        name: str,
        *,
        transaction_amount: int,
        target_amount: int,
        target_type: MatchTargetType,
        reference: str,
        transaction_currency: str = "SEK",
        target_currency: str = "SEK",
    ) -> dict:
        counterparty = f"Counterparty {name}"
        transaction = BankTransaction(
            transaction_id=f"TX-{name}",
            date=date(2026, 7, 10),
            amount_minor=transaction_amount,
            currency=transaction_currency,
            counterparty=counterparty,
            reference=reference,
            bank_account="1930",
            source="synthetic_fixture",
        )
        target = MatchTarget(
            target_id=f"TARGET-{name}",
            target_type=target_type,
            date=date(2026, 7, 10),
            amount_minor=target_amount,
            remaining_amount_minor=target_amount,
            currency=target_currency,
            counterparty=counterparty,
            reference=reference,
            source="synthetic_fixture",
        )
        return BankReconciliationPipeline(
            output_dir=cls.evidence_dir / name
        ).process([transaction], [target])[0]

    def test_supplier_facts_keep_exact_values_dates_and_invalid_total(self) -> None:
        item = self.items_by_id[self.supplier_case_id]
        facts = _facts_by_label(item.context.facts if item.context else ())

        self.assertEqual(("1,000.00 SEK", "1 000,00 SEK"), _values(facts["Net amount"]))
        self.assertEqual(("250.00 SEK", "250,00 SEK"), _values(facts["VAT amount"]))
        self.assertEqual(
            ("Missing or invalid", "Saknas eller är ogiltigt"),
            _values(facts["Invoice total"]),
        )
        self.assertEqual(("2026-05-10", "2026-05-10"), _values(facts["Invoice date"]))
        self.assertEqual(("2026-06-09", "2026-06-09"), _values(facts["Due date"]))

        row = _review_row(self.markup, self.supplier_case_id)
        self.assertIn('data-en="Invoice total" data-sv="Fakturabelopp"', row)
        self.assertIn(
            'data-en="Missing or invalid" data-sv="Saknas eller är ogiltigt"',
            row,
        )
        self.assertNotIn("NaN", row)
        self.assertIn("missing or invalid", _search_text(row))
        self.assertIn("saknas eller är ogiltigt", _search_text(row))

    def test_partial_inflow_and_outflow_show_absolute_remaining_amount(self) -> None:
        for name, bank_amount, open_amount in (
            ("partial_inflow", "400.00 SEK", "1,000.00 SEK"),
            ("partial_outflow", "-400.00 SEK", "-1,000.00 SEK"),
        ):
            with self.subTest(name=name):
                item = self.items_by_id[self.proposal_ids[name]]
                facts = _facts_by_label(item.context.facts if item.context else ())
                self.assertIn("Payment difference", item.categories)
                self.assertEqual(bank_amount, facts["Bank amount"].value)
                self.assertEqual(open_amount, facts["Open amount"].value)
                self.assertEqual("600.00 SEK", facts["Remaining if matched"].value)
                self.assertEqual("600,00 SEK", facts["Remaining if matched"].value_sv)

                row = _review_row(self.markup, self.proposal_ids[name])
                self.assertIn(
                    "Compare the payment with the open amount. Confirm the partial payment or difference treatment; no balance has been updated.",
                    row,
                )
                self.assertIn(
                    "Jämför betalningen med det öppna beloppet. Bekräfta hur delbetalningen eller mellanskillnaden ska hanteras; inget saldo har uppdaterats.",
                    row,
                )

    def test_overpayment_shows_excess_without_updating_a_balance(self) -> None:
        item = self.items_by_id[self.proposal_ids["overpayment"]]
        facts = _facts_by_label(item.context.facts if item.context else ())

        self.assertEqual("1,250.00 SEK", facts["Bank amount"].value)
        self.assertEqual("1,000.00 SEK", facts["Open amount"].value)
        self.assertEqual(
            "250.00 SEK",
            facts["Payment exceeds open amount by"].value,
        )
        self.assertNotIn("Remaining if matched", facts)
        proposal = self.bank_proposals["overpayment"]
        self.assertEqual("approval_required", proposal["policy_decision"]["mode"])
        self.assertFalse(proposal["reconciliation_payload"]["reconciles_in_fortnox"])

    def test_incompatible_currency_and_direction_have_no_numeric_residual(self) -> None:
        for name in ("currency_mismatch", "direction_mismatch"):
            with self.subTest(name=name):
                proposal = self.bank_proposals[name]
                self.assertIsNotNone(proposal["selected_candidate"])
                self.assertEqual("approval_required", proposal["policy_decision"]["mode"])
                self.assertFalse(proposal["reconciliation_payload"]["reconciles_in_fortnox"])

                item = self.items_by_id[self.proposal_ids[name]]
                facts = _facts_by_label(item.context.facts if item.context else ())
                self.assertIn("Incompatible match", item.categories)
                self.assertEqual("Not comparable", facts["Amount comparison"].value)
                self.assertEqual("Kan inte jämföras", facts["Amount comparison"].value_sv)
                self.assertNotIn("Remaining if matched", facts)
                self.assertNotIn("Payment exceeds open amount by", facts)

                row = _review_row(self.markup, self.proposal_ids[name])
                self.assertIn(
                    "Verify currency and payment direction. Do not compare amounts across currencies without exchange-rate evidence.",
                    row,
                )
                self.assertIn(
                    "Verifiera valuta och betalningsriktning. Jämför inte belopp mellan olika valutor utan styrkt valutakurs.",
                    row,
                )

    def test_proposed_reference_is_searchable_and_html_escaped(self) -> None:
        case_id = self.proposal_ids["partial_inflow"]
        item = self.items_by_id[case_id]
        facts = _facts_by_label(item.context.facts if item.context else ())
        self.assertEqual("INV-Ö & <Partial>", facts["Proposed match"].value)

        row = _review_row(self.markup, case_id)
        self.assertIn("INV-Ö &amp; &lt;Partial&gt;", row)
        self.assertNotIn("INV-Ö & <Partial>", row)
        search = _search_text(row)
        self.assertIn("proposed match", search)
        self.assertIn("föreslagen matchning", search)
        self.assertIn("inv-ö & <partial>", search)
        self.assertIn("remaining if matched", search)
        self.assertIn("kvar om matchningen godkänns", search)


def _facts_by_label(facts: tuple[ReviewFact, ...]) -> dict[str, ReviewFact]:
    return {fact.label: fact for fact in facts}


def _values(fact: ReviewFact) -> tuple[str, str]:
    return fact.value, fact.value_sv


def _review_row(markup: str, case_id: str) -> str:
    case_at = markup.index(case_id)
    row_start = markup.rfind('<li class="attention-row"', 0, case_at)
    if row_start < 0:
        raise AssertionError(f"Review row not found for {case_id}")
    next_row = markup.find('<li class="attention-row"', case_at + len(case_id))
    list_end = markup.index("</ol>", case_at)
    row_end = min(end for end in (next_row, list_end) if end >= 0)
    return markup[row_start:row_end]


def _search_text(row: str) -> str:
    match = re.search(r'data-search="([^"]*)"', row)
    if match is None:
        raise AssertionError("Review row has no searchable context")
    return html.unescape(match.group(1))


if __name__ == "__main__":
    unittest.main()
