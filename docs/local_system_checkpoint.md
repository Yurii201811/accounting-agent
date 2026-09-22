# Connected local system checkpoint — 2026-09-22

The newer [release finalization checkpoint](release_finalization_checkpoint.md)
records the Grok-assisted consistency fixes, backup/restore, and packaged release.

## Working result

The `serve` command now provides a persistent local application connecting
synthetic intake, validation, supplier invoice preparation, bank matching,
case evidence, human review records, audit history, and verified JSON exports.

```bash
python3 -m accounting_agent.cli serve --data-dir .local/system --port 8767
```

Open <http://127.0.0.1:8767/>. The SQLite directory is ignored by Git. The old
static operations cockpit remains available separately. See [operation and
architecture](local_system.md) for the input contract and boundaries.

The application records local assessments, not financial approvals. Original
accounting policy remains attached to every case. Request keys prevent duplicate
runs, review revisions prevent silent overwrites, failed intake creates no
partial cases, and an interrupted dead process leaves an honest saved state.
Schema readiness checks refuse incompatible databases; the initial compatible
sequenced-audit schema upgrades additively.

## Verified evidence

- `python3 -m unittest discover -s tests`: **345 tests passed**. This includes
  local service and HTTP tests for intake, review, export, server restart,
  stale revisions, idempotency, validation rejection, process crash recovery,
  live-owner preservation, schema upgrade/refusal, and altered evidence.
- `python3 -m accounting_agent.cli v1-system-check --json`: **11 checks passed**;
  zero ERP writes, external calls, and hosted-model calls.
- JavaScript syntax, Python compilation, and `git diff --check` passed.
- Built and installed the wheel in an isolated temporary environment. Outside
  the checkout, the installed package processed all **35 sample cases**, verified
  its export, loaded all five application assets, and created the local server.
- Browser acceptance exercised the sample month and a separately imported
  two-case JSON bundle, case search and selection, saved reviews, and reopening
  the same SQLite data after server restart.
- Browser rejection of a bundle without the required synthetic declaration
  displayed the error and saved failed run in Work history with **zero cases**.
- Desktop (1440 px) and mobile (390 px) checks showed readable evidence and review
  controls without horizontal overflow. Temporary viewport override was reset.
- The browser export preview for the 35-case run showed one saved review, three
  audit events, and no integrity errors. Its displayed JSON was saved as a local
  acceptance artifact; native browser file-download completion was not asserted.

Current browser sample run: `run_2d2ff5bbd1144278b7faac233fc0a2bc`.
The partial-payment case `br_FC-BANK-004` retains its `approval_required` policy
and saved `needs_changes` assessment, including the 6,250.00 SEK residual. No
balance was changed. The two-case import is
`run_6f10f1fca089424dbd0eb9146ba6653f` and retains its supplier review.

Acceptance artifacts are outside the repository:

- `accounting-system-desktop.png`
- `accounting-system-mobile.png`
- `accounting-system-evidence.json`

The exported package's `content_hash` is
`af33cf8680b66d501c78bfecb8be5816a357f8d6dcdb10b4b2f52e4af83fac86`.
These hashes check saved record consistency; they are not an independently
signed audit trail or protection against replacing the entire database.

## Current state and next boundary

At this checkpoint, changes were local and uncommitted. No push, deployment,
real client processing, live connector call, invoice approval, payment, message,
or filing had occurred.
This verifies a connected synthetic development workflow; it does not establish
production readiness or error-free accounting across unseen inputs.

The next operational phase is a separately scoped production design covering
authenticated reviewer identities, tenant isolation, protected storage, backup
and restore, and supported document ingestion. Live financial execution remains
outside the current adapter rules and requires an explicit change of scope.
