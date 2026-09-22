# Operations Cockpit

The operations cockpit is a read-only static workspace for Accounting Agent v1.
It gives the operator one place to inspect workflow state, safety
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
  with work-type, search, and priority filtering. Supplier/counterparty, reference,
  and exact stored amount identify the work. No queue is truncated.
- Close: dependency-aware evidence, reconciliation, exception, policy, and
  independent-signoff controls.
- Automation: a resumable preparation ladder and advisory model-routing
  boundary.
- Integrations: capability declarations generated from the provider registry
  for Fortnox, NetSuite, Oracle Fusion, SAP S/4HANA, Odoo, SIE, CSV, and
  supervised observation-only computer use. Only the guarded Fortnox read
  contract has a preview implementation; the others are declarations.
- How it works: deterministic accounting stages and the bounded specialist-
  agent plan, ending at a human decision gate.
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

### Inspecting a case

Supplier invoices and bank transactions have counted work-type filters. Counts
represent unique cases, not repeated risk signals; the selected type combines
with search and priority. Removable filter chips and Clear all reset the same
controls, with localized result announcements and keyboard focus recovery.

Every case has a native Inspect case / Visa ärende disclosure available in both
Guided and Expert modes. It lists the checks needed before reassessment, so a
secondary duplicate or payment-detail risk remains visible even when a stronger
rule blocks the case. Senior review remains explicit on escalated cases.
Opening a disclosure never approves, resolves, selects, or changes a case.

Tied bank matches show every equally scored top invoice beside its match score,
with an explicit none-selected state. Supplier identity conflicts and missing
bank details have specific English/Swedish explanations. Existing evidence
links can be opened directly in Guided mode; raw case IDs and policy diagnostics
remain in Expert details. Amounts use the stored currency precision and localized
number separators; missing or invalid amounts stay absent instead of becoming
zero. The isolated public preview demonstrates these controls with invented
company names, references, and a tied payment example.

Case details also show invoice net, VAT, total, invoice date, and due date. An
invalid or missing monetary field is explicitly labelled rather than filled
with zero. Bank cases show the proposed reference, bank amount, and open amount.
Comparable amounts show the remaining balance if matched or the overpayment;
different currencies, opposite directions, zero amounts, or invalid amounts
show a non-comparable state instead of a calculated residual. These are
read-only comparisons: balances are never updated by the cockpit.

Partial payments, amount differences, and incompatible currency/direction have
specific bilingual guidance. A low score explained by those known differences
does not by itself become an unrelated missing-evidence warning. The main
instruction is not repeated inside the disclosure when useful facts are
available; any additional risk checks remain visible. Fact labels and values
are searchable in both languages.

## Navigation and decision hierarchy

Below `60rem`, a labelled native section jump remains non-sticky and provides
access to every visible section without horizontal scrolling. Today stacks the
priority count, counted Review action, and local-run state in that order. At
`60rem` and wider, the same sections are rendered as desktop anchors that stay
sticky below the safety strip; linked headings receive top clearance, and
Today preserves count, run, and action as desktop columns. The jump and anchors
stay synchronized with the current hash and scroll position.

The compact masthead exposes Review early. Today then leads with the priority
count, local-run state, latest evidence, and a counted Review action, followed
by the always-visible live-safety heartbeat and secondary fixture state. Every
Review row labels its localized reason as “Next human decision” / “Nästa
mänskliga beslut” and its evidence state as “Evidence” / “Underlag”. Review
filters identify the list and live result count they update. When no cases
exist, the visible zero count remains while the filters and dynamic no-match
state are omitted in favor of one calm bilingual static state. When filters
are active, localized removable chips expose the current search and priority;
individual removal returns focus to its control, while Clear all resets both.
The live result reports visible and total cases with correct English/Swedish
grammar. A stable severity rail reinforces the existing text badge, and row
hover or descendant focus adds emphasis without using color as the only signal.
In the command dialog, arrow keys move through matching sections and Escape
closes the dialog from any focused item and returns focus to the Find work
control. The interface remains strictly observe/review-only.

The stylesheet is bundled as package data and copied locally when a clean
installation builds a cockpit. The page remains offline and contains no CDN,
remote font, or runtime asset dependency.

## Deployable synthetic preview

Do not deploy `reports/operations_cockpit/index.html`: it may link to local
generated evidence. Build the isolated bundle instead:

```bash
python3 -m accounting_agent.cli build-public-preview \
  --output .local/accounting-agent-v1-preview
```

This builder never reads local case artifacts. It renders three built-in
synthetic review examples, copies only the packaged stylesheet/icon/license,
emits `preview-manifest.json` with file hashes and explicit disabled builder
capabilities, and refuses to reuse a target containing any unexpected file.

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
