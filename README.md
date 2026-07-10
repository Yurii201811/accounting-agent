# Accounting Agent

Sweden-first, provider-neutral accounting automation for safe local proposals,
exception review, reconciliation, and evidence packaging.

The functional runtime still uses synthetic local fixtures. It extracts invoice
fields, isolates duplicates by client, checks supplier and VAT risk, proposes
BAS/VAT treatment, prepares bank-reconciliation proposals, writes human review
packets, and records local evidence. It does not process real client data or
post, approve, send, pay, delete, change ERP settings, file tax, or call a live
provider.

Version 1 adds explicit legal-entity journals, evidence-bound approvals,
dependency-aware close readiness, resumable preparation agents, guarded ERP
read contracts, provider-neutral advisory-model routing, and a bilingual
Guided/Expert cockpit. International support is a schema and jurisdiction-pack
foundation, not a blanket compliance claim. Live provider writes remain
forbidden.

Inspect that machine-readable boundary:

```bash
python3 -m accounting_agent.cli platform-status
python3 -m accounting_agent.cli platform-status --json
python3 -m accounting_agent.cli v1-system-check --json
```

Run the complete local demo:

```bash
python3 -m accounting_agent.cli demo-supplier-invoice-autopilot
```

The demo writes normalized intake cases, extracted invoice JSON, accounting
proposals, risk findings, policy decisions, execution permits where applicable,
approval packets, Fortnox dry-run payloads, gnubok shadow output, and an audit
log to `.local/demo_supplier_invoice_autopilot`.

Run the full fake-client month dry run:

```bash
python3 -m accounting_agent.cli fake-client-dry-run
```

The fake-client run generates a synthetic Swedish consulting/service business
month, runs supplier invoice autopilot and bank reconciliation locally, writes
outputs to `.local/fake_client_dry_run`, and writes
`docs/fake_client_dry_run_report.md`. It uses no real client data and no live
external APIs.

Build the read-only local operations cockpit:

```bash
python3 -m accounting_agent.cli build-operations-cockpit
```

The cockpit writes `reports/operations_cockpit/index.html`. It is a local,
read-only Workbench generated from repo artifacts. Guided mode gives accountants
one clear next decision; Expert mode exposes policy, provider, specialist-agent,
and evidence detail. The main interface, review reasons, filters, workflow,
provider matrix, and dates switch between English and Swedish. The selected
guidance perspective changes explanatory emphasis only; risk priority and
safety policy remain fixed. It has no CDN or live-provider dependency and
remains observe/review only.

Build the separate deployable preview from built-in synthetic examples only:

```bash
python3 -m accounting_agent.cli build-public-preview \
  --output .local/accounting-agent-v1-preview
```

The public builder never reads local workflow artifacts and refuses unexpected
files in its target directory.

Private course references, if present, stay under `.local/course_reference/`
and are excluded from Git. They can inform topic coverage and plain-language
explanations, but current official law, BFN, Skatteverket, BAS, and SIE sources
remain authoritative.

Run the lower-level sample pipeline:

```bash
python3 -m accounting_agent.cli process-fixtures
```

Run tests:

```bash
python3 -m unittest
```

Fixture commands use an explicit 2026-05-16 evaluation date by default so risk
outcomes do not change with the wall clock. Pass `--as-of YYYY-MM-DD` to the
supplier fixture or demo command when testing a different review date.

Start with `docs/accounting_agent_v1.md` for the product, jurisdiction, ERP,
model, autonomy, computer-use, and release boundary. See
`docs/local_model_evaluation.md` for the local Ollama comparison,
`docs/v1_research_decisions.md` for the problem-to-product decisions,
`docs/local_demo_supplier_invoice_autopilot.md` for the one-command local demo,
`docs/mvp_supplier_invoice_autopilot.md` for the packet schema, and
`docs/operations_cockpit.md` for the interface workflow.
