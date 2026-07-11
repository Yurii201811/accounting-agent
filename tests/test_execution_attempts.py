from __future__ import annotations

import multiprocessing
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import accounting_agent
from accounting_agent.execution_attempts import (
    EXECUTION_ATTEMPT_SCHEMA_VERSION,
    ExecutionAttempt,
    ExecutionAttemptConflict,
    ExecutionAttemptError,
    ExecutionAttemptHumanReviewRequired,
    ExecutionAttemptIntegrityError,
    ExecutionAttemptScope,
    ExecutionAttemptSchemaError,
    ExecutionAttemptState,
    ExecutionAttemptTransitionError,
    SQLiteExecutionAttemptStore,
)


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
EXPECTED_ROOT_EXPORTS = (
    "EXECUTION_ATTEMPT_SCHEMA_VERSION",
    "ExecutionAttempt",
    "ExecutionAttemptConflict",
    "ExecutionAttemptError",
    "ExecutionAttemptHumanReviewRequired",
    "ExecutionAttemptIntegrityError",
    "ExecutionAttemptSchemaError",
    "ExecutionAttemptScope",
    "ExecutionAttemptState",
    "ExecutionAttemptTransitionError",
    "SQLiteExecutionAttemptStore",
)


def _scope(**overrides: str) -> ExecutionAttemptScope:
    values = {
        "permit_id": "permit-synthetic-1",
        "client_id": "synthetic-client",
        "entity_id": "synthetic-entity",
        "case_id": "case-synthetic-1",
        "provider_id": "fortnox-sandbox",
        "action": "create_unbooked_supplier_invoice_draft",
        "payload_hash": "a" * 64,
    }
    values.update(overrides)
    return ExecutionAttemptScope(**values)


def _reserve_worker(arguments: tuple[str, str, dict[str, str]]) -> tuple[str, str]:
    database, key, scope_values = arguments
    try:
        record = SQLiteExecutionAttemptStore(database).reserve(
            key,
            ExecutionAttemptScope(**scope_values),
            reserved_at=NOW,
        )
    except ExecutionAttemptConflict:
        return ("conflict", "")
    return ("ok", record.scope.digest)


