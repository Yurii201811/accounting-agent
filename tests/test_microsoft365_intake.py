from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from accounting_agent import (
    ClientMapper,
    ClientMappingRule,
    IntakeSourceType,
    LocalIntakeProcessor,
    SQLiteIntakeStore,
    manual_upload_source,
    outlook_attachment_source,
    teams_message_file_source,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "microsoft365_intake"


class Microsoft365IntakeTests(unittest.TestCase):
    def make_store_and_processor(
        self,
        *,
        copy_files: bool = True,
    ) -> tuple[SQLiteIntakeStore, LocalIntakeProcessor, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        store = SQLiteIntakeStore(root / "intake.sqlite")
        store.add_client_mapping_rule(
            ClientMappingRule(
                rule_id="domain-acme",
                match_type="domain",
                pattern="acme.example",
                client_id="client_acme",
                priority=10,
            )
        )
        store.add_client_mapping_rule(
            ClientMappingRule(
                rule_id="folder-fixtures",
                match_type="folder",
                pattern="microsoft365_intake",
                client_id="client_fixture",
                priority=20,
            )
        )
        processor = LocalIntakeProcessor(
            store=store,
            storage_root=root / "stored_documents",
            client_mapper=ClientMapper.from_store(store),
            copy_files=copy_files,
        )
        return store, processor, root

    def test_outlook_attachment_becomes_normalized_case_and_extraction_task(self) -> None:
        store, processor, _ = self.make_store_and_processor()
        source = outlook_attachment_source(
            FIXTURES / "acme_invoice_001.txt",
            sender="ACME Billing <billing@acme.example>",
            received_at="2026-05-16T08:00:00+00:00",
            message_id="message-001",
            attachment_id="attachment-001",
            subject="Invoice INV-001",
        )

        case = processor.ingest(source)

        self.assertEqual(IntakeSourceType.OUTLOOK_EMAIL_ATTACHMENT, case.source_type)
        self.assertEqual("client_acme", case.client_id)
        self.assertEqual("domain-acme", case.client_mapping_rule)
        self.assertTrue(case.sha256)
        self.assertEqual("copied", case.storage_mode)
        self.assertTrue(Path(case.stored_path).exists())
        self.assertEqual("billing@acme.example", case.source_metadata["sender"].split("<")[1].rstrip(">"))
        self.assertEqual("INV-001", case.invoice_metadata["invoice_number"])
        self.assertEqual(125000, case.invoice_metadata["amount_minor"])
        self.assertEqual(1, len(store.list_cases()))

        tasks = store.list_extraction_tasks()
        self.assertEqual(1, len(tasks))
        self.assertEqual(case.case_id, tasks[0].case_id)
        self.assertEqual("extract_document", tasks[0].task_type)
        self.assertEqual("queued", tasks[0].status)
        self.assertEqual(case.sha256, tasks[0].payload["sha256"])

        event_types = {event["event_type"] for event in store.list_audit_events()}
        self.assertIn("intake_case_created", event_types)
        self.assertIn("extraction_task_queued", event_types)

    def test_folder_scan_creates_cases_detects_duplicates_and_is_idempotent(self) -> None:
        store, processor, _ = self.make_store_and_processor()

        first_scan = processor.scan_folder(FIXTURES)

        self.assertEqual(4, len(first_scan))
        self.assertEqual(4, len(store.list_cases()))
        self.assertEqual(4, len(store.list_extraction_tasks()))

        cases_by_name = {case.file_name: case for case in store.list_cases()}
        original = cases_by_name["acme_invoice_001.txt"]
        hash_copy = cases_by_name["acme_invoice_001_hash_copy.txt"]
        metadata_duplicate = cases_by_name["acme_invoice_001_metadata_duplicate.txt"]

        self.assertEqual(original.sha256, hash_copy.sha256)
        self.assertEqual(original.case_id, hash_copy.duplicate_of_case_id)
        self.assertIn("sha256", hash_copy.duplicate_reasons)
        self.assertIn("invoice_metadata", hash_copy.duplicate_reasons)

        self.assertNotEqual(original.sha256, metadata_duplicate.sha256)
        self.assertEqual(original.case_id, metadata_duplicate.duplicate_of_case_id)
        self.assertEqual(("invoice_metadata",), metadata_duplicate.duplicate_reasons)

        second_scan = processor.scan_folder(FIXTURES)

        self.assertEqual([case.case_id for case in first_scan], [case.case_id for case in second_scan])
        self.assertEqual(4, len(store.list_cases()))
        self.assertEqual(4, len(store.list_extraction_tasks()))
        self.assertTrue((FIXTURES / "acme_invoice_001.txt").exists())

    def test_manual_upload_and_future_teams_source_use_same_local_interface(self) -> None:
        store, processor, _ = self.make_store_and_processor(copy_files=False)
        manual_case = processor.ingest(
            manual_upload_source(
                FIXTURES / "beta_receipt_002.txt",
                uploaded_by="local_operator",
                note="Manual local upload fixture",
            )
        )
        teams_case = processor.ingest(
            teams_message_file_source(
                FIXTURES / "beta_receipt_002.txt",
                team_id="team-local-fixture",
                channel_id="channel-invoices",
                message_id="message-002",
                file_id="file-002",
                sender="teammate@example.invalid",
            )
        )

        self.assertEqual(IntakeSourceType.MANUAL_LOCAL_UPLOAD, manual_case.source_type)
        self.assertEqual("referenced", manual_case.storage_mode)
        self.assertEqual(IntakeSourceType.TEAMS_MESSAGE_FILE, teams_case.source_type)
        self.assertEqual("future_interface_only", teams_case.source_metadata["connector_status"])
        self.assertEqual(manual_case.case_id, teams_case.duplicate_of_case_id)
        self.assertIn("sha256", teams_case.duplicate_reasons)
        self.assertEqual(2, len(store.list_extraction_tasks()))


if __name__ == "__main__":
    unittest.main()
