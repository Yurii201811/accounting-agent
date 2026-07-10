# Operations Cockpit

The operations cockpit is a read-only static dashboard for the local Accounting
Agent MVP. It gives the operator one place to inspect workflow state, safety
boundaries, review queues, local output artifacts, and safe next commands.

Build it with:

```bash
python3 -m accounting_agent.cli build-operations-cockpit
```

Default output:

```text
reports/operations_cockpit/index.html
```

## What it reads

The builder reads repo-local files only:

- `.local/fake_client_dry_run/manifest.json`
- `.local/fake_client_dry_run/summary.json`
- `.local/fake_client_dry_run/audit_log.jsonl`
- `.local/fake_client_dry_run/bank_reconciliation_proposals.json`
- `.local/fake_client_dry_run/supplier_invoice_autopilot/**`
- `.local/demo_supplier_invoice_autopilot/**`
- `.local/accounting_agent.sqlite`, opened read-only if it exists
- selected docs under `docs/`

It does not read secrets, credentials, tokens, raw client document folders, or
external systems. It does not initialize or mutate the SQLite database.

## What it shows

- Workflow map from intake through audit/report.
- Operational status including last run, local readiness, live-call counters,
  and SQLite counts.
- Safety banner with current allowed and blocked boundaries.
- Review queues for approval, escalation, forbidden cases, missing info, risky
  suppliers, duplicate risk, changed bank details, uncertain VAT, and policy
  alignment warnings.
- Links to existing local manifests, summaries, audit logs, approval packets,
  Fortnox dry-run payloads, gnubok shadow outputs, bank proposals, the
  fake-client report, and relevant docs.
- Safe next local commands and actions that remain forbidden.

## Safety contract

The cockpit is observe/review only. It is not an approval authority and it never
executes accounting work. It makes no live Fortnox, Microsoft Graph, email,
payment, tax, or filing calls.

The following remain forbidden in this adapter phase:

- final Fortnox posting
- invoice sending
- supplier invoice approval
- payments
- deletes
- settings changes
- tax filing
- processing real client documents or secrets

Generated links are emitted only for targets that already exist under the repo
root. Missing artifacts are shown as missing text rather than clickable links.
