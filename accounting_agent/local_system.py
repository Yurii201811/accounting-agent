"""Durable local synthetic accounting workflow.

This module joins the existing fixture pipelines behind one SQLite application
boundary.  It records review outcomes only; it never issues approvals, permits,
messages, payments, filings, or live accounting writes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from contextlib import ExitStack, contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from accounting_agent.bank_reconciliation import (
    BankReconciliationPipeline,
    BankTransaction,
    MatchTarget,
)
from accounting_agent.client_identity import canonical_client_id
from accounting_agent.local_locks import try_run_lease
from accounting_agent.fake_client_dry_run import build_fake_client_month
from accounting_agent.supplier_invoice import SupplierInvoicePipeline
from accounting_agent.supplier_invoice.extraction import extract_invoice_fields


SCHEMA_VERSION = 1
DATABASE_SCHEMA_VERSION = 1
SYNTHETIC_CLIENT_ID = "synthetic_client"
SYNTHETIC_ENTITY_ID = "synthetic_entity"
REVIEW_OUTCOMES = frozenset({"reviewed", "needs_changes", "rejected"})


class LocalSystemConflict(RuntimeError):
    """Raised for idempotency or optimistic-concurrency conflicts."""


class LocalSystemSchemaError(RuntimeError):
    """Raised when an existing local-system database is incompatible."""


class LocalAccountingSystem:
    """Persist one synthetic intake-to-review workflow under ``data_dir``."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = self.data_dir / "local_accounting_system.sqlite"
        self._initialize()
        self._recover_interrupted_runs()

    def sample_bundle(self) -> dict[str, Any]:
        return sample_bundle()

    def health(self) -> dict[str, Any]:
        """Check database readiness without changing runs or exposing evidence."""
        with self._session() as connection:
            self._validate_database_schema(connection)
            if connection.execute("PRAGMA user_version").fetchone()[0] != DATABASE_SCHEMA_VERSION:
                raise RuntimeError("Workspace database schema version is not supported")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Workspace storage integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("Workspace storage contains invalid record references")
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("runs", "cases", "reviews", "audit_events")
            }
        return {"status": "ready", "environment": "synthetic_local",
                "database_schema_version": DATABASE_SCHEMA_VERSION,
                "live_actions_enabled": False, "storage_counts": counts}

    def create_run(
        self,
        bundle: Mapping[str, Any],
        request_key: str,
    ) -> dict[str, Any]:
        with ExitStack() as cleanup:
            return self._create_run(bundle, request_key, cleanup)

    def _create_run(self, bundle: Mapping[str, Any], request_key: str, cleanup: ExitStack) -> dict[str, Any]:
        request_key = _required_text(request_key, "request_key")
        canonical_bundle = _canonical_mapping(bundle, "bundle")
        bundle_json = _canonical_json(canonical_bundle)
        bundle_hash = _sha256_text(bundle_json)

        with self._session(immediate=True) as connection:
            existing = connection.execute(
                "SELECT run_id, bundle_hash FROM runs WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            if existing is not None:
                if existing["bundle_hash"] != bundle_hash:
                    raise LocalSystemConflict(
                        "request_key is already bound to different bundle content"
                    )
                run_id = str(existing["run_id"])
            else:
                run_id = f"run_{uuid.uuid4().hex}"
                lease = try_run_lease(self.data_dir, run_id)
                if lease is None:
                    raise LocalSystemConflict("Could not claim the new processing run")
                cleanup.callback(lease.close)
                created_at = _utc_now()
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, request_key, bundle_hash, bundle_json, name,
                        client_id, entity_id, created_at, updated_at, status,
                        owner_pid, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        run_id,
                        request_key,
                        bundle_hash,
                        bundle_json,
                        str(canonical_bundle.get("name") or ""),
                        str(canonical_bundle.get("client_id") or ""),
                        str(canonical_bundle.get("entity_id") or ""),
                        created_at,
                        created_at,
                        "processing",
                        os.getpid(),
                    ),
                )
                self._insert_audit(
                    connection,
                    run_id=run_id,
                    case_id=None,
                    event_type="run_created",
                    payload={"bundle_hash": bundle_hash, "request_key": request_key},
                    created_at=created_at,
                )
        if existing is not None:
            self._recover_interrupted_runs()
            return self.get_run(run_id)

        try:
            validated = _validate_bundle(canonical_bundle)
            case_rows = self._process_bundle(run_id, validated)
            for attempt in range(3):
                try:
                    self._complete_run(run_id, validated, case_rows)
                    break
                except sqlite3.OperationalError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except (sqlite3.OperationalError, LocalSystemConflict):
            # Do not turn a transient persistence failure into invalid input.
            # Releasing the OS lease makes this recoverable on replay/startup.
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failed_at = _utc_now()
            with self._session(immediate=True) as connection:
                updated = connection.execute(
                    """
                    UPDATE runs
                    SET status = 'failed', owner_pid = NULL, error = ?, updated_at = ?
                    WHERE run_id = ? AND status = 'processing'
                    """,
                    (error, failed_at, run_id),
                )
                if updated.rowcount == 1:
                    self._insert_audit(
                        connection,
                        run_id=run_id,
                        case_id=None,
                        event_type="run_failed",
                        payload={"error": error},
                        created_at=failed_at,
                    )
            raise
        return self.get_run(run_id)

    def _complete_run(self, run_id: str, validated: dict[str, Any], case_rows: list[dict[str, Any]]) -> None:
        completed_at = _utc_now()
        with self._session(immediate=True) as connection:
            current = connection.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if current is None or current["status"] != "processing":
                raise LocalSystemConflict("Run is no longer owned for processing")
            for row in case_rows:
                connection.execute(
                    """
                    INSERT INTO cases (
                        run_id, case_id, kind, policy_mode, packet_json,
                        evidence_hash, review_status, review_revision,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        run_id,
                        row["case_id"],
                        row["kind"],
                        row["policy_mode"],
                        _canonical_json(row["packet"]),
                        row["evidence_hash"],
                        row["review_status"],
                        completed_at,
                        completed_at,
                    ),
                )
            connection.execute(
                """
                UPDATE runs
                SET name = ?, client_id = ?, entity_id = ?,
                    status = 'completed', owner_pid = NULL,
                    error = NULL, updated_at = ?
                WHERE run_id = ? AND status = 'processing'
                """,
                (
                    validated["name"],
                    validated["client_id"],
                    validated["entity_id"],
                    completed_at,
                    run_id,
                ),
            )
            self._insert_audit(
                connection,
                run_id=run_id,
                case_id=None,
                event_type="run_completed",
                payload={"case_count": len(case_rows)},
                created_at=completed_at,
            )

    def list_runs(self) -> list[dict[str, Any]]:
        with self._session() as connection:
            rows = connection.execute(
                """
                SELECT r.run_id, r.name, r.client_id, r.entity_id, r.created_at,
                       r.updated_at, r.status, r.error, r.bundle_hash,
                       COUNT(c.case_id) AS case_count
                FROM runs AS r
                LEFT JOIN cases AS c ON c.run_id = r.run_id
                GROUP BY r.run_id
                ORDER BY r.created_at DESC, r.run_id DESC
                """
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "name": row["name"],
                "client_id": row["client_id"],
                "entity_id": row["entity_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "status": row["status"],
                "error": row["error"],
                "bundle_hash": row["bundle_hash"],
                "case_count": int(row["case_count"]),
            }
            for row in rows
        ]

    def get_run(self, run_id: str) -> dict[str, Any]:
        run_id = _required_text(run_id, "run_id")
        with self._session() as connection:
            snapshot = self._export_snapshot(connection, run_id)
        cases = snapshot["cases"]
        counts: dict[str, int] = {}
        for case in cases:
            counts[case["review_status"]] = counts.get(case["review_status"], 0) + 1
        return {**snapshot["run"], "cases": cases, "audit": snapshot["audit"],
                "integrity_verified": snapshot["integrity_verified"],
                "integrity_errors": snapshot["integrity_errors"],
                "counts": {"total": len(cases), "by_review_status": counts}}

    def get_case(self, run_id: str, case_id: str) -> dict[str, Any]:
        run_id = _required_text(run_id, "run_id")
        case_id = _required_text(case_id, "case_id")
        with self._session() as connection:
            self._require_run(connection, run_id)
            row = connection.execute(
                "SELECT * FROM cases WHERE run_id = ? AND case_id = ?",
                (run_id, case_id),
            ).fetchone()
            reviews = self._reviews_for_case(connection, run_id, case_id)
            integrity = self._export_snapshot(connection, run_id)
        if row is None:
            raise KeyError(case_id)
        case = _case_from_row(row)
        case["reviews"] = reviews
        case["review_history"] = reviews
        case["integrity_verified"] = integrity["integrity_verified"]
        case["integrity_errors"] = integrity["integrity_errors"]
        return case

    def record_review(
        self,
        run_id: str,
        case_id: str,
        *,
        outcome: str,
        note: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        run_id = _required_text(run_id, "run_id")
        case_id = _required_text(case_id, "case_id")
        outcome = _required_text(outcome, "outcome")
        if outcome not in REVIEW_OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(REVIEW_OUTCOMES)}")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise ValueError("expected_revision must be an integer")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("note must be a non-empty string")
        note = note.strip()
        if len(note) > 2_000:
            raise ValueError("note must be at most 2000 characters")

        decided_at = _utc_now()
        with self._session(immediate=True) as connection:
            self._require_run(connection, run_id)
            if not self._export_snapshot(connection, run_id)["integrity_verified"]:
                raise LocalSystemConflict("Stored evidence is inconsistent; review is blocked")
            row = connection.execute(
                "SELECT * FROM cases WHERE run_id = ? AND case_id = ?",
                (run_id, case_id),
            ).fetchone()
            if row is None:
                raise KeyError(case_id)
            if int(row["review_revision"]) != expected_revision:
                raise LocalSystemConflict("review revision has changed")
            if row["policy_mode"] == "forbidden" and outcome == "reviewed":
                raise ValueError("a forbidden case cannot be marked reviewed")
            revision = expected_revision + 1
            decision = {
                "run_id": run_id,
                "case_id": case_id,
                "revision": revision,
                "outcome": outcome,
                "note": note,
                "actor": "local_operator",
                "evidence_hash": row["evidence_hash"],
                "policy_mode": row["policy_mode"],
                "decided_at": decided_at,
            }
            decision_hash = _hash_payload(decision)
            connection.execute(
                """
                INSERT INTO reviews (
                    run_id, case_id, revision, outcome, note, actor,
                    evidence_hash, policy_mode, decision_hash, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    case_id,
                    revision,
                    outcome,
                    note,
                    "local_operator",
                    row["evidence_hash"],
                    row["policy_mode"],
                    decision_hash,
                    decided_at,
                ),
            )
            connection.execute(
                """
                UPDATE cases
                SET review_status = ?, review_revision = ?, updated_at = ?
                WHERE run_id = ? AND case_id = ?
                """,
                (outcome, revision, decided_at, run_id, case_id),
            )
            self._insert_audit(
                connection,
                run_id=run_id,
                case_id=case_id,
                event_type="review_recorded",
                payload={
                    "revision": revision,
                    "outcome": outcome,
                    "actor": "local_operator",
                    "evidence_hash": row["evidence_hash"],
                    "decision_hash": decision_hash,
                    "policy_mode_unchanged": row["policy_mode"],
                },
                created_at=decided_at,
            )
        return self.get_case(run_id, case_id)

    def export_run(self, run_id: str) -> dict[str, Any]:
        run_id = _required_text(run_id, "run_id")
        with self._session() as connection:
            return self._export_snapshot(connection, run_id)

    def _export_snapshot(self, connection: sqlite3.Connection, run_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        cases = self._list_cases(connection, run_id)
        reviews = [dict(item) for item in connection.execute(
            "SELECT * FROM reviews WHERE run_id = ? ORDER BY decided_at, case_id, revision", (run_id,)
        ).fetchall()]
        audit = self._audit_for_run(connection, run_id)
        run = {
            "run_id": row["run_id"],
            "name": row["name"],
            "client_id": row["client_id"],
            "entity_id": row["entity_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "error": row["error"],
            "bundle_hash": row["bundle_hash"],
        }
        payload = {
            "schema_version": SCHEMA_VERSION,
            "synthetic": True,
            "bundle": json.loads(row["bundle_json"]),
            "run": run,
            "cases": cases,
            "reviews": reviews,
            "audit": audit,
        }
        integrity_errors = _integrity_errors(
            bundle_json=row["bundle_json"],
            bundle_hash=row["bundle_hash"],
            cases=cases,
            reviews=reviews,
            audit=audit,
            run_id=run_id,
            run_status=run["status"],
        )
        payload["integrity_verified"] = not integrity_errors
        payload["integrity_errors"] = integrity_errors
        return {**payload, "content_hash": _hash_payload(payload)}

    def _process_bundle(
        self,
        run_id: str,
        bundle: dict[str, Any],
    ) -> list[dict[str, Any]]:
        evaluation_date = date.fromisoformat(bundle["evaluation_date"])
        rows: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix=f"{run_id}-") as temp:
            fixture_root = Path(temp)
            supplier_pipeline = SupplierInvoicePipeline(
                db_path=None,
                output_dir=None,
                client_id=bundle["client_id"],
                entity_id=bundle["entity_id"],
                enable_shadow_ledger=False,
                evaluation_date=evaluation_date,
            )
            for index, fixture in enumerate(bundle["supplier_invoices"]):
                fixture_path = fixture_root / f"supplier-{index:04d}.json"
                fixture_path.write_text(
                    json.dumps(fixture, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                packet = supplier_pipeline.process_fixture(fixture_path)
                packet = _stable_supplier_packet(packet, index)
                rows.append(_case_row("supplier_invoice", packet))

        bank_pipeline = BankReconciliationPipeline(
            output_dir=None,
            client_id=bundle["client_id"],
        )
        bank_packets = bank_pipeline.process(
            [BankTransaction.from_dict(item) for item in bundle["bank_transactions"]],
            [MatchTarget.from_dict(item) for item in bundle["open_items"]],
        )
        rows.extend(_case_row("bank_reconciliation", packet) for packet in bank_packets)
        case_ids = [row["case_id"] for row in rows]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("pipeline produced duplicate case identifiers")
        return rows

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            database_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            expected_tables = {"runs", "cases", "reviews", "audit_events"}
            existing_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            existing_app_tables = expected_tables & existing_tables
            if database_version == 0 and existing_app_tables:
                # The first local prototype created the complete sequenced-audit
                # schema without a user_version. Preserve those successful runs
                # through the sole supported additive upgrade.
                connection.execute("BEGIN IMMEDIATE")
                database_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                if database_version == 0:
                    self._validate_database_schema(
                        connection,
                        allow_missing_owner_pid=True,
                    )
                    run_columns = {
                        str(row[1])
                        for row in connection.execute(
                            "PRAGMA table_info(runs)"
                        ).fetchall()
                    }
                    if "owner_pid" not in run_columns:
                        connection.execute(
                            "ALTER TABLE runs ADD COLUMN owner_pid INTEGER"
                        )
                    connection.execute(
                        f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}"
                    )
                    database_version = DATABASE_SCHEMA_VERSION
            if database_version not in (0, DATABASE_SCHEMA_VERSION):
                raise LocalSystemSchemaError(
                    "unsupported local-system database schema version "
                    f"{database_version}; expected {DATABASE_SCHEMA_VERSION}"
                )

            if database_version == 0:
                connection.executescript(
                    f"""
                BEGIN IMMEDIATE;

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    request_key TEXT NOT NULL UNIQUE,
                    bundle_hash TEXT NOT NULL,
                    bundle_json TEXT NOT NULL,
                    name TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner_pid INTEGER,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS cases (
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    case_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    policy_mode TEXT NOT NULL,
                    packet_json TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    review_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, case_id)
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    note TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    policy_mode TEXT NOT NULL,
                    decision_hash TEXT NOT NULL UNIQUE,
                    decided_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, case_id, revision),
                    FOREIGN KEY (run_id, case_id) REFERENCES cases(run_id, case_id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    case_id TEXT,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    UNIQUE (run_id, sequence)
                );

                PRAGMA user_version = {DATABASE_SCHEMA_VERSION};
                COMMIT;
                    """
                )
                database_version = DATABASE_SCHEMA_VERSION

            self._validate_database_schema(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_database_schema(
        connection: sqlite3.Connection,
        *,
        allow_missing_owner_pid: bool = False,
    ) -> None:
        required_columns = {
            "runs": {
                "run_id",
                "request_key",
                "bundle_hash",
                "bundle_json",
                "name",
                "client_id",
                "entity_id",
                "created_at",
                "updated_at",
                "status",
                "owner_pid",
                "error",
            },
            "cases": {
                "run_id",
                "case_id",
                "kind",
                "policy_mode",
                "packet_json",
                "evidence_hash",
                "review_status",
                "review_revision",
                "created_at",
                "updated_at",
            },
            "reviews": {
                "run_id",
                "case_id",
                "revision",
                "outcome",
                "note",
                "actor",
                "evidence_hash",
                "policy_mode",
                "decision_hash",
                "decided_at",
            },
            "audit_events": {
                "event_id",
                "run_id",
                "case_id",
                "sequence",
                "event_type",
                "payload_json",
                "event_hash",
                "created_at",
            },
        }
        if allow_missing_owner_pid:
            required_columns["runs"].remove("owner_pid")
        for table_name, expected in required_columns.items():
            actual = {
                str(row[1])
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            missing = sorted(expected - actual)
            if missing:
                fields = ", ".join(f"{table_name}.{column}" for column in missing)
                raise LocalSystemSchemaError(
                    "incompatible local-system database schema; missing " + fields
                )

    def _recover_interrupted_runs(self) -> None:
        """Recover workers whose OS lease is absent, independent of PID reuse."""
        with self._session(immediate=True) as connection:
            rows = connection.execute(
                "SELECT run_id FROM runs WHERE status = 'processing' ORDER BY created_at, run_id"
            ).fetchall()
            for row in rows:
                run_id = str(row["run_id"])
                try:
                    lease = try_run_lease(self.data_dir, run_id)
                except OSError:
                    connection.execute(
                        "UPDATE runs SET error = ? WHERE run_id = ? AND status = 'processing'",
                        ("Run ownership could not be checked; inspect workspace permissions.", run_id),
                    )
                    continue
                if lease is None:
                    continue
                try:
                    error = "Processing was interrupted before cases were committed; submit a new request key to retry."
                    recovered_at = _utc_now()
                    updated = connection.execute(
                        "UPDATE runs SET status = 'interrupted', owner_pid = NULL, error = ?, updated_at = ? "
                        "WHERE run_id = ? AND status = 'processing'",
                        (error, recovered_at, run_id),
                    )
                    if updated.rowcount == 1:
                        self._insert_audit(connection, run_id=run_id, case_id=None,
                                           event_type="run_interrupted", payload={"error": error},
                                           created_at=recovered_at)
                finally:
                    lease.close()

    def _list_cases(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM cases WHERE run_id = ? ORDER BY kind, case_id",
            (run_id,),
        ).fetchall()
        return [_case_from_row(row) for row in rows]

    @staticmethod
    def _reviews_for_case(
        connection: sqlite3.Connection,
        run_id: str,
        case_id: str,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM reviews
                WHERE run_id = ? AND case_id = ?
                ORDER BY revision
                """,
                (run_id, case_id),
            ).fetchall()
        ]

    @staticmethod
    def _audit_for_run(
        connection: sqlite3.Connection,
        run_id: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "event_id": row["event_id"],
                "case_id": row["case_id"],
                "sequence": int(row["sequence"]),
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "event_hash": row["event_hash"],
                "created_at": row["created_at"],
            }
            for row in connection.execute(
                "SELECT * FROM audit_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        ]

    @staticmethod
    def _require_run(connection: sqlite3.Connection, run_id: str) -> None:
        row = connection.execute(
            "SELECT 1 FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        case_id: str | None,
        event_type: str,
        payload: Mapping[str, Any],
        created_at: str,
    ) -> None:
        event_id = f"audit_{uuid.uuid4().hex}"
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM audit_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
        )
        material = {
            "event_id": event_id,
            "run_id": run_id,
            "case_id": case_id,
            "sequence": sequence,
            "event_type": event_type,
            "payload": dict(payload),
            "created_at": created_at,
        }
        connection.execute(
            """
            INSERT INTO audit_events (
                event_id, run_id, case_id, sequence, event_type,
                payload_json, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                case_id,
                sequence,
                event_type,
                _canonical_json(payload),
                _hash_payload(material),
                created_at,
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _session(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def sample_bundle() -> dict[str, Any]:
    """Return the built-in 35-case synthetic month without filesystem fixtures."""

    month = build_fake_client_month()
    profile = month["profile"]
    bank = month["bank_reconciliation"]
    return {
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "name": f"{profile['display_name']} · {profile['accounting_period']}",
        "client_id": SYNTHETIC_CLIENT_ID,
        "entity_id": SYNTHETIC_ENTITY_ID,
        "evaluation_date": "2026-05-31",
        "supplier_invoices": month["supplier_invoices"],
        "bank_transactions": bank["bank_transactions"],
        "open_items": bank["open_items"],
    }


def _validate_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    if bundle.get("synthetic") is not True:
        raise ValueError("only explicitly synthetic bundles are accepted")
    name = _required_text(bundle.get("name"), "name")
    client_id = canonical_client_id(_required_text(bundle.get("client_id"), "client_id"))
    entity_id = canonical_client_id(_required_text(bundle.get("entity_id"), "entity_id"))
    if client_id != SYNTHETIC_CLIENT_ID or entity_id != SYNTHETIC_ENTITY_ID:
        raise ValueError("bundle must use the fixed synthetic client and entity scopes")
    evaluation_date = _required_text(bundle.get("evaluation_date"), "evaluation_date")
    date.fromisoformat(evaluation_date)
    supplier_invoices = _mapping_list(bundle.get("supplier_invoices"), "supplier_invoices")
    bank_transactions = _mapping_list(bundle.get("bank_transactions"), "bank_transactions")
    open_items = _mapping_list(bundle.get("open_items"), "open_items")
    for name_, items in (
        ("supplier_invoices", supplier_invoices),
        ("bank_transactions", bank_transactions),
        ("open_items", open_items),
    ):
        if len(items) > 200:
            raise ValueError(f"{name_} must contain at most 200 items")
    for fixture in supplier_invoices:
        extract_invoice_fields(fixture)
    for transaction in bank_transactions:
        _require_integer(transaction.get("amount_minor"), "bank transaction amount_minor")
    for target in open_items:
        _require_integer(target.get("amount_minor"), "open item amount_minor")
        if target.get("remaining_amount_minor") is not None:
            _require_integer(
                target["remaining_amount_minor"],
                "open item remaining_amount_minor",
            )
    transactions = [BankTransaction.from_dict(item) for item in bank_transactions]
    targets = [MatchTarget.from_dict(item) for item in open_items]
    _validate_bank_identifiers(transactions, targets)
    if not supplier_invoices and not bank_transactions:
        raise ValueError("bundle must contain at least one synthetic accounting item")
    return {
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "name": name,
        "client_id": client_id,
        "entity_id": entity_id,
        "evaluation_date": evaluation_date,
        "supplier_invoices": supplier_invoices,
        "bank_transactions": bank_transactions,
        "open_items": open_items,
    }


def _validate_bank_identifiers(
    transactions: list[BankTransaction],
    targets: list[MatchTarget],
) -> None:
    transaction_ids = [item.transaction_id for item in transactions]
    target_ids = [item.target_id for item in targets]
    for values, label in ((transaction_ids, "transaction"), (target_ids, "open item")):
        if any(not value.strip() for value in values):
            raise ValueError(f"{label} identifiers must be non-empty")
        if len(values) != len(set(values)):
            raise ValueError(f"{label} identifiers must be unique")
    packet_keys = [re.sub(r"[^A-Za-z0-9_.-]+", "_", item).casefold() for item in transaction_ids]
    if len(packet_keys) != len(set(packet_keys)):
        raise ValueError("transaction identifiers must produce unique packet names")


def _case_row(kind: str, packet: dict[str, Any]) -> dict[str, Any]:
    case_id = str(packet["case"]["case_id"])
    policy_mode = str(packet["policy_decision"]["mode"])
    evidence_hash = _hash_payload({"kind": kind, "case_id": case_id, "packet": packet})
    return {
        "case_id": case_id,
        "kind": kind,
        "policy_mode": policy_mode,
        "packet": packet,
        "evidence_hash": evidence_hash,
        "review_status": "not_required" if policy_mode == "draft_only" else "unreviewed",
    }


def _stable_supplier_packet(packet: dict[str, Any], index: int) -> dict[str, Any]:
    stable = copy.deepcopy(packet)
    stable["case"]["source_path"] = f"synthetic://supplier_invoice/{index}"
    stable["packet_path"] = None
    return stable


def _case_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "kind": row["kind"],
        "policy_mode": row["policy_mode"],
        "packet": json.loads(row["packet_json"]),
        "evidence_hash": row["evidence_hash"],
        "review_status": row["review_status"],
        "review_revision": int(row["review_revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _integrity_errors(
    *,
    bundle_json: str,
    bundle_hash: str,
    cases: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    run_id: str,
    run_status: str,
) -> list[str]:
    errors: list[str] = []
    if _sha256_text(bundle_json) != bundle_hash:
        errors.append("bundle_hash_mismatch")
    for case in cases:
        expected = _hash_payload(
            {
                "kind": case["kind"],
                "case_id": case["case_id"],
                "packet": case["packet"],
            }
        )
        if expected != case["evidence_hash"]:
            errors.append(f"case_evidence_hash_mismatch:{case['case_id']}")
    for review in reviews:
        material = {
            "run_id": review["run_id"],
            "case_id": review["case_id"],
            "revision": int(review["revision"]),
            "outcome": review["outcome"],
            "note": review["note"],
            "actor": review["actor"],
            "evidence_hash": review["evidence_hash"],
            "policy_mode": review["policy_mode"],
            "decided_at": review["decided_at"],
        }
        if _hash_payload(material) != review["decision_hash"]:
            errors.append(
                f"review_decision_hash_mismatch:{review['case_id']}:{review['revision']}"
            )
    for event in audit:
        material = {
            "event_id": event["event_id"],
            "run_id": run_id,
            "case_id": event["case_id"],
            "sequence": int(event["sequence"]),
            "event_type": event["event_type"],
            "payload": event["payload"],
            "created_at": event["created_at"],
        }
        if _hash_payload(material) != event["event_hash"]:
            errors.append(f"audit_event_hash_mismatch:{event['event_id']}")
    # Hashes must agree with related records and the complete run lifecycle.
    by_case = {case["case_id"]: case for case in cases}
    for case in cases:
        case_id = case["case_id"]
        packet = case["packet"]
        if packet.get("policy_decision", {}).get("mode") != case["policy_mode"]:
            errors.append(f"case_policy_mismatch:{case_id}")
        if packet.get("case", {}).get("case_id") != case_id:
            errors.append(f"case_identity_mismatch:{case_id}")
        history = sorted((r for r in reviews if r["case_id"] == case_id), key=lambda r: r["revision"])
        if [r["revision"] for r in history] != list(range(1, len(history) + 1)):
            errors.append(f"review_revision_gap:{case_id}")
        expected_status = history[-1]["outcome"] if history else (
            "not_required" if case["policy_mode"] == "draft_only" else "unreviewed")
        if case["review_revision"] != len(history) or case["review_status"] != expected_status:
            errors.append(f"case_review_state_mismatch:{case_id}")
        if case["policy_mode"] == "forbidden" and (
                case["review_status"] == "reviewed" or any(r["outcome"] == "reviewed" for r in history)):
            errors.append(f"forbidden_case_reviewed:{case_id}")
    for review in reviews:
        case = by_case.get(review["case_id"])
        if (case is None or review["run_id"] != run_id
                or review["evidence_hash"] != case["evidence_hash"]
                or review["policy_mode"] != case["policy_mode"]):
            errors.append(f"review_evidence_binding_mismatch:{review['case_id']}:{review['revision']}")
        events = [event for event in audit if event["event_type"] == "review_recorded"
                  and event["case_id"] == review["case_id"]
                  and event["payload"].get("decision_hash") == review["decision_hash"]]
        if len(events) != 1 or any(events[0]["payload"].get(key) != review[key]
                                  for key in ("revision", "outcome", "actor", "evidence_hash")):
            errors.append(f"review_audit_mismatch:{review['case_id']}:{review['revision']}")
    if [event["sequence"] for event in audit] != list(range(1, len(audit) + 1)):
        errors.append("audit_sequence_gap")
    starts = [e for e in audit if e["event_type"] == "run_created"]
    if (len(starts) != 1 or not audit or audit[0]["event_type"] != "run_created"
            or starts[0]["payload"].get("bundle_hash") != bundle_hash):
        errors.append("run_creation_audit_mismatch")
    terminal = [e for e in audit if e["event_type"] in {"run_completed", "run_failed", "run_interrupted"}]
    if run_status == "processing":
        if terminal or cases or reviews:
            errors.append("processing_run_state_mismatch")
    elif (run_status not in {"completed", "failed", "interrupted"} or len(terminal) != 1
          or terminal[0]["event_type"] != f"run_{run_status}"):
        errors.append("run_terminal_audit_mismatch")
    elif run_status == "completed":
        if terminal[0]["payload"].get("case_count") != len(cases):
            errors.append("completed_case_count_mismatch")
    elif cases or reviews:
        errors.append("failed_run_has_cases")
    review_hashes = {r["decision_hash"] for r in reviews}
    for event in audit:
        if event["event_type"] == "review_recorded" and (
                event["case_id"] not in by_case or event["payload"].get("decision_hash") not in review_hashes):
            errors.append(f"orphan_review_audit:{event['event_id']}")
    return errors


def _mapping_list(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{name} must contain objects")
    return [dict(item) for item in value]


def _canonical_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    try:
        return json.loads(_canonical_json(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only JSON values") from exc


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _require_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash_payload(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
