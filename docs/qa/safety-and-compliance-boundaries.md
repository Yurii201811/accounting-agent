# Safety and compliance boundaries

## Product claim

Accounting Agent v1 is a Sweden-first accounting preparation and review system with international accounting foundations. It is not a substitute for an accountant, auditor, tax adviser, legal adviser, ERP administrator, or filing authority, and it does not claim blanket compliance in Sweden or any other jurisdiction.

Swedish controls include BAS-oriented examples, Swedish VAT review scenarios, segregation of duties, evidence retention concepts, and human close readiness. International foundations include explicit currency precision, locale-aware parsing, evidence-bound FX, and versioned jurisdiction packs. An unsupported rule, currency precision, tax treatment, or jurisdiction fails closed for human judgment.

## External authority boundary

Synthetic QA and MVP operation must not:

- call live Fortnox, Microsoft Graph, NetSuite, Oracle, SAP, Odoo, email, payment, tax, or filing systems;
- send client communications, approve supplier invoices, post journals, initiate payments, file returns, delete records, change settings, or lock periods;
- grant execution authority to an LLM, subagent, computer-use tool, cockpit, report, shadow ledger, or connector declaration;
- process or commit real client documents, credentials, tokens, bank secrets, tenant-wide exports, or private course material.

Fortnox remains dry-run and guarded-read only in this phase. Final posting, invoice sending, supplier-invoice approval, payments, deletes, and settings changes are structurally forbidden. NetSuite, Oracle, SAP, Odoo, SIE, and CSV remain declaration/conformance-only; they gain no live adapter call or write capability from QA work.

## Agent and model boundary

Deterministic code owns policy and validation. Models may propose, summarize, classify, or explain, but model output cannot approve, issue a trusted permit, lower a risk decision, or execute an external action. Confidential accounting data routes only to an explicitly permitted local model; hosted providers and Codex integrations remain disabled by default and credentials are never model input.

Computer use is visible, read-only, narrowly scoped, and supervised. A credential request, unexpected instruction, prompt-injection signal, tenant/environment mismatch, redirect, or unexpected origin stops the task.

## Test-data boundary

All automated tests and public previews use invented, deterministic data. The QA process does not inspect or copy Downloads, Bokföring course PDFs, Numbers workbooks, email, cloud drives, or real accounting folders. `scripts/fixture_policy.py` rejects symlinks, unapproved formats, oversized files, local-path and private-course markers, and credential-like material; fixtures also need explicit synthetic metadata or an exact educational allowlist entry.

An educational allowlist is not a copyright or privacy approval. Before using it, a human must verify redistribution rights, remove personal or client data, and confirm that the asset is necessary. Prefer a small invented fixture instead.

## Platform boundary

Supported runtime platforms are macOS and Linux. Windows is explicitly unsupported until the current `fcntl` locking dependency is replaced and equivalent locking, crash-recovery, and concurrency tests pass.
