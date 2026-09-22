from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from accounting_agent.local_maintenance import DATABASE_NAME, create_backup, restore_backup
from accounting_agent.local_system import LocalAccountingSystem, sample_bundle


class LocalMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = LocalAccountingSystem(self.root / "source")
        bundle = sample_bundle()
        bundle["supplier_invoices"] = bundle["supplier_invoices"][:1]
        bundle["bank_transactions"] = bundle["bank_transactions"][:1]
        self.run = self.system.create_run(bundle, "backup-test")
        case = self.run["cases"][0]
        self.system.record_review(self.run["run_id"], case["case_id"], outcome="needs_changes",
                                  note="Synthetic backup acceptance", expected_revision=0)
        self.backup = self.root / "workspace.zip"

    def test_restore_preserves_export_exactly_and_does_not_change_source(self):
        original = self.system.export_run(self.run["run_id"])
        manifest = create_backup(self.system.data_dir, self.backup)
        self.assertEqual(1, manifest["counts"]["reviews"])
        restored = restore_backup(self.backup, self.root / "restored")
        reopened = LocalAccountingSystem(restored["data_dir"])
        self.assertEqual(original, reopened.export_run(self.run["run_id"]))
        self.assertEqual(original, self.system.export_run(self.run["run_id"]))
        self.assertEqual("ready", reopened.health()["status"])
        self.assertEqual(0o600, (Path(restored["data_dir"]) / DATABASE_NAME).stat().st_mode & 0o777)

    def test_backup_and_restore_never_replace_existing_work(self):
        create_backup(self.system.data_dir, self.backup)
        original = self.backup.read_bytes()
        with self.assertRaises(FileExistsError):
            create_backup(self.system.data_dir, self.backup)
        with self.assertRaises(FileExistsError):
            restore_backup(self.backup, self.system.data_dir)
        self.assertEqual(original, self.backup.read_bytes())
        self.assertEqual(1, len(self.system.list_runs()))

    def test_manifest_mismatch_leaves_no_restore_directory(self):
        create_backup(self.system.data_dir, self.backup)
        with zipfile.ZipFile(self.backup) as archive:
            database = archive.read(DATABASE_NAME)
            manifest = json.loads(archive.read("manifest.json"))
        manifest["database_sha256"] = "0" * 64
        altered = self.root / "altered.zip"
        with zipfile.ZipFile(altered, "w") as archive:
            archive.writestr(DATABASE_NAME, database)
            archive.writestr("manifest.json", json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "hash"):
            restore_backup(altered, self.root / "restored")
        self.assertFalse((self.root / "restored").exists())

    def test_bad_evidence_is_rejected_even_with_matching_archive_hash(self):
        create_backup(self.system.data_dir, self.backup)
        with zipfile.ZipFile(self.backup) as archive:
            database = self.root / "changed.sqlite"
            database.write_bytes(archive.read(DATABASE_NAME))
            manifest = json.loads(archive.read("manifest.json"))
        connection = sqlite3.connect(database)
        try:
            connection.execute("UPDATE cases SET evidence_hash = ?", ("invalid",))
            connection.commit()
        finally:
            connection.close()
        payload = database.read_bytes()
        manifest["database_sha256"] = hashlib.sha256(payload).hexdigest()
        altered = self.root / "altered.zip"
        with zipfile.ZipFile(altered, "w") as archive:
            archive.writestr(DATABASE_NAME, payload)
            archive.writestr("manifest.json", json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "evidence integrity"):
            restore_backup(altered, self.root / "restored")
        self.assertFalse((self.root / "restored").exists())

    def test_processing_run_cannot_be_backed_up_as_completed(self):
        with self.system._session(immediate=True) as connection:
            connection.execute("UPDATE runs SET status = 'processing', owner_pid = ?", (os.getpid(),))
        with self.assertRaisesRegex(RuntimeError, "processing"):
            create_backup(self.system.data_dir, self.backup)
        self.assertFalse(self.backup.exists())
        self.assertEqual("processing", self.system.get_run(self.run["run_id"])["status"])

    def test_unexpected_archive_entries_and_missing_source_are_rejected(self):
        with zipfile.ZipFile(self.backup, "w") as archive:
            archive.writestr("unexpected.txt", "synthetic")
        with self.assertRaisesRegex(ValueError, "exactly"):
            restore_backup(self.backup, self.root / "restored")
        with self.assertRaises(ValueError):
            create_backup(self.root / "missing", self.root / "missing.zip")
        self.assertFalse((self.root / "missing").exists())
