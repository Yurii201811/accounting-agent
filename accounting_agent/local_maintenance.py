"""Verified backup/restore for the synthetic local workspace; no live services."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from contextlib import closing
from pathlib import Path

from accounting_agent.local_system import DATABASE_SCHEMA_VERSION, LocalAccountingSystem

DATABASE_NAME = "local_accounting_system.sqlite"
BACKUP_VERSION = 1
MAX_BACKUP_BYTES = 64 * 1024 * 1024


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)


def _verify_snapshot(directory: Path) -> dict:
    database = directory / DATABASE_NAME
    with closing(_readonly(database)) as connection:
        if connection.execute("PRAGMA user_version").fetchone()[0] != DATABASE_SCHEMA_VERSION:
            raise ValueError("Backup database schema version is not supported")
        LocalAccountingSystem._validate_database_schema(connection)
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Backup database failed SQLite integrity checks")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Backup database contains invalid record references")
        if connection.execute("SELECT COUNT(*) FROM runs WHERE status = 'processing'").fetchone()[0]:
            raise RuntimeError("Wait for processing runs to finish before creating or restoring a backup")
    system = LocalAccountingSystem(directory)
    runs = system.list_runs()
    for run in runs:
        exported = system.export_run(run["run_id"])
        if not exported["integrity_verified"]:
            raise ValueError("Backup evidence integrity checks failed: " + ", ".join(exported["integrity_errors"]))
    with system._session() as connection:
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("runs", "cases", "reviews", "audit_events")}
    return counts


def _sync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_backup(data_dir: str | Path, output: str | Path) -> dict:
    """Create a checked SQLite snapshot. Existing backups are never overwritten."""
    source = Path(data_dir) / DATABASE_NAME
    output = Path(output).absolute()
    if not source.is_file() or source.is_symlink():
        raise ValueError("An existing regular workspace database is required")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Backup destination already exists")
    if source.stat().st_size > MAX_BACKUP_BYTES:
        raise ValueError("Workspace exceeds the 64 MB local backup limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".accounting-backup-", dir=output.parent) as temp:
        stage = Path(temp)
        snapshot = stage / DATABASE_NAME
        source_connection = _readonly(source)
        target_connection = sqlite3.connect(snapshot)
        deadline = time.monotonic() + 10
        def progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() > deadline:
                raise TimeoutError("Workspace is busy; retry the backup when processing finishes")
        try:
            source_connection.backup(target_connection, pages=256, progress=progress, sleep=0.02)
        finally:
            target_connection.close()
            source_connection.close()
        if snapshot.stat().st_size > MAX_BACKUP_BYTES:
            raise ValueError("Workspace snapshot exceeds the 64 MB local backup limit")
        counts = _verify_snapshot(stage)
        manifest = {"backup_version": BACKUP_VERSION, "database_schema_version": DATABASE_SCHEMA_VERSION,
                    "created_at": datetime.now(UTC).isoformat(), "environment": "synthetic_local",
                    "database_sha256": _digest(snapshot), "counts": counts}
        archive = stage / "backup.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.write(snapshot, DATABASE_NAME)
            bundle.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
        os.chmod(archive, 0o600)
        _sync_file(archive)
        os.link(archive, output)  # Atomic publication; fails if a destination appeared.
        _sync_directory(output.parent)
    return {**manifest, "path": str(output), "backup_sha256": _digest(output)}


def restore_backup(archive_path: str | Path, data_dir: str | Path) -> dict:
    """Restore only to a new directory after validating the entire backup."""
    archive_path, destination = Path(archive_path), Path(data_dir).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Restore requires a new data directory; existing work is never replaced")
    if not archive_path.is_file() or archive_path.stat().st_size > MAX_BACKUP_BYTES + 65536:
        raise ValueError("A backup ZIP below the 64 MB local limit is required")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".accounting-restore-", dir=destination.parent) as temp:
        stage = Path(temp)
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if len(entries) != 2 or {entry.filename for entry in entries} != {DATABASE_NAME, "manifest.json"}:
                raise ValueError("Backup must contain exactly the database and manifest")
            if any(entry.flag_bits & 1 or entry.file_size > MAX_BACKUP_BYTES for entry in entries):
                raise ValueError("Backup contains an unsupported or oversized entry")
            if archive.getinfo("manifest.json").file_size > 65536:
                raise ValueError("Backup manifest is too large")
            manifest = json.loads(archive.read("manifest.json"))
            if (not isinstance(manifest, dict) or manifest.get("backup_version") != BACKUP_VERSION
                    or manifest.get("environment") != "synthetic_local"
                    or manifest.get("database_schema_version") != DATABASE_SCHEMA_VERSION):
                raise ValueError("Unsupported backup format or environment")
            snapshot = stage / DATABASE_NAME
            snapshot.write_bytes(archive.read(DATABASE_NAME))
        if _digest(snapshot) != manifest.get("database_sha256"):
            raise ValueError("Backup database hash does not match its manifest")
        counts = _verify_snapshot(stage)
        if counts != manifest.get("counts"):
            raise ValueError("Backup record counts do not match its manifest")
        os.chmod(snapshot, 0o600)
        _sync_file(snapshot)
        destination.mkdir(mode=0o700)  # Exclusive reservation after all validation.
        try:
            os.link(snapshot, destination / DATABASE_NAME)
        except BaseException:
            destination.rmdir()  # Only the empty directory reserved by this call.
            raise
        _sync_directory(destination)
        _sync_directory(destination.parent)
    return {"restored": True, "data_dir": str(destination), "counts": counts,
            "environment": "synthetic_local", "database_sha256": manifest["database_sha256"]}
