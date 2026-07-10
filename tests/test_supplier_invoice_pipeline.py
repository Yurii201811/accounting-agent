from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from accounting_agent import LocalGnubokShadowLedgerAdapter, ShadowLedgerUnavailable
from accounting_agent.db import LOCAL_QUEUE_SCHEMA_VERSION, LocalQueue, QueueSchemaError
from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.supplier_invoice.extraction import extract_invoice_fields
from accounting_agent.supplier_invoice.pipeline import build_invoice_signature


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "supplier_invoices"


class SupplierInvoicePipelineTests(unittest.TestCase):
    def run_pipeline(self) -> tuple[list[dict], Path, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        db_path = root / "queue.sqlite"
        output_dir = root / "packets"
        pipeline = SupplierInvoicePipeline(
            db_path=db_path,
            output_dir=output_dir,
            evaluation_date=date(2026, 5, 16),
        )
        packets = pipeline.process_fixture_dir(FIXTURES)
        return packets, db_path, output_dir

    def test_processes_all_sample_fixtures_into_approval_packets(self) -> None:
        packets, db_path, output_dir = self.run_pipeline()

        self.assertEqual(5, len(packets))
        self.assertEqual(5, len(list(output_dir.glob("*.approval_packet.json"))))
        self.assertEqual(5, table_count(db_path, "approval_packets"))
        self.assertEqual(5, table_count(db_path, "accounting_proposals"))
        self.assertGreaterEqual(table_count(db_path, "audit_events"), 10)

        for packet in packets:
            self.assertEqual("supplier_invoice_autopilot_mvp1.v1", packet["packet_version"])
            self.assertTrue(packet["case"]["file_hash"])
            self.assertEqual("local_fixture", packet["case"]["created_from"])
            self.assertIn("entries", packet["accounting_proposal"])
            self.assertIn("flags", packet["risk"])
            self.assertIn(
                packet["policy_decision"]["mode"],
                {"draft_only", "approval_required", "escalation_required"},
            )
            self.assertIn("risk_findings", packet)
            self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])
            self.assertFalse(packet["next_action"]["live_api_call"])
            self.assertTrue(packet["required_human_decision"])
            self.assertIn("shadow_ledger_comparison", packet)
            self.assertEqual("fortnox", packet["shadow_ledger_comparison"]["source_of_truth"])
            self.assertIn(
                packet["shadow_ledger_comparison"]["status"],
                {"mirrored", "mirrored_with_warnings"},
            )

    def test_normal_swedish_invoice_is_draft_only_with_bas_and_vat_proposal(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "normal_swedish_25_vat")

        self.assertEqual("draft_only", packet["policy_decision"]["mode"])
        self.assertEqual("low", packet["risk"]["level"])
        self.assertEqual([], packet["risk"]["flags"])
        self.assertEqual("matched", packet["supplier_match"]["status"])
        self.assertEqual("6110", packet["accounting_proposal"]["bas_account"])
        self.assertEqual("2641", packet["vat_proposal"]["input_vat_account"])
        self.assertEqual("2440", packet["accounting_proposal"]["entries"][2]["account"])
        self.assertEqual("mirrored", packet["shadow_ledger_comparison"]["status"])
        self.assertEqual([], packet["shadow_ledger_comparison"]["differences"])
        self.assertEqual(
            packet["fortnox_draft_payload"]["accounting_rows"],
            packet["shadow_ledger_comparison"]["fortnox_payload"]["accounting_rows"],
        )

    def test_duplicate_invoice_is_blocked_for_human_review(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "possible_duplicate_invoice")

        self.assertEqual("possible_duplicate", packet["duplicate_check"]["status"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertIn("possible_duplicate", flag_codes(packet))
        self.assertEqual("none_until_duplicate_reviewed", packet["next_action"]["action"])

    def test_unknown_supplier_requires_review_but_still_gets_accounting_proposal(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "unknown_supplier")

        self.assertEqual("unknown", packet["supplier_match"]["status"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertIn("unknown_supplier", flag_codes(packet))
        self.assertEqual("6991", packet["accounting_proposal"]["bas_account"])
        self.assertEqual("none_until_supplier_created_or_matched", packet["next_action"]["action"])

    def test_changed_bank_details_blocks_supplier_master_update(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "changed_bank_details")

        self.assertEqual("changed", packet["supplier_match"]["bank_details_status"])
        self.assertIn("changed_bank_details", flag_codes(packet))
        self.assertEqual("escalation_required", packet["policy_decision"]["mode"])
        self.assertIn("security_review", packet["policy_decision"]["required_reviews"])
        self.assertIn("update_supplier_bank_details", packet["policy_decision"]["blocked_actions"])
        self.assertEqual("none_until_bank_details_verified", packet["next_action"]["action"])

    def test_uncertain_vat_and_extraction_requires_manual_review(self) -> None:
        packets, _, _ = self.run_pipeline()
        packet = by_scenario(packets, "uncertain_vat_extraction")

        codes = flag_codes(packet)
        self.assertIn("low_extraction_confidence", codes)
        self.assertIn("missing_required_fields", codes)
        self.assertIn("vat_amount_mismatch", codes)
        self.assertEqual("manual_review", packet["vat_proposal"]["status"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertEqual("none_until_extraction_and_vat_reviewed", packet["next_action"]["action"])
        self.assertIn(
            "vat_amount_differs_from_rate:expected_30000:actual_12500",
            packet["shadow_ledger_comparison"]["warnings"],
        )

    def test_shadow_ledger_fail_soft_keeps_supplier_invoice_pipeline_working(self) -> None:
        class UnavailableAdapter(LocalGnubokShadowLedgerAdapter):
            def get_or_create_company_context(self, **kwargs):  # type: ignore[no-untyped-def]
                raise ShadowLedgerUnavailable("gnubok_not_configured")

        pipeline = SupplierInvoicePipeline(
            db_path=None,
            output_dir=None,
            shadow_ledger_adapter=UnavailableAdapter(),
        )

        packet = pipeline.process_fixture(FIXTURES / "01_normal_25_vat.json")

        self.assertEqual("shadow_unavailable", packet["shadow_ledger_comparison"]["status"])
        self.assertEqual("fortnox", packet["shadow_ledger_comparison"]["source_of_truth"])
        self.assertIn("main_pipeline_unaffected", packet["shadow_ledger_comparison"]["warnings"])
        self.assertFalse(packet["fortnox_draft_payload"]["live_api_call"])

    def test_same_fixture_is_isolated_across_clients_in_one_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            first = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "Client-A",
                client_id="Client-A",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            second = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-a",
                client_id="client-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            intake_count = table_count(db_path, "intake_cases")
            document_count = table_count(db_path, "documents")

        self.assertNotEqual(first["case"]["case_id"], second["case"]["case_id"])
        self.assertEqual("Client-A", first["case"]["client_id"])
        self.assertEqual("client-a", second["case"]["client_id"])
        self.assertEqual("unique", second["duplicate_check"]["status"])
        self.assertEqual(2, intake_count)
        self.assertEqual(2, document_count)

    def test_v01_unscoped_duplicate_fails_closed_without_leaking_legacy_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "legacy-queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            seed_v01_queue(db_path, fixture)

            packet = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-a",
                client_id="client-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)

            self.assertEqual(LOCAL_QUEUE_SCHEMA_VERSION, LocalQueue(db_path).schema_version())

        duplicate = packet["duplicate_check"]
        self.assertEqual("possible_duplicate", duplicate["status"])
        self.assertEqual("legacy_unscoped_review", duplicate["scope_status"])
        self.assertIsNone(duplicate["duplicate_of_case_id"])
        self.assertIsNone(duplicate["duplicate_source_path"])
        self.assertEqual("approval_required", packet["policy_decision"]["mode"])
        self.assertNotIn("legacy-case", json.dumps(duplicate))
        self.assertNotIn("legacy/private/path", json.dumps(duplicate))

    def test_explicit_v01_mapping_restores_same_client_match_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "legacy-queue.sqlite"
            fixture = FIXTURES / "01_normal_25_vat.json"
            seed_v01_queue(db_path, fixture)
            queue = LocalQueue(db_path)

            self.assertEqual(1, queue.map_legacy_rows_to_client("client-a"))
            client_b = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-b",
                client_id="client-b",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)
            client_a = SupplierInvoicePipeline(
                db_path=db_path,
                output_dir=root / "client-a",
                client_id="client-a",
                evaluation_date=date(2026, 5, 16),
            ).process_fixture(fixture)

        self.assertEqual("unique", client_b["duplicate_check"]["status"])
        self.assertEqual("possible_duplicate", client_a["duplicate_check"]["status"])
        self.assertEqual("legacy-case", client_a["duplicate_check"]["duplicate_of_case_id"])

    def test_queue_refuses_unknown_newer_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "future-queue.sqlite"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute(
                    f"PRAGMA user_version = {LOCAL_QUEUE_SCHEMA_VERSION + 1}"
                )
            with self.assertRaises(QueueSchemaError):
                LocalQueue(db_path).initialize()

    def test_cli_one_command_processes_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_path = root / "queue.sqlite"
            output_dir = root / "packets"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "process-fixtures",
                    "--fixtures",
                    str(FIXTURES),
                    "--db",
                    str(db_path),
                    "--output",
                    str(output_dir),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("Processed 5 supplier invoice fixtures", result.stdout)


def by_scenario(packets: list[dict], scenario: str) -> dict:
    for packet in packets:
        if packet["case"]["fixture_name"] == scenario:
            return packet
    raise AssertionError(f"Missing packet for scenario {scenario}")


def flag_codes(packet: dict) -> set[str]:
    return {flag["code"] for flag in packet["risk"]["flags"]}


def table_count(db_path: Path, table_name: str) -> int:
    with closing(sqlite3.connect(db_path)) as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    return int(row[0])


def seed_v01_queue(db_path: Path, fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    extracted = extract_invoice_fields(fixture)
    scoped_signature = build_invoice_signature(extracted, client_id="client-a")
    legacy_signature = scoped_signature.split("|", 1)[1]
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(
            """
            PRAGMA user_version = 1;
            PRAGMA foreign_keys = ON;
            CREATE TABLE intake_cases (
                case_id TEXT PRIMARY KEY,
                fixture_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE documents (
                doc_hash TEXT PRIMARY KEY,
                case_id TEXT NOT NULL UNIQUE REFERENCES intake_cases(case_id),
                source_path TEXT NOT NULL,
                invoice_signature TEXT NOT NULL,
                supplier_name TEXT,
                supplier_org_number TEXT,
                invoice_number TEXT,
                invoice_date TEXT,
                gross_amount TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO intake_cases (
                case_id, fixture_name, source_path, file_hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-case",
                "legacy_fixture",
                "legacy/private/path",
                "legacy-file-hash",
                "approval_packet_ready",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO documents (
                doc_hash, case_id, source_path, invoice_signature,
                supplier_name, supplier_org_number, invoice_number,
                invoice_date, gross_amount, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-document-hash",
                "legacy-case",
                "legacy/private/path",
                legacy_signature,
                extracted.get("supplier_name"),
                extracted.get("supplier_org_number"),
                extracted.get("invoice_number"),
                extracted.get("invoice_date"),
                extracted["amounts"].get("gross"),
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()


if __name__ == "__main__":
    unittest.main()
