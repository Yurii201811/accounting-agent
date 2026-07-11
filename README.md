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

Supplier, bank-reconciliation, and local Microsoft 365 sample fixtures are
packaged with the application, so their default commands also work from a
clean installation outside the source checkout. Passing an empty, missing, or
incomplete fixture folder fails with a nonzero exit code and an actionable
message; it never reports a zero-item run as successful.

Run tests:

```bash
python3 -m unittest
```

Install the locked QA tools and run the v1 gates:

```bash
uv sync --frozen --group qa
npm ci
npx playwright install chromium firefox webkit
uv run --frozen --group qa python scripts/qa.py quick
uv run --frozen --group qa python scripts/qa.py full
```

The full gate adds subprocess-aware branch coverage, property and resilience
tests, Ruff, mypy, Bandit, dependency and credential-leak scans, a final evidence
privacy scrub/audit,
targeted safety mutation testing, and the Chromium/Firefox/WebKit Playwright +
axe matrix. Evidence is written below `.local/qa/runs/<UTC-run-id>/`.

`release` rebuilds the exact five-file public preview with a fixed source-date
epoch and requires its public `*.vercel.app` HTTPS deployment URL, then proves deterministic
wheel/sdist hashes, clean-installed behavior for all nine commands, preview
privacy, and deployed artifact equality. It never enables or tests a live ERP
write:

```bash
ACCOUNTING_AGENT_PREVIEW_URL=https://your-preview.vercel.app \
uv run --frozen --group qa python scripts/qa.py release
```

The command writes a revision- and bundle-bound manual VoiceOver template under
the run's `accessibility/` directory. Until a human completes that checklist,
the automated steps may pass but `release_ready` remains false and the command
exits `2`. A dirty worktree or mismatched preview hash can never be reported as
release-ready.

After completing the checklist against the exact deployed bundle, start a new
evidence run and pass the prior attestation explicitly:

```bash
ACCOUNTING_AGENT_PREVIEW_URL=https://your-preview.vercel.app \
uv run --frozen --group qa python scripts/qa.py release \
  --manual-accessibility-evidence \
  .local/qa/runs/<prior-run-id>/accessibility/manual-voiceover.md
```

Release mode always rebuilds and verifies
`.local/accounting-agent-v1-preview-release`; an alternate bundle environment
value cannot redirect the release proof. Both summary and attestation inputs are confined to regular, non-symlinked
paths below `.local/qa/runs/`. The runner samples Git revision and cleanliness
before and after all gates and rejects drift visible at either boundary. Run
release QA in its dedicated worktree and do not commit, check out, or edit
concurrently; endpoint sampling is not an immutable filesystem snapshot.

Release source archives include the tests, helpers, synthetic source fixtures,
QA traceability and coverage catalogs, workflow specification, and QA runner
needed to validate the archive on its own.

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