class ExecutionAttemptScopeTests(unittest.TestCase):
    def test_execution_attempt_contracts_are_additive_root_exports(self) -> None:
        for export_name in EXPECTED_ROOT_EXPORTS:
            with self.subTest(export=export_name):
                self.assertIn(export_name, accounting_agent.__all__)
                self.assertIs(
                    getattr(accounting_agent, export_name),
                    globals()[export_name],
                )
        self.assertIs(accounting_agent.ExecutionAttemptError, ExecutionAttemptError)

    def test_scope_is_frozen_and_every_required_field_changes_its_digest(self) -> None:
        scope = _scope()

        with self.assertRaises(FrozenInstanceError):
            scope.case_id = "mutated"  # type: ignore[misc]

        alternatives = {
            "permit_id": "permit-synthetic-2",
            "client_id": "synthetic-client-2",
            "entity_id": "synthetic-entity-2",
            "case_id": "case-synthetic-2",
            "provider_id": "provider-synthetic-2",
            "action": "other_draft_action",
            "payload_hash": "b" * 64,
        }
        for field_name, value in alternatives.items():
            with self.subTest(field_name=field_name):
                self.assertNotEqual(scope.digest, replace(scope, **{field_name: value}).digest)

    def test_scope_rejects_blank_identity_and_non_sha256_payload(self) -> None:
        for field_name in (
            "permit_id",
            "client_id",
            "entity_id",
            "case_id",
            "provider_id",
            "action",
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaises((TypeError, ValueError)):
                    _scope(**{field_name: " "})
        with self.assertRaisesRegex(ValueError, "payload_hash"):
            _scope(payload_hash="not-a-sha256")

    def test_record_rejects_invalid_state_metadata_and_counters(self) -> None:
        base = {
            "idempotency_key": "idempotency-1",  # gitleaks:allow - test identifier
            "scope": _scope(),
            "state": ExecutionAttemptState.RESERVED,
            "created_at": NOW,
            "updated_at": NOW,
        }
        invalid_records = (
            ({"scope": object()}, TypeError, "scope"),
            ({"updated_at": NOW - timedelta(seconds=1)}, ValueError, "before"),
            ({"retry_count": True}, TypeError, "retry_count"),
            ({"retry_count": -1}, ValueError, "negative"),
            ({"response_hash": "b" * 64}, ValueError, "reserved"),
            (
                {"state": ExecutionAttemptState.COMPLETED},
                ValueError,
                "response hash and reference",
            ),
            (
                {
                    "state": ExecutionAttemptState.COMPLETED,
                    "response_hash": "b" * 64,
                    "response_reference": "provider-1",
                    "failure_reason": "should-not-coexist",
                },
                ValueError,
                "failure reason",
            ),
            ({"state": ExecutionAttemptState.FAILED}, ValueError, "failure reason"),
            (
                {
                    "state": ExecutionAttemptState.FAILED,
                    "failure_reason": "definitive",
                    "response_hash": "b" * 64,
                },
                ValueError,
                "response metadata",
            ),
            ({"state": ExecutionAttemptState.UNKNOWN}, ValueError, "ambiguity reason"),
        )
        for changes, error_type, message in invalid_records:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(error_type, message):
                    ExecutionAttempt(**(base | changes))

    def test_values_reject_non_text_controls_and_oversized_content(self) -> None:
        with self.assertRaisesRegex(TypeError, "permit_id"):
            _scope(permit_id=123)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "empty"):
            _scope(permit_id="")
        with self.assertRaisesRegex(ValueError, "control"):
            _scope(permit_id="permit\u0000id")
        with self.assertRaisesRegex(ValueError, "256"):
            _scope(permit_id="p" * 257)
        with self.assertRaisesRegex(TypeError, "payload_hash"):
            _scope(payload_hash=123)  # type: ignore[arg-type]


