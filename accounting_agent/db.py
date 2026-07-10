from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS intake_cases (
    case_id TEXT PRIMARY KEY,
    fixture_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
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

CREATE INDEX IF NOT EXISTS idx_documents_invoice_signature
    ON documents(invoice_signature);

CREATE TABLE IF NOT EXISTS extracted_fields (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounting_proposals (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    proposal_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_decisions (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    decision_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_packets (
    case_id TEXT PRIMARY KEY REFERENCES intake_cases(case_id),
    packet_json TEXT NOT NULL,
    packet_path TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT REFERENCES intake_cases(case_id),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class LocalQueue:
    """SQLite persistence for local MVP queue and audit records."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session() as connection:
            connection.executescript(SCHEMA_SQL)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def session(self) -> Any:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def find_duplicate_signature(
        self, invoice_signature: str, current_case_id: str
    ) -> dict[str, Any] | None:
        self.initialize()
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT case_id, source_path, supplier_name, invoice_number,
                       invoice_date, gross_amount, created_at
                FROM documents
                WHERE invoice_signature = ?
                ORDER BY created_at ASC, case_id ASC
                """,
                (invoice_signature,),
            ).fetchall()

        if not rows:
            return None

        first = dict(rows[0])
        for row in rows:
            if row["case_id"] == current_case_id:
                return None if first["case_id"] == current_case_id else first

        return first

    def store_pipeline_result(self, packet: dict[str, Any], packet_path: Path) -> None:
        self.initialize()
        now = packet["generated_at"]
        case = packet["case"]
        document = packet["document"]
        extracted = packet["extracted_fields"]

        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO intake_cases (
                    case_id, fixture_name, source_path, file_hash, status,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    fixture_name = excluded.fixture_name,
                    source_path = excluded.source_path,
                    file_hash = excluded.file_hash,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    case["case_id"],
                    case["fixture_name"],
                    case["source_path"],
                    case["file_hash"],
                    case["status"],
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO documents (
                    doc_hash, case_id, source_path, invoice_signature,
                    supplier_name, supplier_org_number, invoice_number,
                    invoice_date, gross_amount, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_hash) DO UPDATE SET
                    source_path = excluded.source_path,
                    invoice_signature = excluded.invoice_signature,
                    supplier_name = excluded.supplier_name,
                    supplier_org_number = excluded.supplier_org_number,
                    invoice_number = excluded.invoice_number,
                    invoice_date = excluded.invoice_date,
                    gross_amount = excluded.gross_amount,
                    updated_at = excluded.updated_at
                """,
                (
                    document["file_hash"],
                    case["case_id"],
                    case["source_path"],
                    document["invoice_signature"],
                    extracted.get("supplier_name"),
                    extracted.get("supplier_org_number"),
                    extracted.get("invoice_number"),
                    extracted.get("invoice_date"),
                    extracted["amounts"].get("gross"),
                    now,
                    now,
                ),
            )
            self._upsert_json(
                connection,
                "extracted_fields",
                "payload_json",
                case["case_id"],
                extracted,
                now,
            )
            self._upsert_json(
                connection,
                "accounting_proposals",
                "proposal_json",
                case["case_id"],
                packet["accounting_proposal"],
                now,
            )
            self._upsert_json(
                connection,
                "policy_decisions",
                "decision_json",
                case["case_id"],
                packet["policy_decision"],
                now,
            )
            connection.execute(
                """
                INSERT INTO approval_packets (
                    case_id, packet_json, packet_path, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    packet_json = excluded.packet_json,
                    packet_path = excluded.packet_path,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    case["case_id"],
                    _json(packet),
                    str(packet_path),
                    "pending_human_review",
                    now,
                ),
            )
            for event in packet["audit_events"]:
                connection.execute(
                    """
                    INSERT INTO audit_events (
                        case_id, event_type, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        case["case_id"],
                        event["event_type"],
                        _json(event["payload"]),
                        event["created_at"],
                    ),
                )

    def count(self, table_name: str) -> int:
        if table_name not in {
            "intake_cases",
            "documents",
            "extracted_fields",
            "accounting_proposals",
            "policy_decisions",
            "approval_packets",
            "audit_events",
        }:
            raise ValueError(f"Unsupported table: {table_name}")
        self.initialize()
        with self.session() as connection:
            row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"])

    @staticmethod
    def _upsert_json(
        connection: sqlite3.Connection,
        table_name: str,
        json_column: str,
        case_id: str,
        payload: dict[str, Any],
        updated_at: str,
    ) -> None:
        connection.execute(
            f"""
            INSERT INTO {table_name} (case_id, {json_column}, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                {json_column} = excluded.{json_column},
                updated_at = excluded.updated_at
            """,
            (case_id, _json(payload), updated_at),
        )


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
