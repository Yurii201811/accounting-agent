"""Durable, fail-closed execution-attempt reservations.

This module records intent and observed outcomes.  It does not perform provider
calls and deliberately exposes no transport or external-write capability.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from .client_identity import canonical_client_id


EXECUTION_ATTEMPT_SCHEMA_VERSION = 1

_SCOPE_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS execution_attempt_scope_immutable
BEFORE UPDATE OF
    idempotency_key, permit_id, client_id, entity_id, case_id,
    provider_id, action, payload_hash, scope_digest
ON execution_attempts
BEGIN
    SELECT RAISE(ABORT, 'execution attempt scope is immutable');
END
"""

_TERMINAL_IMMUTABLE_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS execution_attempt_terminal_immutable
BEFORE UPDATE ON execution_attempts
WHEN OLD.state IN ('completed', 'unknown')
BEGIN
    SELECT RAISE(ABORT, 'terminal execution attempt is immutable');
END
"""

_TERMINAL_DELETE_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS execution_attempt_terminal_delete_forbidden
BEFORE DELETE ON execution_attempts
WHEN OLD.state IN ('completed', 'unknown')
BEGIN
    SELECT RAISE(ABORT, 'terminal execution attempt is immutable');
END
"""

_STATE_TRANSITION_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS execution_attempt_state_transition_valid
BEFORE UPDATE OF state ON execution_attempts
WHEN NOT (
    (OLD.state = 'reserved' AND NEW.state IN ('completed', 'failed', 'unknown'))
    OR (OLD.state = 'failed' AND NEW.state = 'reserved')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid execution attempt state transition');
END
"""

_TRIGGER_SQL = {
    "execution_attempt_scope_immutable": _SCOPE_IMMUTABLE_TRIGGER_SQL,
    "execution_attempt_terminal_immutable": _TERMINAL_IMMUTABLE_TRIGGER_SQL,
    "execution_attempt_terminal_delete_forbidden": _TERMINAL_DELETE_TRIGGER_SQL,
    "execution_attempt_state_transition_valid": _STATE_TRANSITION_TRIGGER_SQL,
}


class ExecutionAttemptError(RuntimeError):
    """Base class for durable execution-attempt failures."""


class ExecutionAttemptConflict(ExecutionAttemptError):
    """Raised when an idempotency key is replayed with a different scope."""


class ExecutionAttemptTransitionError(ExecutionAttemptError):
    """Raised when an attempt cannot make the requested state transition."""


class ExecutionAttemptHumanReviewRequired(ExecutionAttemptTransitionError):
    """Raised when an ambiguous provider outcome must be resolved by a person."""


class ExecutionAttemptSchemaError(ExecutionAttemptError):
    """Raised when the SQLite schema cannot be used without unsafe guessing."""


class ExecutionAttemptIntegrityError(ExecutionAttemptError):
    """Raised when a durable row does not match its immutable scope digest."""


class ExecutionAttemptState(str, Enum):
    RESERVED = "reserved"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExecutionAttemptScope:
    """The exact authority and provider payload bound to one reservation."""

    permit_id: str
    client_id: str
    entity_id: str
    case_id: str
    provider_id: str
    action: str
    payload_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "permit_id", _canonical_text(self.permit_id, "permit_id"))
        object.__setattr__(self, "client_id", canonical_client_id(self.client_id))
        object.__setattr__(self, "entity_id", canonical_client_id(self.entity_id))
        object.__setattr__(self, "case_id", _canonical_text(self.case_id, "case_id"))
        object.__setattr__(self, "provider_id", _canonical_text(self.provider_id, "provider_id"))
        object.__setattr__(self, "action", _canonical_text(self.action, "action"))
        _require_sha256(self.payload_hash, "payload_hash")

    @property
    def digest(self) -> str:
        material = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def to_dict(self) -> dict[str, str]:
        return {
            "permit_id": self.permit_id,
            "client_id": self.client_id,
            "entity_id": self.entity_id,
            "case_id": self.case_id,
            "provider_id": self.provider_id,
            "action": self.action,
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class ExecutionAttempt:
    """One durable execution reservation and its latest trusted state."""

    idempotency_key: str
    scope: ExecutionAttemptScope
    state: ExecutionAttemptState
    created_at: datetime
    updated_at: datetime
    retry_count: int = 0
    response_hash: str | None = None
    response_reference: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "idempotency_key",
            _canonical_text(self.idempotency_key, "idempotency_key"),
        )
        if not isinstance(self.scope, ExecutionAttemptScope):
            raise TypeError("scope must be an ExecutionAttemptScope")
        object.__setattr__(self, "state", ExecutionAttemptState(self.state))
        object.__setattr__(self, "created_at", _as_utc(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _as_utc(self.updated_at, "updated_at"))
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot be before created_at")
        if isinstance(self.retry_count, bool) or not isinstance(self.retry_count, int):
            raise TypeError("retry_count must be an integer")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if self.response_hash is not None:
            _require_sha256(self.response_hash, "response_hash")
        if self.response_reference is not None:
            object.__setattr__(
                self,
                "response_reference",
                _canonical_text(self.response_reference, "response_reference", limit=1024),
            )
        if self.failure_reason is not None:
            object.__setattr__(
                self,
                "failure_reason",
                _canonical_text(self.failure_reason, "failure_reason", limit=1024),
            )
        self._validate_state_metadata()

    @property
    def requires_human_review(self) -> bool:
        return self.state is ExecutionAttemptState.UNKNOWN

    def _validate_state_metadata(self) -> None:
        if self.state is ExecutionAttemptState.RESERVED:
            if any(
                value is not None
                for value in (
                    self.response_hash,
                    self.response_reference,
                    self.failure_reason,
                )
            ):
                raise ValueError("reserved attempts cannot carry outcome metadata")
        elif self.state is ExecutionAttemptState.COMPLETED:
            if self.response_hash is None or self.response_reference is None:
                raise ValueError("completed attempts require a response hash and reference")
            if self.failure_reason is not None:
                raise ValueError("completed attempts cannot carry a failure reason")
        elif self.state is ExecutionAttemptState.FAILED:
            if self.failure_reason is None:
                raise ValueError("failed attempts require a failure reason")
            if self.response_hash is not None or self.response_reference is not None:
                raise ValueError("definitive failures cannot carry response metadata")
        elif self.failure_reason is None:
            raise ValueError("unknown attempts require an ambiguity reason")


class SQLiteExecutionAttemptStore:
    """SQLite reservation store with atomic scope binding and terminal outcomes."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        timeout: float = 5.0,
    ) -> None:
        raw_database_path = str(database_path)
        if raw_database_path in {"", ":memory:"}:
            raise ExecutionAttemptSchemaError(
                "Execution attempts require a durable file-backed SQLite database"
            )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a number")
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.database_path = raw_database_path
        self.clock = clock or _utc_now
        self.timeout = float(timeout)
        self.initialize()

    def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > EXECUTION_ATTEMPT_SCHEMA_VERSION:
                raise ExecutionAttemptSchemaError(
                    "Execution-attempt schema is newer than this runtime; refusing downgrade"
                )
            try:
                connection.execute("BEGIN IMMEDIATE")
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version > EXECUTION_ATTEMPT_SCHEMA_VERSION:
                    raise ExecutionAttemptSchemaError(
                        "Execution-attempt schema is newer than this runtime; refusing downgrade"
                    )
                if version == 0:
                    if self._table_exists(connection):
                        raise ExecutionAttemptSchemaError(
                            "Execution-attempt table does not match the supported schema: "
                            "an unversioned table already exists"
                        )
                    self._install_schema(connection)
                    self._validate_schema(connection)
                    connection.execute(f"PRAGMA user_version = {EXECUTION_ATTEMPT_SCHEMA_VERSION}")
                else:
                    self._validate_schema(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def schema_version(self) -> int:
        with closing(self._connect()) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def get(self, idempotency_key: str) -> ExecutionAttempt | None:
        key = _canonical_text(idempotency_key, "idempotency_key")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM execution_attempts WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def reserve(
        self,
        idempotency_key: str,
        scope: ExecutionAttemptScope,
        *,
        reserved_at: datetime | None = None,
    ) -> ExecutionAttempt:
        key = _canonical_text(idempotency_key, "idempotency_key")
        scope = _require_scope(scope)
        timestamp = self._timestamp(reserved_at, "reserved_at")
        with self._transaction() as connection:
            existing = self._load(connection, key)
            if existing is not None:
                _require_exact_scope(existing, scope)
                return existing
            connection.execute(
                """
                INSERT INTO execution_attempts (
                    idempotency_key, permit_id, client_id, entity_id, case_id,
                    provider_id, action, payload_hash, scope_digest, state,
                    created_at, updated_at, retry_count, response_hash,
                    response_reference, failure_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL)
                """,
                (
                    key,
                    scope.permit_id,
                    scope.client_id,
                    scope.entity_id,
                    scope.case_id,
                    scope.provider_id,
                    scope.action,
                    scope.payload_hash,
                    scope.digest,
                    ExecutionAttemptState.RESERVED.value,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            return self._load_required(connection, key)

    def complete(
        self,
        idempotency_key: str,
        scope: ExecutionAttemptScope,
        *,
        response_hash: str,
        response_reference: str,
        completed_at: datetime | None = None,
    ) -> ExecutionAttempt:
        _require_sha256(response_hash, "response_hash")
        reference = _canonical_text(
            response_reference,
            "response_reference",
            limit=1024,
        )
        key = _canonical_text(idempotency_key, "idempotency_key")
        scope = _require_scope(scope)
        timestamp = self._timestamp(completed_at, "completed_at")
        with self._transaction() as connection:
            existing = self._load_required(connection, key)
            _require_exact_scope(existing, scope)
            if existing.state is ExecutionAttemptState.COMPLETED:
                if (
                    existing.response_hash == response_hash
                    and existing.response_reference == reference
                ):
                    return existing
                raise ExecutionAttemptTransitionError("completed execution attempts are immutable")
            _require_mutable_reserved(existing)
            _require_monotonic(timestamp, existing.updated_at)
            connection.execute(
                """
                UPDATE execution_attempts
                SET state = ?, updated_at = ?, response_hash = ?, response_reference = ?
                WHERE idempotency_key = ?
                """,
                (
                    ExecutionAttemptState.COMPLETED.value,
                    timestamp.isoformat(),
                    response_hash,
                    reference,
                    key,
                ),
            )
            return self._load_required(connection, key)

    def fail(
        self,
        idempotency_key: str,
        scope: ExecutionAttemptScope,
        *,
        reason: str,
        failed_at: datetime | None = None,
    ) -> ExecutionAttempt:
        failure_reason = _canonical_text(reason, "failure_reason", limit=1024)
        key = _canonical_text(idempotency_key, "idempotency_key")
        scope = _require_scope(scope)
        timestamp = self._timestamp(failed_at, "failed_at")
        with self._transaction() as connection:
            existing = self._load_required(connection, key)
            _require_exact_scope(existing, scope)
            if existing.state is ExecutionAttemptState.FAILED:
                if existing.failure_reason == failure_reason:
                    return existing
                raise ExecutionAttemptTransitionError(
                    "failed outcome is already recorded; retry explicitly before replacing it"
                )
            _require_mutable_reserved(existing)
            _require_monotonic(timestamp, existing.updated_at)
            connection.execute(
                """
                UPDATE execution_attempts
                SET state = ?, updated_at = ?, failure_reason = ?
                WHERE idempotency_key = ?
                """,
                (
                    ExecutionAttemptState.FAILED.value,
                    timestamp.isoformat(),
                    failure_reason,
                    key,
                ),
            )
            return self._load_required(connection, key)

    def mark_unknown(
        self,
        idempotency_key: str,
        scope: ExecutionAttemptScope,
        *,
        reason: str,
        response_hash: str | None = None,
        response_reference: str | None = None,
        observed_at: datetime | None = None,
    ) -> ExecutionAttempt:
        ambiguity_reason = _canonical_text(reason, "failure_reason", limit=1024)
        if response_hash is not None:
            _require_sha256(response_hash, "response_hash")
        reference = (
            _canonical_text(response_reference, "response_reference", limit=1024)
            if response_reference is not None
            else None
        )
        key = _canonical_text(idempotency_key, "idempotency_key")
        scope = _require_scope(scope)
        timestamp = self._timestamp(observed_at, "observed_at")
        with self._transaction() as connection:
            existing = self._load_required(connection, key)
            _require_exact_scope(existing, scope)
            if existing.state is ExecutionAttemptState.UNKNOWN:
                if (
                    existing.failure_reason == ambiguity_reason
                    and existing.response_hash == response_hash
                    and existing.response_reference == reference
                ):
                    return existing
                raise ExecutionAttemptTransitionError(
                    "unknown execution attempts are immutable pending human review"
                )
            _require_mutable_reserved(existing)
            _require_monotonic(timestamp, existing.updated_at)
            connection.execute(
                """
                UPDATE execution_attempts
                SET state = ?, updated_at = ?, response_hash = ?,
                    response_reference = ?, failure_reason = ?
                WHERE idempotency_key = ?
                """,
                (
                    ExecutionAttemptState.UNKNOWN.value,
                    timestamp.isoformat(),
                    response_hash,
                    reference,
                    ambiguity_reason,
                    key,
                ),
            )
            return self._load_required(connection, key)

    def retry_failed(
        self,
        idempotency_key: str,
        scope: ExecutionAttemptScope,
        *,
        reserved_at: datetime | None = None,
    ) -> ExecutionAttempt:
        key = _canonical_text(idempotency_key, "idempotency_key")
        scope = _require_scope(scope)
        timestamp = self._timestamp(reserved_at, "reserved_at")
        with self._transaction() as connection:
            existing = self._load_required(connection, key)
            _require_exact_scope(existing, scope)
            if existing.state is ExecutionAttemptState.UNKNOWN:
                raise ExecutionAttemptHumanReviewRequired(
                    "unknown execution outcome requires human review; automatic retry is forbidden"
                )
            if existing.state is ExecutionAttemptState.COMPLETED:
                raise ExecutionAttemptTransitionError("completed execution attempts are immutable")
            if existing.state is not ExecutionAttemptState.FAILED:
                raise ExecutionAttemptTransitionError(
                    "only a definitively failed execution attempt can be retried"
                )
            _require_monotonic(timestamp, existing.updated_at)
            connection.execute(
                """
                UPDATE execution_attempts
                SET state = ?, updated_at = ?, retry_count = retry_count + 1,
                    response_hash = NULL, response_reference = NULL,
                    failure_reason = NULL
                WHERE idempotency_key = ?
                """,
                (ExecutionAttemptState.RESERVED.value, timestamp.isoformat(), key),
            )
            return self._load_required(connection, key)

    def _timestamp(self, value: datetime | None, name: str) -> datetime:
        return _as_utc(value if value is not None else self.clock(), name)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _load(
        self,
        connection: sqlite3.Connection,
        idempotency_key: str,
    ) -> ExecutionAttempt | None:
        row = connection.execute(
            "SELECT * FROM execution_attempts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return _record_from_row(row) if row is not None else None

    def _load_required(
        self,
        connection: sqlite3.Connection,
        idempotency_key: str,
    ) -> ExecutionAttempt:
        record = self._load(connection, idempotency_key)
        if record is None:
            raise ExecutionAttemptTransitionError("execution attempt is not reserved")
        return record

    @staticmethod
    def _install_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_attempts (
                idempotency_key TEXT PRIMARY KEY,
                permit_id TEXT NOT NULL,
                client_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                scope_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN ('reserved', 'completed', 'failed', 'unknown')
                ),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0 CHECK (
                    retry_count >= 0 AND typeof(retry_count) = 'integer'
                ),
                response_hash TEXT,
                response_reference TEXT,
                failure_reason TEXT
            ) WITHOUT ROWID
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS execution_attempt_scope_lookup
            ON execution_attempts(client_id, entity_id, case_id)
            """
        )
        for trigger_ddl in _TRIGGER_SQL.values():
            connection.execute(trigger_ddl)

    @staticmethod
    def _table_exists(connection: sqlite3.Connection) -> bool:
        return (
            connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'execution_attempts'
                """
            ).fetchone()
            is not None
        )

    @classmethod
    def _validate_schema(cls, connection: sqlite3.Connection) -> None:
        table_row = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'execution_attempts'
            """
        ).fetchone()
        if table_row is None:
            raise ExecutionAttemptSchemaError(
                "Current execution-attempt schema is missing its durable table"
            )

        expected_columns = (
            ("idempotency_key", "TEXT", 1, None, 1),
            ("permit_id", "TEXT", 1, None, 0),
            ("client_id", "TEXT", 1, None, 0),
            ("entity_id", "TEXT", 1, None, 0),
            ("case_id", "TEXT", 1, None, 0),
            ("provider_id", "TEXT", 1, None, 0),
            ("action", "TEXT", 1, None, 0),
            ("payload_hash", "TEXT", 1, None, 0),
            ("scope_digest", "TEXT", 1, None, 0),
            ("state", "TEXT", 1, None, 0),
            ("created_at", "TEXT", 1, None, 0),
            ("updated_at", "TEXT", 1, None, 0),
            ("retry_count", "INTEGER", 1, "0", 0),
            ("response_hash", "TEXT", 0, None, 0),
            ("response_reference", "TEXT", 0, None, 0),
            ("failure_reason", "TEXT", 0, None, 0),
        )
        actual_columns = tuple(
            (str(row[1]), str(row[2]).upper(), int(row[3]), row[4], int(row[5]))
            for row in connection.execute("PRAGMA table_info(execution_attempts)").fetchall()
        )
        table_sql = _normalize_sql(str(table_row[0]))
        required_table_fragments = (
            "without rowid",
            "state text not null check",
            "state in ('reserved', 'completed', 'failed', 'unknown')",
            "retry_count >= 0 and typeof(retry_count) = 'integer'",
        )
        if actual_columns != expected_columns or any(
            fragment not in table_sql for fragment in required_table_fragments
        ):
            raise ExecutionAttemptSchemaError(
                "Execution-attempt table structure does not match the supported schema"
            )

        index_columns = tuple(
            str(row[2])
            for row in connection.execute(
                "PRAGMA index_info(execution_attempt_scope_lookup)"
            ).fetchall()
        )
        if index_columns != ("client_id", "entity_id", "case_id"):
            raise ExecutionAttemptSchemaError(
                "Execution-attempt scope index does not match the supported schema"
            )

        trigger_rows = connection.execute(
            """
            SELECT name, sql FROM sqlite_master
            WHERE type = 'trigger' AND tbl_name = 'execution_attempts'
            """
        ).fetchall()
        trigger_sql = {str(row[0]): _normalize_sql(str(row[1])) for row in trigger_rows}
        expected_trigger_sql = {
            name: _normalize_sql(ddl).replace(
                "create trigger if not exists",
                "create trigger",
                1,
            )
            for name, ddl in _TRIGGER_SQL.items()
        }
        if trigger_sql != expected_trigger_sql:
            raise ExecutionAttemptSchemaError(
                "Execution-attempt safety trigger definitions do not match the supported schema"
            )


def _record_from_row(row: sqlite3.Row) -> ExecutionAttempt:
    try:
        raw_retry_count = row["retry_count"]
        if isinstance(raw_retry_count, bool) or not isinstance(raw_retry_count, int):
            raise TypeError("durable retry_count must be an integer")
        scope = ExecutionAttemptScope(
            permit_id=str(row["permit_id"]),
            client_id=str(row["client_id"]),
            entity_id=str(row["entity_id"]),
            case_id=str(row["case_id"]),
            provider_id=str(row["provider_id"]),
            action=str(row["action"]),
            payload_hash=str(row["payload_hash"]),
        )
        stored_digest = str(row["scope_digest"])
        if stored_digest != scope.digest:
            raise ExecutionAttemptIntegrityError(
                "execution attempt scope digest does not match its durable fields"
            )
        return ExecutionAttempt(
            idempotency_key=str(row["idempotency_key"]),
            scope=scope,
            state=ExecutionAttemptState(str(row["state"])),
            created_at=_parse_datetime(str(row["created_at"])),
            updated_at=_parse_datetime(str(row["updated_at"])),
            retry_count=raw_retry_count,
            response_hash=(str(row["response_hash"]) if row["response_hash"] is not None else None),
            response_reference=(
                str(row["response_reference"]) if row["response_reference"] is not None else None
            ),
            failure_reason=(
                str(row["failure_reason"]) if row["failure_reason"] is not None else None
            ),
        )
    except ExecutionAttemptIntegrityError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutionAttemptIntegrityError(
            "execution attempt row contains invalid durable data"
        ) from exc


def _require_scope(value: ExecutionAttemptScope) -> ExecutionAttemptScope:
    if not isinstance(value, ExecutionAttemptScope):
        raise TypeError("scope must be an ExecutionAttemptScope")
    return value


def _require_exact_scope(
    existing: ExecutionAttempt,
    expected: ExecutionAttemptScope,
) -> None:
    if existing.scope != expected:
        raise ExecutionAttemptConflict(
            "idempotency key is already bound to a different execution scope"
        )


def _require_mutable_reserved(existing: ExecutionAttempt) -> None:
    if existing.state in {ExecutionAttemptState.COMPLETED, ExecutionAttemptState.UNKNOWN}:
        raise ExecutionAttemptTransitionError(
            f"{existing.state.value} execution attempts are immutable"
        )
    if existing.state is not ExecutionAttemptState.RESERVED:
        raise ExecutionAttemptTransitionError(
            "failed execution attempts must be explicitly retried before a new outcome"
        )


def _require_monotonic(candidate: datetime, previous: datetime) -> None:
    if candidate < previous:
        raise ValueError("execution attempt timestamp cannot be before its last durable change")


def _canonical_text(value: str, name: str, *, limit: int = 256) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if value != value.strip():
        raise ValueError(f"{name} must not contain leading or trailing whitespace")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{name} must not contain control or invisible format characters")
    if len(normalized.encode("utf-8")) > limit:
        raise ValueError(f"{name} must not exceed {limit} UTF-8 bytes")
    return normalized


def _require_sha256(value: str, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _as_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_datetime(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value), "durable timestamp")


def _normalize_sql(value: str) -> str:
    return " ".join(value.lower().split())


def _utc_now() -> datetime:
    return datetime.now(UTC)
