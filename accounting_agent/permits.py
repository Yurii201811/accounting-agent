"""Execution permits for policy-approved external writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .policy import (
    EXTERNAL_WRITE_ACTIONS,
    ActionType,
    PermissionMode,
    PolicyContext,
    PolicyDecision,
    evaluate_policy,
)


class PermitError(Exception):
    """Base class for execution permit failures."""


class PermitForbidden(PermitError):
    """Raised when a forbidden policy decision is used to request a permit."""


class PermitReviewRequired(PermitError):
    """Raised when required reviews have not been supplied."""


class PermitValidationError(PermitError):
    """Raised when an execution permit does not match the attempted write."""


@dataclass(frozen=True)
class ExecutionPermit:
    permit_id: str
    case_id: str
    client_id: str
    allowed_action: ActionType
    payload_hash: str
    policy_version: str
    required_reviews: tuple[str, ...]
    permission_mode: PermissionMode
    expires_at: datetime
    idempotency_key: str
    issued_at: datetime
    approved_reviews: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_action"] = self.allowed_action.value
        data["permission_mode"] = self.permission_mode.value
        data["expires_at"] = self.expires_at.isoformat()
        data["issued_at"] = self.issued_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionPermit":
        return cls(
            permit_id=str(data["permit_id"]),
            case_id=str(data["case_id"]),
            client_id=str(data["client_id"]),
            allowed_action=ActionType(data["allowed_action"]),
            payload_hash=str(data["payload_hash"]),
            policy_version=str(data["policy_version"]),
            required_reviews=tuple(data.get("required_reviews", ())),
            permission_mode=PermissionMode(data["permission_mode"]),
            expires_at=_parse_datetime(data["expires_at"]),
            idempotency_key=str(data["idempotency_key"]),
            issued_at=_parse_datetime(data["issued_at"]),
            approved_reviews=tuple(data.get("approved_reviews", ())),
        )


class PermitStore(Protocol):
    def save(self, permit: ExecutionPermit) -> None:
        ...

    def get(self, permit_id: str) -> ExecutionPermit | None:
        ...


class InMemoryPermitStore:
    def __init__(self) -> None:
        self._permits: dict[str, ExecutionPermit] = {}

    def save(self, permit: ExecutionPermit) -> None:
        self._permits[permit.permit_id] = permit

    def get(self, permit_id: str) -> ExecutionPermit | None:
        return self._permits.get(permit_id)


class SQLitePermitStore:
    """Small SQLite-compatible permit store for local development and tests."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._ensure_schema()

    def save(self, permit: ExecutionPermit) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO execution_permits (
                        permit_id,
                        case_id,
                        client_id,
                        allowed_action,
                        payload_hash,
                        policy_version,
                        required_reviews,
                        permission_mode,
                        expires_at,
                        idempotency_key,
                        issued_at,
                        approved_reviews
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        permit.permit_id,
                        permit.case_id,
                        permit.client_id,
                        permit.allowed_action.value,
                        permit.payload_hash,
                        permit.policy_version,
                        json.dumps(list(permit.required_reviews), separators=(",", ":")),
                        permit.permission_mode.value,
                        permit.expires_at.isoformat(),
                        permit.idempotency_key,
                        permit.issued_at.isoformat(),
                        json.dumps(list(permit.approved_reviews), separators=(",", ":")),
                    ),
                )

    def get(self, permit_id: str) -> ExecutionPermit | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT *
                FROM execution_permits
                WHERE permit_id = ?
                """,
                (permit_id,),
            ).fetchone()
        if row is None:
            return None
        return ExecutionPermit.from_dict(
            {
                "permit_id": row["permit_id"],
                "case_id": row["case_id"],
                "client_id": row["client_id"],
                "allowed_action": row["allowed_action"],
                "payload_hash": row["payload_hash"],
                "policy_version": row["policy_version"],
                "required_reviews": tuple(json.loads(row["required_reviews"])),
                "permission_mode": row["permission_mode"],
                "expires_at": row["expires_at"],
                "idempotency_key": row["idempotency_key"],
                "issued_at": row["issued_at"],
                "approved_reviews": tuple(json.loads(row["approved_reviews"])),
            }
        )

    def _ensure_schema(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS execution_permits (
                        permit_id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        allowed_action TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        policy_version TEXT NOT NULL,
                        required_reviews TEXT NOT NULL,
                        permission_mode TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        issued_at TEXT NOT NULL,
                        approved_reviews TEXT NOT NULL
                    )
                    """
                )


