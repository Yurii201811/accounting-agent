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

- Today: run readiness, unique priority-case count, and zero-required live-call
  counters. A non-zero live counter is rendered as a safety violation.
- Review: one deduplicated row per case, sorted by the strictest stop condition,
  with search and priority filtering. No queue is truncated.
- Workflow: deterministic accounting stages and the bounded specialist-agent
  plan, ending at a human decision gate.
- Integrations: capability declarations generated from the provider registry
  for Fortnox, NetSuite, Oracle Fusion, SAP S/4HANA, generic exchange, and
  supervised observation-only computer use.
- Controls and evidence: policy boundaries, grouped local artifacts, and expert
  details without leaking the local workspace path.

Guided mode keeps the next decision and plain-language evidence visible. Expert
mode adds raw case IDs, policy modes, queue counts, and local operator commands.
Raw policy codes and fixture identifiers stay inside Expert details. The
guidance perspective and English/Swedish controls persist locally in the
browser; perspective changes explanatory emphasis but never risk order or
policy. The primary interface, dynamic review reasons, filters, workflow,
provider matrix, empty states, and dates are localized. A zero-result filter
state offers a local clear-filters action.
`Cmd/Ctrl + K` opens section navigation.

The stylesheet is bundled as package data and copied locally when a clean
installation builds a cockpit. The page remains offline and contains no CDN,
remote font, or runtime asset dependency.

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
