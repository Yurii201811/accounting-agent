# Local release operations

This runbook covers the synthetic local system. It does not enable real client
processing, authenticate accounting signoffs, or enable external financial work.

## Verify a candidate

Requirements: Python 3.11+ and Node.js for the JavaScript syntax check. The
application itself has no Node.js runtime requirement.

```bash
python3 scripts/verify_release.py
python3 -m accounting_agent.cli check-workspace --data-dir .local/system
```

The release gate executes all unit/integration tests, all v1 control checks, and
the application JavaScript syntax check. It fails if a check fails or a required
tool is missing. Its JSON report is local test evidence, not hosted CI or
production acceptance. The GitHub workflow runs the same gate on Python 3.11
and 3.14 when these changes are published.

`GET /api/health` reports database readiness and aggregate record counts. It
returns 503 without internal database details when storage is unavailable.
Readiness checks do not certify the accounting content of every case; verified
exports and backups perform those additional relationship and hash checks.
The `check-workspace` command opens the application store and therefore also
performs normal startup recovery of abandoned processing runs. The HTTP health
endpoint only reads the already-open workspace.

## Create a recovery copy

Use **Prepare workspace backup** in the sidebar, followed by **Download backup
ZIP**, or run:

```bash
python3 -m accounting_agent.cli backup-workspace \
  --data-dir .local/system --output .local/backups/accounting-workspace.zip
```

The backup contains exactly a SQLite snapshot and its manifest. The manifest
records the schema version, timestamp, database SHA-256, environment, and record
counts. Backup creation checks all saved run exports and publishes the archive
atomically. An existing destination is never overwritten; choose a new filename
for each recovery copy. In-progress runs must finish first. The local limit is
64 MB, and a busy snapshot attempt times out after ten seconds.

Backups contain the synthetic source evidence and review notes. They are not
encrypted and their hashes are not signatures. Keep them within the approved
local environment; this implementation is not protected client storage.
Stop any older application process before upgrading code. Run leases are local
process coordination files and are deliberately excluded from backups.

## Restore and verify

```bash
python3 -m accounting_agent.cli restore-workspace \
  --backup .local/backups/accounting-workspace.zip --data-dir .local/restored
python3 -m accounting_agent.cli check-workspace --data-dir .local/restored
python3 -m accounting_agent.cli serve --data-dir .local/restored --port 8768
```

Restore refuses an existing destination, unexpected archive entries, unsupported
versions, checksum/count mismatches, invalid SQLite references, active runs,
and inconsistent accounting evidence. No destination workspace is created until
validation passes. The restored directory and database use owner-only
permissions on supported Unix filesystems. Open the restored application and
inspect the expected run, review history, and export before deciding to use it.
The original workspace remains available throughout recovery.

## Production remains a separate release

Outstanding production requirements include authenticated reviewer identities,
tenant authorization, protected storage and key management, independently trusted
audit/approval records, document ingestion, and a deployment target with
operational ownership. Authentication and hosting choices are unresolved.
The application binds to loopback and has no supported public deployment mode.
Do not expose it through a public proxy or treat a green local gate as permission
to process real client data or execute financial actions.
