# Matching reliability checkpoint

Verified on 2026-09-22 in the canonical Accounting Agent checkout, on `main`
at base commit `aed4507`. Changes are local and uncommitted. Existing cockpit,
model-runtime, finance-skill, and related documentation/test work was preserved.

## Changes

- Supplier names are advisory candidates until an organisation number confirms
  the registry identity. Conflicting identifiers require accountant review and
  cannot populate the proposed ERP supplier ID.
- Missing invoice or registry bankgiro is unknown evidence, requires review,
  and prevents the local demo from issuing an execution permit. Changed bank
  details retain the existing escalation requirement.
- Equally scored top bank matches remain unselected. The approval packet keeps
  every tied top candidate and asks a human to choose or reject the match.
- Empty or duplicate transaction/open-item IDs, and transaction IDs that
  collide after filename sanitization or case folding, are rejected before
  any review packets are written.

The supplier and bank autopilot documentation describes these contracts. The
two new reliability test modules add 14 tests, including positive matching
cases, order-independent tie handling, six-way ties, and the supplier demo's
permit gate.

## Verification

- `python3 -m unittest`: **304 tests passed** (baseline: 290).
- Complete supplier-invoice CLI demo: **passed**, five synthetic cases and five
  approval packets; only the normal case received a local dry-run permit.
- Complete fake-client CLI month: **passed**, 15 supplier invoices/receipts and
  20 bank transactions; zero unsafe misses, false positives, unclear outputs,
  or policy alignment warnings in the built-in synthetic scenarios.
- `python3 -m accounting_agent.cli v1-system-check --json`: **passed**, all 11
  checks true; zero external calls, ERP writes, or hosted-model calls.
- `git diff --check`: **passed**.
- Bounded cross-review of supplier changes and bank changes: no outstanding
  material findings after fixing truncated tie alternatives and filename
  collisions.

Run logs, summaries, and the fake-client report are stored locally under
`.local/matching-reliability-20260922-6wdr7cyq/`. The final full-suite output is
saved in `unittest.stderr.txt` there.

## Boundary and next action

This checkpoint verifies synthetic local processing only. No real client data,
live provider service, payment, filing, or external communication was used.
Supplier identity relies on the fixture registry, and the new ambiguity rule
detects exact ties at the matcher's existing rounded score. Identifier checks
apply within each run; this change does not add persistent reconciliation
allocation across runs.

The changes are ready for local review. A useful next development step is to
extend synthetic acceptance scenarios for near-tied bank candidates and
supplier aliases before changing the scoring or registry model.
