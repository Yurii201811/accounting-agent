# Local release finalization — 2026-09-23

## Result

The synthetic local application is packaged and verified through intake,
processing, policy review, durable history, evidence export, workspace backup,
restore, and reopening. Current application: <http://127.0.0.1:8768/>.

The latest browser-created sample is
`run_6f1fef7439254f1caf2916953b5e3f31`: 35 cases completed without a run error.
The older partial-payment review retains its policy and revision history.

## Grok assistance and disposition

The user authorized Grok Build CLI with Grok 4.7 and Extra High. The local CLI
listed `grok-4.7`; the completed session metadata confirms `grok-4.7` and
`xhigh`. Session: `01a0cb0f-b5ec-73b1-a5fc-3ae5e3823f45`.

Grok received a bounded source/document brief and returned a source review.
It did not execute the tests or modify the repository. Its final review text is
saved in the local release artifacts. Recommendations were checked against the
source before changes were applied.

| Finding | Resolution and evidence |
| --- | --- |
| A live reused PID can keep an abandoned run processing | Workers now hold OS file leases. Startup and same-key replay recover absent leases; real live-worker and subprocess-crash tests pass. |
| Multi-query reads can mix old case state with new reviews | Read sessions now explicitly begin a SQLite transaction. A concurrent-write regression verifies one coherent exported snapshot. |
| Independent hashes miss inconsistent policy, history, and audit projections | Exports validate record relationships, lifecycle events, counts, revisions, and policy. Reads expose integrity state; review and export are blocked when inconsistent. |
| A transient completion write failure consumes a valid request as failed | Completion commits retry up to three times. Exhausted persistence failures remain recoverable; terminal rows cannot be overwritten. |

Additional work adds atomic verified backup publication, restore to a new
directory only, storage health checks, a browser backup control, and one-command
release verification. No accounting policy modes or live-action permissions
were relaxed.

## Verification

- `python3 scripts/verify_release.py`: **362 tests passed**, all **11 accounting
  control checks passed**, and JavaScript syntax passed on Python 3.14.7.
- Control checks reported zero ERP writes, application external calls, and
  hosted-model calls. The separate user-authorized Grok source review was an
  external model consultation.
- Focused resource-warning checks covered recovery, concurrent snapshots,
  review integrity, HTTP behavior, and backup/restore.
- Built and installed the wheel in an isolated environment outside the
  checkout. The installed package processed 35 cases, rejected a forbidden
  review, loaded all five UI assets, started the server, and restored an export
  exactly from its backup.
- Browser checks verified a new 35-case run, the saved partial-payment evidence,
  a second review revision, invalidation of an older prepared backup after a
  review save, and the verified-backup download control. No browser console
  errors or warnings were observed.
- The final workspace backup contains **4 runs, 72 cases, 3 review records,
  and 11 audit events**. Every exported run matched exactly after restoration
  into a separate temporary workspace. Existing work was preserved.
- The CI workflow is written locally and pins verified action references. It
  has not been pushed or run on GitHub; its Python 3.11 matrix is not a claim of
  an additional local runtime test.

## Release artifacts

Stored under `.local/releases/2026-09-23/` and excluded from Git:

- `accounting_agent-1.0.0-py3-none-any.whl`
- `workspace-backup.zip`
- `release-verification.json`
- `grok-review.md` (final response only)
- `manifest.json` (artifact/source hashes and verification metadata)

Wheel SHA-256:
`c32eab133276dfbcd9a541fc58091fdadf710002a377af4cda161e91fc82a98d`.
See [operations](local_release_operations.md) for restore and verification
commands. These are local release artifacts, not a published release.

## Remaining production scope

This is a verified synthetic local release, not a finished production accounting
service. Authentication, tenant authorization, protected client storage and key
management, independently trusted signoffs/audit anchoring, real-document
ingestion, and deployment acceptance remain unimplemented or unverified.
The requested hosting target/domain and login-provider choice are unanswered.

The repository still forbids processing real client documents and live financial
actions in this phase. No live accounting, Graph, email, payment, tax, or filing
operation was added or performed. At the verification checkpoint, no push or
deployment had occurred and source changes were uncommitted. The local artifact
manifest records that exact packaged source state.

## Publication follow-up

The user subsequently requested a commit and push to GitHub `master`. At the
publication preflight, the repository default was `main` and `master` did not
exist. The release is being committed to a new `master` branch without changing
the default branch or deploying the application. Application source matches the verified package except for removal of a
trailing blank line; local databases, backups, and release archives stay outside
Git. Git history and GitHub Actions provide the subsequent publication
and hosted-check state.
