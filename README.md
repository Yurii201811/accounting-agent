# Accounting Agent

Local-first Swedish accounting automation workspace.

MVP 1 is the Supplier Invoice Autopilot: it ingests synthetic local fixtures,
extracts invoice fields, checks duplicates and supplier risk, proposes BAS/VAT
treatment, writes an approval packet, and stores the result in a local SQLite
queue. It does not post to Fortnox, send emails, approve invoices, or start
payments.

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

The cockpit writes `reports/operations_cockpit/index.html`. It is static HTML
generated from repo-local manifests, summaries, approval packets, audit logs,
bank reconciliation proposals, and docs. It has no server, CDN, external asset,
or live-provider dependency, and it remains observe/review only.

Run the lower-level sample pipeline:

```bash
python3 -m accounting_agent.cli process-fixtures
```

Run tests:

```bash
python3 -m unittest
```

See `docs/local_demo_supplier_invoice_autopilot.md` for the one-command local
demo and `docs/mvp_supplier_invoice_autopilot.md` for the MVP contract and
packet schema. See `docs/operations_cockpit.md` for the cockpit workflow.
