from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from accounting_agent.db import LOCAL_QUEUE_SCHEMA_VERSION, LocalQueue, QueueSchemaError
from accounting_agent.evidence import EvidenceIntegrityError, HashChainedEventLog


class SQLiteResilienceV1Tests(unittest.TestCase):
    def test_queue_session_rolls_back_the_entire_failed_unit_of_work(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalQueue(Path(directory) / "queue.sqlite")
            queue.initialize()

            with self.assertRaisesRegex(RuntimeError, "synthetic crash"):
                with queue.session() as connection:
                    connection.execute(
                        """
                        INSERT INTO intake_cases (
                            case_id, fixture_name, source_path, file_hash,
                            client_id, entity_id, identity_scope_version,
                            status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "case-rollback",
                            "synthetic.json",
                            "synthetic://fixture",
                            "f" * 64,
                            "client-a",
                            "entity-a",
                            LOCAL_QUEUE_SCHEMA_VERSION,
                            "received",
                            "2026-07-11T08:00:00+00:00",
                            "2026-07-11T08:00:00+00:00",
                        ),
                    )
                    raise RuntimeError("synthetic crash")

            with queue.session() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM intake_cases WHERE case_id = ?",
                    ("case-rollback",),
                ).fetchone()[0]
            self.assertEqual(0, count)

    def test_initialized_queue_passes_sqlite_integrity_and_foreign_key_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalQueue(Path(directory) / "queue.sqlite")
            queue.initialize()

            with queue.session() as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchall()
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()

            self.assertEqual([("ok",)], [tuple(row) for row in integrity])
            self.assertEqual([], foreign_keys)

    def test_future_schema_refusal_does_not_mutate_the_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite"
            future_version = LOCAL_QUEUE_SCHEMA_VERSION + 1
            with sqlite3.connect(path) as connection:
                connection.execute(f"PRAGMA user_version = {future_version}")

            with self.assertRaisesRegex(QueueSchemaError, "unsafe downgrade"):
                LocalQueue(path).initialize()

            with sqlite3.connect(path) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            self.assertEqual(future_version, version)
            self.assertEqual([], tables)

    def test_locked_queue_fails_without_partial_mutation_and_recovers_after_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "locked.sqlite"
            queue = LocalQueue(path)
            queue.initialize()
            holder = sqlite3.connect(path)
            holder.execute("BEGIN EXCLUSIVE")
            real_connect = sqlite3.connect

            try:
                with patch(
                    "accounting_agent.db.sqlite3.connect",
                    side_effect=lambda *args, **kwargs: real_connect(
                        *args,
                        timeout=0.05,
                        **kwargs,
                    ),
                ):
                    with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                        queue.initialize()
            finally:
                holder.rollback()
                holder.close()

            self.assertEqual(0, queue.count("intake_cases"))
            with sqlite3.connect(path) as connection:
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])

    def test_dynamic_queue_identifiers_are_restricted_to_exact_internal_allowlists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            queue = LocalQueue(Path(directory) / "allowlist.sqlite")
            queue.initialize()

            with self.assertRaisesRegex(ValueError, "Unsupported table"):
                queue.count("intake_cases; DROP TABLE intake_cases")
            with queue.session() as connection:
                with self.assertRaisesRegex(ValueError, "Unsupported queue JSON"):
                    queue._upsert_json(
                        connection,
                        "audit_events",
                        "payload_json",
                        "case-never-written",
                        "client-a",
                        "entity-a",
                        {},
                        "2026-07-11T08:00:00+00:00",
                    )

            self.assertEqual(0, queue.count("intake_cases"))

    def test_event_log_fsync_failure_leaves_a_detectable_fail_closed_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = HashChainedEventLog(Path(directory) / "events.jsonl")

            with patch("accounting_agent.evidence.os.fsync", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    log.append(
                        client_id="client-a",
                        event_type="synthetic.crash",
                        actor_id="qa",
                        object_id="case-1",
                        details={"fixture": True},
                    )

            verification = log.verify()
            self.assertFalse(verification.valid)
            self.assertIn("event_head_missing_or_invalid", verification.errors)
            with self.assertRaises(EvidenceIntegrityError):
                log.append(
                    client_id="client-a",
                    event_type="synthetic.retry",
                    actor_id="qa",
                    object_id="case-1",
                    details={},
                )


if __name__ == "__main__":
    unittest.main()