class SQLiteExecutionAttemptStoreTests(unittest.TestCase):
    def test_ephemeral_memory_database_is_rejected_for_durable_attempts(self) -> None:
        with self.assertRaisesRegex(ExecutionAttemptSchemaError, "durable file"):
            SQLiteExecutionAttemptStore(":memory:")

    def test_timeout_and_timestamp_contracts_fail_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "attempts.sqlite"
            with self.assertRaisesRegex(TypeError, "timeout"):
                SQLiteExecutionAttemptStore(database, timeout=True)
            with self.assertRaisesRegex(ValueError, "greater than zero"):
                SQLiteExecutionAttemptStore(database, timeout=0)

            store = SQLiteExecutionAttemptStore(database)
            with self.assertRaisesRegex(TypeError, "reserved_at"):
                store.reserve(
                    "idempotency-1",
                    _scope(),
                    reserved_at="not-a-datetime",  # type: ignore[arg-type]
                )
            with self.assertRaisesRegex(TypeError, "scope"):
                store.reserve("idempotency-1", object())  # type: ignore[arg-type]

            self.assertEqual(EXECUTION_ATTEMPT_SCHEMA_VERSION, store.schema_version())
            self.assertIsNone(store.get("idempotency-1"))

    def test_exact_replay_returns_the_original_record_without_retrying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            first = store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            replay = store.reserve(
                "idempotency-1",
                _scope(),
                reserved_at=NOW + timedelta(minutes=5),
            )

        self.assertEqual(first, replay)
        self.assertEqual(ExecutionAttemptState.RESERVED, replay.state)
        self.assertEqual(0, replay.retry_count)
        self.assertEqual(NOW, replay.created_at)
        self.assertEqual(NOW, replay.updated_at)

    def test_replay_with_any_scope_mismatch_fails_closed_and_keeps_original(self) -> None:
        alternatives = {
            "permit_id": "permit-synthetic-2",
            "client_id": "synthetic-client-2",
            "entity_id": "synthetic-entity-2",
            "case_id": "case-synthetic-2",
            "provider_id": "provider-synthetic-2",
            "action": "other_draft_action",
            "payload_hash": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            original = store.reserve("idempotency-1", _scope(), reserved_at=NOW)

            for field_name, value in alternatives.items():
                with self.subTest(field_name=field_name):
                    with self.assertRaisesRegex(ExecutionAttemptConflict, "scope"):
                        store.reserve(
                            "idempotency-1",
                            replace(_scope(), **{field_name: value}),
                        )
                    self.assertEqual(original, store.get("idempotency-1"))

    def test_completion_records_response_and_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            completed = store.complete(
                "idempotency-1",
                _scope(),
                response_hash="c" * 64,
                response_reference="sandbox-draft-123",
                completed_at=NOW + timedelta(seconds=1),
            )
            replay = store.complete(
                "idempotency-1",
                _scope(),
                response_hash="c" * 64,
                response_reference="sandbox-draft-123",
                completed_at=NOW + timedelta(minutes=1),
            )

            self.assertEqual(completed, replay)
            self.assertEqual(ExecutionAttemptState.COMPLETED, completed.state)
            self.assertEqual("c" * 64, completed.response_hash)
            self.assertEqual("sandbox-draft-123", completed.response_reference)
            self.assertFalse(completed.requires_human_review)
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "immutable"):
                store.complete(
                    "idempotency-1",
                    _scope(),
                    response_hash="d" * 64,
                    response_reference="sandbox-draft-456",
                )
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "immutable"):
                store.fail("idempotency-1", _scope(), reason="late transport error")
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "immutable"):
                store.retry_failed("idempotency-1", _scope())

    def test_failed_attempt_requires_explicit_retry_and_increments_retry_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            failed = store.fail(
                "idempotency-1",
                _scope(),
                reason="definitive_provider_rejection",
                failed_at=NOW + timedelta(seconds=1),
            )

            self.assertEqual(
                failed,
                store.fail(
                    "idempotency-1",
                    _scope(),
                    reason="definitive_provider_rejection",
                ),
            )
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "already recorded"):
                store.fail(
                    "idempotency-1",
                    _scope(),
                    reason="different_failure",
                )
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "explicitly retried"):
                store.complete(
                    "idempotency-1",
                    _scope(),
                    response_hash="c" * 64,
                    response_reference="impossible-reference",
                )

            replay = store.reserve(
                "idempotency-1",
                _scope(),
                reserved_at=NOW + timedelta(minutes=1),
            )
            retried = store.retry_failed(
                "idempotency-1",
                _scope(),
                reserved_at=NOW + timedelta(minutes=2),
            )

        self.assertEqual(failed, replay)
        self.assertEqual(ExecutionAttemptState.FAILED, failed.state)
        self.assertEqual("definitive_provider_rejection", failed.failure_reason)
        self.assertEqual(ExecutionAttemptState.RESERVED, retried.state)
        self.assertEqual(1, retried.retry_count)
        self.assertIsNone(retried.failure_reason)

    def test_ambiguous_result_is_terminal_and_requires_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            unknown = store.mark_unknown(
                "idempotency-1",
                _scope(),
                reason="timeout_after_request_body_sent",
                response_hash="d" * 64,
                response_reference="request-correlation-123",
                observed_at=NOW + timedelta(seconds=30),
            )
            replay = store.reserve("idempotency-1", _scope())

            exact_observation_replay = store.mark_unknown(
                "idempotency-1",
                _scope(),
                reason="timeout_after_request_body_sent",
                response_hash="d" * 64,
                response_reference="request-correlation-123",
            )

            self.assertEqual(unknown, replay)
            self.assertEqual(unknown, exact_observation_replay)
            self.assertEqual(ExecutionAttemptState.UNKNOWN, unknown.state)
            self.assertTrue(unknown.requires_human_review)
            with self.assertRaisesRegex(
                ExecutionAttemptHumanReviewRequired,
                "human review",
            ):
                store.retry_failed("idempotency-1", _scope())
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "immutable"):
                store.complete(
                    "idempotency-1",
                    _scope(),
                    response_hash="e" * 64,
                    response_reference="guessed-draft",
                )
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "immutable"):
                store.mark_unknown(
                    "idempotency-1",
                    _scope(),
                    reason="different_guess",
                )

    def test_unreserved_or_still_reserved_attempt_cannot_skip_protocol_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "not reserved"):
                store.fail("missing", _scope(), reason="definitive")

            store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            with self.assertRaisesRegex(ExecutionAttemptTransitionError, "definitively failed"):
                store.retry_failed("idempotency-1", _scope())

    def test_store_normalizes_aware_timestamps_to_utc_and_rejects_naive_time(self) -> None:
        cet = timezone(timedelta(hours=2))
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            record = store.reserve(
                "idempotency-1",
                _scope(),
                reserved_at=datetime(2026, 7, 11, 14, 0, tzinfo=cet),
            )
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                store.reserve(
                    "idempotency-2",
                    _scope(case_id="case-synthetic-2"),
                    reserved_at=datetime(2026, 7, 11, 12, 0),
                )

        self.assertEqual(NOW, record.created_at)
        self.assertIs(UTC, record.created_at.tzinfo)
        self.assertIs(UTC, record.updated_at.tzinfo)

    def test_transitions_reject_timestamps_before_the_last_durable_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            original = store.reserve("idempotency-1", _scope(), reserved_at=NOW)

            with self.assertRaisesRegex(ValueError, "before"):
                store.fail(
                    "idempotency-1",
                    _scope(),
                    reason="definitive_rejection",
                    failed_at=NOW - timedelta(seconds=1),
                )

            self.assertEqual(original, store.get("idempotency-1"))

    def test_future_schema_is_refused_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "future.sqlite"
            future_version = EXECUTION_ATTEMPT_SCHEMA_VERSION + 1
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(f"PRAGMA user_version = {future_version}")

            with self.assertRaisesRegex(ExecutionAttemptSchemaError, "newer"):
                SQLiteExecutionAttemptStore(database)

            with closing(sqlite3.connect(database)) as connection, connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            self.assertEqual(future_version, version)
            self.assertEqual([], tables)

    def test_current_version_missing_table_is_refused_without_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(f"PRAGMA user_version = {EXECUTION_ATTEMPT_SCHEMA_VERSION}")

            with self.assertRaisesRegex(ExecutionAttemptSchemaError, "missing"):
                SQLiteExecutionAttemptStore(database)

            with closing(sqlite3.connect(database)) as connection, connection:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            self.assertEqual([], tables)

    def test_current_version_constraintless_table_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "constraintless.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript(
                    f"""
                    CREATE TABLE execution_attempts (
                        idempotency_key TEXT,
                        permit_id TEXT,
                        client_id TEXT,
                        entity_id TEXT,
                        case_id TEXT,
                        provider_id TEXT,
                        action TEXT,
                        payload_hash TEXT,
                        scope_digest TEXT,
                        state TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        retry_count INTEGER,
                        response_hash TEXT,
                        response_reference TEXT,
                        failure_reason TEXT
                    );
                    PRAGMA user_version = {EXECUTION_ATTEMPT_SCHEMA_VERSION};
                    """
                )

            with self.assertRaisesRegex(ExecutionAttemptSchemaError, "structure"):
                SQLiteExecutionAttemptStore(database)

            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "INSERT INTO execution_attempts (idempotency_key) VALUES ('duplicate')"
                )
                connection.execute(
                    "INSERT INTO execution_attempts (idempotency_key) VALUES ('duplicate')"
                )
                count = connection.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0]
            self.assertEqual(2, count)

    def test_current_version_missing_safety_trigger_is_refused_not_healed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "missing-trigger.sqlite"
            SQLiteExecutionAttemptStore(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("DROP TRIGGER execution_attempt_terminal_immutable")

            with self.assertRaisesRegex(ExecutionAttemptSchemaError, "trigger"):
                SQLiteExecutionAttemptStore(database)

            with closing(sqlite3.connect(database)) as connection, connection:
                trigger = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                    ("execution_attempt_terminal_immutable",),
                ).fetchone()
            self.assertIsNone(trigger)

    def test_current_version_same_named_noop_trigger_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "noop-trigger.sqlite"
            SQLiteExecutionAttemptStore(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript(
                    """
                    DROP TRIGGER execution_attempt_terminal_immutable;
                    CREATE TRIGGER execution_attempt_terminal_immutable
                    BEFORE UPDATE ON execution_attempts
                    WHEN OLD.state IN ('completed', 'unknown') AND 0
                    BEGIN
                        SELECT RAISE(ABORT, 'terminal execution attempt is immutable');
                    END;
                    """
                )

            with self.assertRaisesRegex(ExecutionAttemptSchemaError, "trigger"):
                SQLiteExecutionAttemptStore(database)

    def test_incompatible_version_zero_table_is_refused_and_transaction_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "incompatible.sqlite"
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "CREATE TABLE execution_attempts (idempotency_key TEXT PRIMARY KEY)"
                )

            with self.assertRaisesRegex(ExecutionAttemptSchemaError, "supported schema"):
                SQLiteExecutionAttemptStore(database)

            with closing(sqlite3.connect(database)) as connection, connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                columns = connection.execute("PRAGMA table_info(execution_attempts)").fetchall()
            self.assertEqual(0, version)
            self.assertEqual(["idempotency_key"], [column[1] for column in columns])

    def test_database_failure_rolls_back_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "attempts.sqlite"
            store = SQLiteExecutionAttemptStore(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    """
                    CREATE TRIGGER synthetic_reservation_failure
                    AFTER INSERT ON execution_attempts
                    BEGIN
                        SELECT RAISE(ABORT, 'synthetic disk failure');
                    END
                    """
                )

            with self.assertRaisesRegex(sqlite3.IntegrityError, "synthetic disk failure"):
                store.reserve("idempotency-1", _scope(), reserved_at=NOW)

            self.assertIsNone(store.get("idempotency-1"))
            with closing(sqlite3.connect(database)) as connection, connection:
                count = connection.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0]
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(0, count)
            self.assertEqual("ok", integrity)

    def test_tampered_scope_digest_fails_closed_when_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "attempts.sqlite"
            store = SQLiteExecutionAttemptStore(database)
            store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("DROP TRIGGER execution_attempt_scope_immutable")
                connection.execute(
                    "UPDATE execution_attempts SET scope_digest = ? WHERE idempotency_key = ?",
                    ("0" * 64, "idempotency-1"),
                )

            with self.assertRaisesRegex(ExecutionAttemptIntegrityError, "digest"):
                store.get("idempotency-1")

    def test_invalid_durable_timestamp_fails_closed_when_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "attempts.sqlite"
            store = SQLiteExecutionAttemptStore(database)
            store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    "UPDATE execution_attempts SET created_at = ? WHERE idempotency_key = ?",
                    ("not-a-timestamp", "idempotency-1"),
                )

            with self.assertRaisesRegex(ExecutionAttemptIntegrityError, "invalid durable data"):
                store.get("idempotency-1")

    def test_fractional_retry_count_is_rejected_by_database_and_loader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "attempts.sqlite"
            store = SQLiteExecutionAttemptStore(database)
            store.reserve("idempotency-1", _scope(), reserved_at=NOW)
            with closing(sqlite3.connect(database)) as connection, connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE execution_attempts SET retry_count = 1.9 "
                        "WHERE idempotency_key = 'idempotency-1'"  # gitleaks:allow
                    )
                connection.execute("PRAGMA ignore_check_constraints = ON")
                connection.execute(
                    "UPDATE execution_attempts SET retry_count = 1.9 "
                    "WHERE idempotency_key = 'idempotency-1'"  # gitleaks:allow
                )

            with self.assertRaisesRegex(ExecutionAttemptIntegrityError, "invalid durable data"):
                store.get("idempotency-1")

    def test_database_triggers_block_terminal_update_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "attempts.sqlite"
            store = SQLiteExecutionAttemptStore(database)
            store.reserve("completed", _scope(), reserved_at=NOW)
            store.complete(
                "completed",
                _scope(),
                response_hash="c" * 64,
                response_reference="provider-123",
            )
            store.reserve(
                "unknown",
                _scope(case_id="case-synthetic-2", payload_hash="b" * 64),
                reserved_at=NOW,
            )
            store.mark_unknown(
                "unknown",
                _scope(case_id="case-synthetic-2", payload_hash="b" * 64),
                reason="timeout_after_send",
            )

            with closing(sqlite3.connect(database)) as connection, connection:
                for key in ("completed", "unknown"):
                    with self.subTest(operation="update", key=key):
                        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                            connection.execute(
                                "UPDATE execution_attempts SET retry_count = 99 "
                                "WHERE idempotency_key = ?",
                                (key,),
                            )
                    with self.subTest(operation="delete", key=key):
                        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                            connection.execute(
                                "DELETE FROM execution_attempts WHERE idempotency_key = ?",
                                (key,),
                            )

    def test_response_hash_must_be_sha256_and_reference_must_be_nonblank(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteExecutionAttemptStore(Path(directory) / "attempts.sqlite")
            store.reserve("idempotency-1", _scope(), reserved_at=NOW)

            with self.assertRaisesRegex(ValueError, "response_hash"):
                store.complete(
                    "idempotency-1",
                    _scope(),
                    response_hash="invalid",
                    response_reference="sandbox-draft-123",
                )
            with self.assertRaisesRegex(ValueError, "response_reference"):
                store.complete(
                    "idempotency-1",
                    _scope(),
                    response_hash="c" * 64,
                    response_reference=" ",
                )

            self.assertEqual(ExecutionAttemptState.RESERVED, store.get("idempotency-1").state)


class SQLiteExecutionAttemptMultiprocessTests(unittest.TestCase):
    def test_exact_scope_race_returns_one_durable_record_to_every_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "attempts.sqlite")
            SQLiteExecutionAttemptStore(database)
            scope_values = _scope().to_dict()
            context = multiprocessing.get_context("spawn")
            with context.Pool(processes=4) as pool:
                outcomes = pool.map(
                    _reserve_worker,
                    ((database, "shared-key", scope_values) for _ in range(8)),
                )

            self.assertEqual({("ok", _scope().digest)}, set(outcomes))
            with closing(sqlite3.connect(database)) as connection, connection:
                count = connection.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0]
            self.assertEqual(1, count)

    def test_mismatched_scope_race_allows_only_one_scope_for_a_shared_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "attempts.sqlite")
            SQLiteExecutionAttemptStore(database)
            inputs = tuple(
                (
                    database,
                    "shared-key",
                    _scope(
                        permit_id=f"permit-{index}",
                        case_id=f"case-{index}",
                        payload_hash=f"{index:x}" * 64,
                    ).to_dict(),
                )
                for index in range(1, 5)
            )
            context = multiprocessing.get_context("spawn")
            with context.Pool(processes=4) as pool:
                outcomes = pool.map(_reserve_worker, inputs)

            self.assertEqual(1, sum(outcome[0] == "ok" for outcome in outcomes), outcomes)
            self.assertEqual(3, sum(outcome[0] == "conflict" for outcome in outcomes), outcomes)
            with closing(sqlite3.connect(database)) as connection, connection:
                count = connection.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()[0]
            self.assertEqual(1, count)


if __name__ == "__main__":
    unittest.main()
