# Accounting Agent

Sweden-first, provider-neutral accounting automation for safe local proposals,
exception review, reconciliation, and evidence packaging.

The functional runtime still uses synthetic local fixtures. It extracts invoice
fields, isolates duplicates by client, checks supplier and VAT risk, proposes
BAS/VAT treatment, prepares bank-reconciliation proposals, writes human review
packets, and records local evidence. It does not process real client data or
post, approve, send, pay, delete, change ERP settings, file tax, or call a live
provider.

## Run the local application

```bash
python3 -m accounting_agent.cli serve --data-dir .local/system --port 8767
```

Open **http://127.0.0.1:8767/**. The persistent application connects synthetic
intake, supplier-invoice and bank-reconciliation pipelines, case evidence,
local review records, run history, and an evidence export.

1. Run the sample month, or download the sample format and import a synthetic
   JSON bundle.
2. Open a case to inspect amounts, risk findings, the accounting proposal, and
   its saved source packet.
3. Record a review, request changes, or reject the proposal. Review records
   preserve the original accounting policy and never authorize execution.
4. Export the run's input, cases, review history, and audit records as JSON.
5. Restart with the same data directory to reopen the saved work.

The server binds only to `127.0.0.1`; it is a local, single-user development
system. Real-client processing and live financial integrations remain outside
this build. See [Local system guide](docs/local_system.md) for the data contract,
API, persistence, recovery, and evidence boundaries. The original read-only
cockpit and CLI workflows remain available below.

Use **Prepare workspace backup** in the sidebar to download a checked recovery
copy of all saved work. To restore, use a new data directory:

```bash
python3 -m accounting_agent.cli restore-workspace --backup accounting-workspace.zip --data-dir .local/restored
python3 -m accounting_agent.cli serve --data-dir .local/restored --port 8767
```

Run the complete local release gate with `python3 scripts/verify_release.py`.
It records test, accounting-control, and JavaScript syntax results under
`.local/release-verification.json`. See [backup and release operations](docs/local_release_operations.md).

Version 1 adds explicit legal-entity journals, evidence-bound approvals,
dependency-aware close readiness, resumable preparation agents, guarded ERP
read contracts, provider-neutral advisory-model routing, and a bilingual
Guided/Expert cockpit. International support is a schema and jurisdiction-pack
foundation, not a blanket compliance claim. Live provider writes remain
forbidden.

## Finance AI skill for Swedish teams

The repository also contains a standalone, provider-neutral Agent Skill for
accountants, controllers, FP&A teams, CFOs, audit/tax/payroll professionals, and
companies introducing Codex, Claude, Excel, or AI agents into finance work:

- [Practical AI for finance in Sweden](docs/ai_for_finance_sweden.md) — a
  publication-ready guide based on Swedish authorities, research, open-source
  patterns, and clearly labeled practitioner evidence.
- [use-ai-in-finance-sweden](skills/use-ai-in-finance-sweden/SKILL.md) — the
  installable skill with role playbooks, Excel routing, Swedish governance,
  adoption controls, task briefs, templates, and a synthetic workflow scorer.

The skill keeps calculations reproducible, source evidence visible, sensitive
data inside approved environments, and posting, approval, payment, filing,
signing, deletion, and external communication under human control.

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
