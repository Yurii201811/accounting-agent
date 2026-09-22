from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from accounting_agent.local_system import (
    LocalAccountingSystem,
    LocalSystemConflict,
    LocalSystemSchemaError,
    sample_bundle,
)


class LocalAccountingSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.system = LocalAccountingSystem(self.temp.name)

    def test_sample_bundle_runs_end_to_end_and_survives_restart(self) -> None:
        run = self.system.create_run(sample_bundle(), "sample-request")

        self.assertEqual("completed", run["status"])
        self.assertEqual(35, run["counts"]["total"])
        self.assertEqual(
            {"supplier_invoice", "bank_reconciliation"},
            {case["kind"] for case in run["cases"]},
        )
        for case in run["cases"]:
            self.assertTrue(case["packet"])
            self.assertEqual(64, len(case["evidence_hash"]))
            self.assertEqual(
                "not_required" if case["policy_mode"] == "draft_only" else "unreviewed",
                case["review_status"],
            )

        restarted = LocalAccountingSystem(self.temp.name)
        loaded = restarted.get_run(run["run_id"])
        self.assertEqual(run["counts"], loaded["counts"])
        self.assertEqual(
            {case["case_id"] for case in run["cases"]},
            {case["case_id"] for case in loaded["cases"]},
        )
        self.assertNotIn("packet", restarted.list_runs()[0])
        self.assertEqual(
            [1, 2],
            [event["sequence"] for event in loaded["audit"]],
        )

    def test_request_key_is_idempotent_and_bound_to_bundle_content(self) -> None:
        bundle = sample_bundle()
        first = self.system.create_run(bundle, "stable-request")
        second = self.system.create_run(copy.deepcopy(bundle), "stable-request")

        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(1, len(self.system.list_runs()))

        changed = copy.deepcopy(bundle)
        changed["name"] = "Different bundle"
        with self.assertRaises(LocalSystemConflict):
            self.system.create_run(changed, "stable-request")

    def test_invalid_bundle_persists_failed_run_without_cases(self) -> None:
        bundle = sample_bundle()
        del bundle["bank_transactions"][0]["currency"]

        with self.assertRaises(ValueError):
            self.system.create_run(bundle, "invalid-request")

        rows = self.system.list_runs()
        self.assertEqual(1, len(rows))
        self.assertEqual("failed", rows[0]["status"])
        self.assertEqual(0, rows[0]["case_count"])
        failed = self.system.get_run(rows[0]["run_id"])
        self.assertEqual([], failed["cases"])
        self.assertIn("currency", failed["error"])

    def test_bundle_rejects_lossy_amounts_nonfinite_values_and_oversized_inputs(self) -> None:
        lossy = sample_bundle()
        lossy["bank_transactions"][0]["amount_minor"] = "10000"
        with self.assertRaisesRegex(ValueError, "amount_minor must be an integer"):
            self.system.create_run(lossy, "lossy-amount")

        nonfinite = sample_bundle()
        nonfinite["bank_transactions"][0]["amount_minor"] = float("nan")
        with self.assertRaisesRegex(ValueError, "only JSON values"):
            self.system.create_run(nonfinite, "nonfinite")

        oversized = sample_bundle()
        oversized["supplier_invoices"] = [
            copy.deepcopy(oversized["supplier_invoices"][0]) for _ in range(201)
        ]
        with self.assertRaisesRegex(ValueError, "at most 200 items"):
            self.system.create_run(oversized, "oversized")

    def test_review_is_atomic_revision_bound_and_does_not_change_policy(self) -> None:
        run = self.system.create_run(sample_bundle(), "review-request")
        original = next(
            case for case in run["cases"] if case["review_status"] == "unreviewed"
        )
        original_policy = copy.deepcopy(original["packet"]["policy_decision"])

        reviewed = self.system.record_review(
            run["run_id"],
            original["case_id"],
            outcome="needs_changes",
            note="Synthetic evidence needs correction.",
            expected_revision=0,
        )

        self.assertEqual("needs_changes", reviewed["review_status"])
        self.assertEqual(1, reviewed["review_revision"])
        self.assertEqual(original_policy, reviewed["packet"]["policy_decision"])
        self.assertEqual(1, len(reviewed["review_history"]))
        self.assertEqual(reviewed["reviews"], reviewed["review_history"])
        with self.assertRaises(LocalSystemConflict):
            self.system.record_review(
                run["run_id"],
                original["case_id"],
                outcome="reviewed",
                note="Stale update",
                expected_revision=0,
            )

        exported = self.system.export_run(run["run_id"])
        self.assertTrue(exported["integrity_verified"])
        self.assertEqual([], exported["integrity_errors"])
        self.assertEqual(1, len(exported["reviews"]))
        self.assertEqual("local_operator", exported["reviews"][0]["actor"])
        self.assertEqual(original["evidence_hash"], exported["reviews"][0]["evidence_hash"])
        self.assertTrue(
            any(event["event_type"] == "review_recorded" for event in exported["audit"])
        )
        unhashed = dict(exported)
        content_hash = unhashed.pop("content_hash")
        canonical = json.dumps(
            unhashed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            content_hash,
        )

    def test_concurrent_stale_reviews_are_serialized(self) -> None:
        run = self.system.create_run(sample_bundle(), "concurrent-review")
        case = next(item for item in run["cases"] if item["review_status"] == "unreviewed")
        second_system = LocalAccountingSystem(self.temp.name)

        def submit(system: LocalAccountingSystem, note: str) -> str:
            try:
                system.record_review(
                    run["run_id"],
                    case["case_id"],
                    outcome="needs_changes",
                    note=note,
                    expected_revision=0,
                )
                return "recorded"
            except LocalSystemConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(
                    lambda args: submit(*args),
                    ((self.system, "First review"), (second_system, "Second review")),
                )
            )
        self.assertEqual(["conflict", "recorded"], sorted(outcomes))
        self.assertEqual(1, len(self.system.get_case(run["run_id"], case["case_id"])["reviews"]))

    def test_export_detects_tampered_packet(self) -> None:
        run = self.system.create_run(sample_bundle(), "tamper-request")
        case = run["cases"][0]
        tampered = copy.deepcopy(case["packet"])
        tampered["tampered"] = True
        with closing(sqlite3.connect(self.system.database_path)) as connection:
            with connection:
                connection.execute(
                    "UPDATE cases SET packet_json = ? WHERE run_id = ? AND case_id = ?",
                    (
                        json.dumps(tampered, sort_keys=True, separators=(",", ":")),
                        run["run_id"],
                        case["case_id"],
                    ),
                )

        exported = self.system.export_run(run["run_id"])
        self.assertFalse(exported["integrity_verified"])
        self.assertIn(
            f"case_evidence_hash_mismatch:{case['case_id']}",
            exported["integrity_errors"],
        )

    def test_orphaned_subprocess_run_is_marked_interrupted(self) -> None:
        script = """
import os
import sys
from accounting_agent.local_system import LocalAccountingSystem, sample_bundle

system = LocalAccountingSystem(sys.argv[1])
system._process_bundle = lambda *_args: os._exit(17)
system.create_run(sample_bundle(), "interrupted-request")
"""
        result = subprocess.run(
            [sys.executable, "-c", script, self.temp.name],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(17, result.returncode, result.stderr)

        restarted = LocalAccountingSystem(self.temp.name)
        recovered = restarted.list_runs()[0]
        self.assertEqual("interrupted", recovered["status"])
        self.assertIn("submit a new request key", recovered["error"])
        run = restarted.get_run(recovered["run_id"])
        self.assertEqual("run_interrupted", run["audit"][-1]["event_type"])

    def test_live_subprocess_owner_is_not_marked_interrupted(self) -> None:
        script = """
import sys
import time
from accounting_agent.local_system import LocalAccountingSystem, sample_bundle

system = LocalAccountingSystem(sys.argv[1])
def stall(*_args):
    print("READY", flush=True)
    time.sleep(60)
system._process_bundle = stall
system.create_run(sample_bundle(), "live-request")
"""
        process = subprocess.Popen(
            [sys.executable, "-c", script, self.temp.name],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    _, stderr = process.communicate()
                    self.fail(f"owner subprocess exited early: {stderr}")
                with closing(sqlite3.connect(self.system.database_path)) as connection:
                    row = connection.execute(
                        "SELECT run_id FROM runs WHERE status = 'processing'"
                    ).fetchone()
                if row is not None:
                    run_id = str(row[0])
                    break
                time.sleep(0.05)
            else:
                self.fail("owner subprocess did not persist a processing run")

            concurrent = LocalAccountingSystem(self.temp.name)
            self.assertEqual("processing", concurrent.get_run(run_id)["status"])
            self.assertFalse(
                any(
                    event["event_type"] == "run_interrupted"
                    for event in concurrent.get_run(run_id)["audit"]
                )
            )
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

        recovered = LocalAccountingSystem(self.temp.name).get_run(run_id)
        self.assertEqual("interrupted", recovered["status"])
        self.assertEqual("run_interrupted", recovered["audit"][-1]["event_type"])

    def test_unversioned_sequenced_schema_is_upgraded_additively(self) -> None:
        run = self.system.create_run(sample_bundle(), "legacy-compatible")
        with closing(sqlite3.connect(self.system.database_path)) as connection:
            with connection:
                connection.execute("ALTER TABLE runs DROP COLUMN owner_pid")
                connection.execute("PRAGMA user_version = 0")

        upgraded = LocalAccountingSystem(self.temp.name)
        self.assertEqual("completed", upgraded.get_run(run["run_id"])["status"])
        with closing(sqlite3.connect(self.system.database_path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
        self.assertEqual(1, version)
        self.assertIn("owner_pid", columns)

    def test_incompatible_database_schema_is_refused_without_mutation(self) -> None:
        with closing(sqlite3.connect(self.system.database_path)) as connection:
            with connection:
                connection.execute(
                    "ALTER TABLE audit_events RENAME COLUMN sequence TO legacy_sequence"
                )

        with self.assertRaisesRegex(
            LocalSystemSchemaError,
            r"missing audit_events\.sequence",
        ):
            LocalAccountingSystem(self.temp.name)

        with closing(sqlite3.connect(self.system.database_path)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(audit_events)").fetchall()
            }
        self.assertIn("legacy_sequence", columns)
        self.assertNotIn("sequence", columns)

    def test_missing_records_and_invalid_review_inputs_fail_closed(self) -> None:
        with self.assertRaises(KeyError):
            self.system.get_run("missing")
        run = self.system.create_run(sample_bundle(), "input-request")
        case = run["cases"][0]
        with self.assertRaises(ValueError):
            self.system.record_review(
                run["run_id"],
                case["case_id"],
                outcome="approve_financially",
                note="",
                expected_revision=0,
            )
        with self.assertRaises(ValueError):
            self.system.record_review(
                run["run_id"],
                case["case_id"],
                outcome="needs_changes",
                note="   ",
                expected_revision=0,
            )
        with self.assertRaises(KeyError):
            self.system.get_case(run["run_id"], "missing")


if __name__ == "__main__":
    unittest.main()
