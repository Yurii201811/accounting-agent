from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from accounting_agent.local_system import LocalAccountingSystem, LocalSystemConflict, sample_bundle


class LocalSystemConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.system = LocalAccountingSystem(self.temp.name)
        bundle = sample_bundle()
        bundle["supplier_invoices"] = bundle["supplier_invoices"][:1]
        bundle["bank_transactions"] = bundle["bank_transactions"][:1]
        self.run = self.system.create_run(bundle, "consistency")
        self.case = self.run["cases"][0]

    def review(self):
        return self.system.record_review(self.run["run_id"], self.case["case_id"],
            outcome="needs_changes", note="Synthetic integrity check", expected_revision=0)

    def test_export_reads_one_snapshot_during_concurrent_review(self):
        with self.system._session() as connection:
            connection.commit()
            connection.execute("PRAGMA journal_mode = WAL")
        writer = LocalAccountingSystem(self.temp.name)
        original_list = self.system._list_cases
        def list_then_commit_review(connection, run_id):
            cases = original_list(connection, run_id)
            writer.record_review(run_id, self.case["case_id"], outcome="reviewed",
                                 note="Concurrent synthetic review", expected_revision=0)
            return cases
        with patch.object(self.system, "_list_cases", side_effect=list_then_commit_review):
            snapshot = self.system.export_run(self.run["run_id"])
        self.assertTrue(snapshot["integrity_verified"], snapshot["integrity_errors"])
        self.assertEqual([], snapshot["reviews"])
        self.assertEqual(0, snapshot["cases"][0]["review_revision"])
        self.assertEqual(1, len(self.system.export_run(self.run["run_id"])["reviews"]))

    def test_deleted_case_is_detected_by_completed_run_count(self):
        with self.system._session(immediate=True) as connection:
            connection.execute("DELETE FROM cases WHERE run_id = ? AND case_id = ?",
                               (self.run["run_id"], self.case["case_id"]))
        exported = self.system.export_run(self.run["run_id"])
        self.assertFalse(exported["integrity_verified"])
        self.assertIn("completed_case_count_mismatch", exported["integrity_errors"])

    def test_review_and_audit_tail_must_match_saved_case_state(self):
        self.review()
        with self.system._session(immediate=True) as connection:
            connection.execute("DELETE FROM reviews WHERE run_id = ?", (self.run["run_id"],))
            connection.execute("DELETE FROM audit_events WHERE event_type = 'review_recorded'")
        exported = self.system.export_run(self.run["run_id"])
        self.assertFalse(exported["integrity_verified"])
        self.assertTrue(any(e.startswith("case_review_state_mismatch:") for e in exported["integrity_errors"]))

    def test_missing_review_audit_event_and_terminal_event_are_detected(self):
        self.review()
        with self.system._session(immediate=True) as connection:
            connection.execute("DELETE FROM audit_events WHERE event_type = 'review_recorded'")
        exported = self.system.export_run(self.run["run_id"])
        self.assertTrue(any(e.startswith("review_audit_mismatch:") for e in exported["integrity_errors"]))
        with self.system._session(immediate=True) as connection:
            connection.execute("DELETE FROM audit_events WHERE event_type = 'run_completed'")
        self.assertIn("run_terminal_audit_mismatch", self.system.export_run(self.run["run_id"])["integrity_errors"])

    def test_changed_policy_projection_blocks_review_and_export(self):
        with self.system._session(immediate=True) as connection:
            connection.execute("UPDATE cases SET policy_mode = 'forbidden' WHERE case_id = ?", (self.case["case_id"],))
        with self.assertRaisesRegex(LocalSystemConflict, "inconsistent"):
            self.review()
        exported = self.system.export_run(self.run["run_id"])
        self.assertTrue(any(e.startswith("case_policy_mismatch:") for e in exported["integrity_errors"]))
        self.assertEqual([], exported["reviews"])