class PermitIssuer:
    def __init__(
        self,
        store: PermitStore | None = None,
        *,
        clock: Any | None = None,
        id_factory: Any | None = None,
        ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        self.store = store
        self.clock = clock or _utc_now
        self.id_factory = id_factory or (lambda: f"permit_{uuid.uuid4().hex}")
        self.ttl = ttl

    def issue(
        self,
        *,
        decision: PolicyDecision,
        context: PolicyContext,
        case_id: str,
        payload: Any,
        approved_reviews: tuple[str, ...] = (),
    ) -> ExecutionPermit:
        if decision.permission_mode is PermissionMode.FORBIDDEN:
            raise PermitForbidden("forbidden policy decisions cannot receive execution permits")
        if decision.action_type != context.action_type:
            raise PermitValidationError("policy decision action does not match policy context")
        if decision.client_id != context.client_id:
            raise PermitValidationError("policy decision client does not match policy context")
        _require_current_policy_decision(decision, context)

        missing_reviews = sorted(set(decision.required_reviews) - set(approved_reviews))
        if missing_reviews:
            raise PermitReviewRequired(
                "missing required reviews: " + ", ".join(missing_reviews)
            )

        now = self.clock()
        payload_hash = canonical_payload_hash(payload)
        permit = ExecutionPermit(
            permit_id=str(self.id_factory()),
            case_id=case_id,
            client_id=context.client_id,
            allowed_action=decision.action_type,
            payload_hash=payload_hash,
            policy_version=decision.policy_version,
            required_reviews=decision.required_reviews,
            permission_mode=decision.permission_mode,
            expires_at=now + self.ttl,
            idempotency_key=_idempotency_key(
                case_id=case_id,
                action_type=decision.action_type,
                payload_hash=payload_hash,
                policy_version=decision.policy_version,
            ),
            issued_at=now,
            approved_reviews=tuple(approved_reviews),
        )
        if self.store is not None:
            self.store.save(permit)
        return permit


class PermitValidator:
    def __init__(self, *, accepted_policy_version: str | None = None, clock: Any | None = None) -> None:
        self.accepted_policy_version = accepted_policy_version
        self.clock = clock or _utc_now

    def require_valid(
        self,
        *,
        permit: ExecutionPermit | None,
        case_id: str,
        action_type: ActionType,
        payload: Any,
    ) -> None:
        if permit is None:
            raise PermitValidationError("external writes require an execution permit")
        action_type = ActionType(action_type)
        if not permit.permit_id.strip():
            raise PermitValidationError("execution permit id is required")
        if not permit.case_id.strip():
            raise PermitValidationError("execution permit case_id is required")
        if not permit.client_id.strip():
            raise PermitValidationError("execution permit client_id is required")
        if not permit.idempotency_key.strip():
            raise PermitValidationError("execution permit idempotency key is required")
        if permit.allowed_action not in EXTERNAL_WRITE_ACTIONS:
            raise PermitValidationError("execution permit action is not an external write")
        if permit.permission_mode in {PermissionMode.AUTO_ALLOWED, PermissionMode.FORBIDDEN}:
            raise PermitValidationError(
                f"execution permit mode {permit.permission_mode.value} is not valid for writes"
            )
        if (
            permit.permission_mode
            in {PermissionMode.APPROVAL_REQUIRED, PermissionMode.ESCALATION_REQUIRED}
            and not permit.required_reviews
        ):
            raise PermitValidationError(
                "reviewed execution permits must include required review types"
            )
        if permit.permission_mode is PermissionMode.FORBIDDEN:
            raise PermitValidationError("forbidden permits are never valid")
        if permit.case_id != case_id:
            raise PermitValidationError("permit case_id does not match attempted write")
        if permit.allowed_action != action_type:
            raise PermitValidationError("permit action does not match attempted write")
        if permit.issued_at >= permit.expires_at:
            raise PermitValidationError("execution permit expiry must be after issue time")
        if permit.expires_at <= self.clock():
            raise PermitValidationError("execution permit has expired")
        if self.accepted_policy_version is not None:
            if permit.policy_version != self.accepted_policy_version:
                raise PermitValidationError("execution permit policy version is not accepted")
        payload_hash = canonical_payload_hash(payload)
        if permit.payload_hash != payload_hash:
            raise PermitValidationError("permit payload hash does not match attempted write")
        expected_idempotency_key = _idempotency_key(
            case_id=case_id,
            action_type=action_type,
            payload_hash=payload_hash,
            policy_version=permit.policy_version,
        )
        if permit.idempotency_key != expected_idempotency_key:
            raise PermitValidationError(
                "execution permit idempotency key does not match attempted write"
            )

        missing_reviews = sorted(set(permit.required_reviews) - set(permit.approved_reviews))
        if missing_reviews:
            raise PermitValidationError(
                "execution permit is missing approved reviews: " + ", ".join(missing_reviews)
            )


def canonical_payload_hash(payload: Any) -> str:
    serialized = json.dumps(
        _to_jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _require_current_policy_decision(
    decision: PolicyDecision,
    context: PolicyContext,
) -> None:
    expected = evaluate_policy(context)
    mismatches: list[str] = []
    if decision.permission_mode != expected.permission_mode:
        mismatches.append("permission_mode")
    if decision.policy_version != expected.policy_version:
        mismatches.append("policy_version")
    if decision.required_reviews != expected.required_reviews:
        mismatches.append("required_reviews")
    if decision.is_external_write != expected.is_external_write:
        mismatches.append("is_external_write")
    if mismatches:
        raise PermitValidationError(
            "policy decision does not match current policy evaluation: "
            + ", ".join(mismatches)
        )


def _idempotency_key(
    *,
    case_id: str,
    action_type: ActionType,
    payload_hash: str,
    policy_version: str,
) -> str:
    material = f"{case_id}:{action_type.value}:{payload_hash}:{policy_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _to_jsonable(value: Any) -> Any:
    if dataclass_is_instance(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_to_jsonable(item) for item in value]
    return value


def dataclass_is_instance(value: Any) -> bool:
    return hasattr(value, "__dataclass_fields__") and not isinstance(value, type)


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _utc_now() -> datetime:
    return datetime.now(UTC)
