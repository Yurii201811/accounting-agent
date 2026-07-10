# Production Readiness and Safety Audit

Generated: 2026-05-16

Superseded note: `docs/post_implementation_audit.md` is the newer MVP-0
post-implementation audit. This document remains useful as the production
readiness baseline, but some findings listed here were partially fixed during
the post-implementation audit: external-write policy evidence now fails closed
when omitted, the permit issuer re-checks policy decisions, the permit
validator enforces idempotency binding, the raw HTTP Fortnox transport is no
longer exported from the package root and requires a matching permit for POST,
restricted MCP draft tools require explicit risk evidence, and demo output
cleanup now refuses unmarked existing folders.

Scope: repository code, configs, tests, docs, synthetic fixtures, local CLI demos, Fortnox adapter boundary, Microsoft 365 intake prototype, gnubok shadow ledger, Hermes approval helpers, restricted Fortnox MCP facade, and the current bank-reconciliation prototype.

## Recommendation

**NO-GO for connecting real Microsoft 365, Fortnox production/sandbox write access, or real client data.**

The system is suitable for **synthetic local fixtures and dry-run-only development**. It is not yet suitable for production accounting, real mailbox/file intake, Fortnox credentials, real supplier invoices, real bank statements, or any client data.

The most important reason is not one missing feature. It is that the current safety model is still an in-process prototype: policy inputs default to safe values, permits are ordinary Python objects without an approval-store trust anchor, idempotency is process-local by default, audit logs are not tamper-evident, local storage is plaintext, and client isolation/retention are not implemented.

## What Changed During This Audit

Small urgent fail-closed fixes were implemented:

- Added `.gitignore` coverage for local databases, JSONL logs, `.env` files, token/credential folders, runtime artifacts, and client/private accounting material (`.gitignore:1`).
- Added a repository safety test that asserts those ignore patterns remain present (`tests/test_repository_safety.py:10`).
- Hardened `FortnoxAdapter` so non-dry-run supplier-invoice draft creation rejects `draft_only` permits and requires an approval/escalation permit with recorded approved reviews (`accounting_agent/adapters/fortnox.py:410`, `accounting_agent/adapters/fortnox.py:627`).
- Added/updated Fortnox tests proving `draft_only` permits are rejected for live draft writes and reviewed permits are required for the live-write path (`tests/test_fortnox_adapter.py:222`).
- Added a policy test proving live bank reconciliation remains forbidden (`tests/test_policy_and_permits.py:130`).

Verification after fixes:

- `python -m unittest` could not run because `python` is not installed in this shell.
- `python3 -m unittest` passed: 78 tests.
- Local supplier invoice fixture smoke passed with 5 synthetic approval packets, 0 live Fortnox calls.
- Local Microsoft 365 intake fixture smoke passed with 4 synthetic/local files, duplicate detection, 0 live Microsoft calls.
- Local Supplier Invoice Autopilot demo passed, wrote temporary artifacts under `/private/tmp/accounting-agent-audit/demo`, and reported 0 live Fortnox calls, 0 live Microsoft 365 calls, 0 emails/payments/filings.
- Local bank reconciliation fixture smoke passed with 7 synthetic bank transactions and 4 review packets; live reconciliation remains forbidden.

## Go/No-Go Matrix

| Area | Current evidence | Classification | Decision |
| --- | --- | --- | --- |
| Synthetic supplier-invoice fixtures | Local fixture pipeline, tests, dry-run payloads, approval packets | Safe now for local synthetic data | Go for fixtures only |
| Local Microsoft 365 intake prototype | Local folder scan only, no Graph client, duplicate detection | Safe only in dry-run/local sample mode | No real mailbox or OneDrive |
| Fortnox reference reads | Adapter exists, credentials required for real transport, sensitive reads disabled by default | Requires fix before real use | No real credentials yet |
| Fortnox supplier-invoice draft write | Permit-gated, dry-run default, live path now requires reviewed permit, but trust anchor is still weak | Safe only in dry-run | No live Fortnox write |
| Fortnox voucher/posting/finalization | Policy and adapter forbid posting/payment/sending/final actions | Forbidden | Keep forbidden |
| Email send | `EmailWriteAdapter` validates permits but never sends; Hermes only drafts | Safe only as draft text | No send path |
| Microsoft Graph tokens/data | No real adapter or token store implemented | Requires fix | No real Graph connection |
| gnubok shadow ledger | Local stub, advisory/fail-soft, Fortnox remains source of truth | Safe only with synthetic/local dry-run data | No real client data |
| Bank reconciliation | Prototype code exists; live reconciliation is forbidden by policy | Requires fix | No Fortnox reconciliation |
| Client separation | `fixture_client`/`unmapped` placeholders; shared local SQLite/storage | Requires fix | No multi-client or real-client use |
| Audit trail | JSONL/SQLite local records, no hash chain/signing/immutable storage | Requires fix | Not production-grade |
| Data retention/deletion | No retention, deletion, legal hold, export, or purge workflow | Requires fix | No real data |
| Test coverage | Good unit coverage for current core plus local demo and bank-reconciliation fixture tests; gaps remain in bypass/property/live-adapter tests | Requires fix | Not enough for production |

## Critical Blockers

### P0-1: Policy can be bypassed by omission of risk facts

`PolicyContext` defaults are optimistic: known supplier/customer, zero duplicate risk, full VAT/OCR confidence, unlocked period, no bank-detail change (`accounting_agent/policy.py:105`). That means a caller or agent can omit inconvenient evidence and get `draft_only` for low-amount external-write proposals (`accounting_agent/policy.py:60`, `accounting_agent/policy.py:147`).

Production fix:

- Replace optional safe defaults with an explicit evidence object.
- Unknown supplier, unknown duplicate state, unknown VAT confidence, unknown bank-detail state, unknown client mapping, or missing source document must fail to `approval_required` or `escalation_required`.
- Add tests where each missing risk signal fails closed.

### P0-2: Permits are not bound to a trusted approval authority

`PermitIssuer.issue(...)` accepts `approved_reviews` as caller-supplied strings and emits a normal dataclass (`accounting_agent/permits.py:207`). `PermitValidator` validates payload hash, case, action, expiry, and reviews (`accounting_agent/permits.py:260`), but it does not verify that reviews came from a human-controlled approval request, role store, or immutable approval ledger.

Production fix:

- Add an approval request table/store with reviewer identity, role, timestamp, decision, and no self-approval.
- Make adapters validate permits by looking up the permit id in the trusted store, not just by trusting an in-memory object.
- Include approval request id, issuer, environment, adapter, client id, source document ids, and execution scope in the permit.
- Consider signing or HMACing permit records if they ever cross process boundaries.

### P0-3: Raw adapter and transport classes are importable bypass surfaces

The restricted MCP facade fails unknown and hidden tools closed. After the
post-implementation audit, `HttpFortnoxTransport` is no longer exported from the
package root and its `POST` method requires a matching permit, but raw Python
module imports are still not a production capability boundary. A production
agent runtime must not expose raw adapter or transport classes/tools to LLM
agents.

Production fix:

- Agent-facing tooling must expose only the restricted facade.
- Do not register raw Fortnox MCP tools or raw adapter methods.
- Add integration tests that enumerate available tools and prove no raw write/transport path is reachable.

### P0-4: Idempotency is not durable by default

The default idempotency store is in-memory (`accounting_agent/idempotency.py:35`), so duplicate prevention disappears on process restart. `FortnoxAdapter` does check idempotency before write (`accounting_agent/adapters/fortnox.py:415`), but production writes need a persistent, atomic reservation before the external call and durable completion after the response.

Production fix:

- Implement a SQLite-backed idempotency store with unique constraints for adapter/action/client/case/payload hash.
- Reserve the idempotency key transactionally before the outbound write.
- Persist request hash, response reference, status, and retry state.
- Add crash/retry tests.

### P0-5: Audit trail is local and not tamper-evident

`JsonlAuditLog` appends JSONL with key-based redaction (`accounting_agent/audit.py:55`, `accounting_agent/audit.py:110`), and SQLite stores audit rows (`accounting_agent/db.py:66`). But there is no hash chain, signature, filesystem permission check, immutable mode, actor authentication, or deletion prevention beyond normal local files.

Production fix:

- Add append-only event schema with hash chaining.
- Record actor identity, role, source system, before/after policy mode, adapter result, and approval/permit ids.
- Use a central redaction layer before any JSON/SQLite/Markdown output.
- Add tamper-detection tests.

### P0-6: Sensitive data is stored in plaintext local artifacts

The intake store persists original paths, stored paths, filenames, source metadata, invoice metadata, and hashes (`accounting_agent/intake/store.py:103`, `accounting_agent/intake/store.py:249`). The local intake processor copies files into a hash/original-filename path (`accounting_agent/intake/local.py:261`). Approval packets include full extracted fields and document summaries (`accounting_agent/supplier_invoice/pipeline.py:208`). This is acceptable for synthetic fixtures, not client data.

Production fix:

- Per-client encrypted storage roots.
- No raw OCR/full document text in packets or audit logs by default.
- Redacted reviewer packets with references to controlled document storage.
- Data classification, retention periods, deletion/purge, export, and legal hold behavior.

### P0-7: Client separation is not implemented

Client mapping is placeholder-based. Unmatched intake becomes `client_id="unmapped"` by design, and the local demo uses `fixture_client` (`accounting_agent/local_demo.py:448`). There is no per-client database, storage root, credential profile, policy threshold set, or access boundary.

Production fix:

- Per-client config, storage, database namespace, Fortnox tenant/company binding, and M365 source allowlist.
- Hard fail for unmapped sources before extraction or proposal work on real data.
- Cross-client duplicate and metadata leak tests.

### P0-8: Fortnox live write path still needs production-grade gates

The live supplier-invoice draft path now requires a reviewed permit (`accounting_agent/adapters/fortnox.py:410`), and forbidden payload markers are blocked (`accounting_agent/adapters/fortnox.py:614`). Still missing: environment allowlist, persistent idempotency, trusted permit lookup, current Fortnox API semantic verification, response redaction, sandbox/prod separation, and proof that a Fortnox "draft" cannot post/book/approve/pay.

Production fix:

- Keep all Fortnox behavior dry-run until a separate live-integration task.
- For live sandbox only, require explicit environment gates, persistent permit/idempotency stores, and a test token outside repo.
- Production write enablement should remain separate from sandbox enablement.
- Final posting, supplier invoice approval, payment, deletion, invoice sending, and settings changes remain forbidden.

### P0-9: Microsoft 365 real intake does not exist safely yet

The M365 slice is local/mock only. This is good. There is no Graph token storage, no tenant/client allowlist enforcement, no mailbox/folder allowlist, no dry-run listing stage, no download staging boundary, and no keychain/secret manager integration.

Production fix:

- Add Graph adapter only behind `M365_GRAPH_ENABLED=true`.
- Use least-privilege read scopes only; no `Mail.Send`.
- Store secrets in OS keychain or a real secret manager, not SQLite or files.
- Implement dry-run source listing before download.
- Hard fail for unmapped client/source rules.

### P0-10: Duplicate, VAT, bank-detail, and unauthorized-write protections are split across helpers

The supplier pipeline detects duplicate invoices (`accounting_agent/supplier_invoice/pipeline.py:155`), changed bank details (`accounting_agent/supplier_invoice/rules.py`), and VAT uncertainty, but the adapter only sees a payload and permit. A caller that bypasses the pipeline can omit risk facts from `PolicyContext`.

Production fix:

- Make adapters require a persisted case/proposal id and load the canonical risk decision from the database.
- The permit should bind source document ids, duplicate status, VAT status, supplier match status, and bank-detail status.
- Add tests proving duplicates, uncertain VAT, changed bank details, unknown suppliers, and locked periods cannot reach a live adapter even if a caller hand-builds a payload.

## Bypass Paths To Close

- Agent omits `duplicate_risk`, `vat_confidence`, or `bank_details_changed` and receives a lower policy mode.
- Agent instantiates `PermitIssuer` and supplies fake review labels.
- Agent constructs an `ExecutionPermit` dataclass directly.
- Agent imports raw `HttpFortnoxTransport` or `FortnoxAdapter` instead of using `RestrictedFortnoxMCP`.
- Agent calls a future raw Fortnox MCP server if it is ever registered beside the restricted facade.
- Agent uses a new source path/client mapping rule to put real documents under `unmapped` or the wrong client.
- Agent relies on gnubok shadow output as if it were a blocking safety control even though it is explicitly fail-soft.
- Agent writes or shares `.local` artifacts containing extracted fields, paths, bank details, or raw source text.

## Microsoft 365 Safety

Current state: no live Graph connection. This is the correct state for now.

No-go reasons:

- No token storage design.
- No tenant/mailbox/drive/folder allowlist.
- No dry-run source listing.
- No secret manager or keychain integration.
- No retention/deletion handling for downloaded attachments.
- No client isolation.

## Fortnox Safety

Current state: dry-run by default; real writes require explicit config and reviewed permit after this audit hardening.

No-go reasons:

- Raw adapter/transport import surface remains.
- Trusted approval authority is missing.
- Persistent idempotency is missing.
- Current Fortnox create semantics are not verified in this audit.
- Error and response handling can still carry client data.
- Production/sandbox separation is not strong enough.

## Email Safety

Current state: safe for draft text only. `draft_missing_info_email(...)` returns `send_status="draft_only_not_sent"` and `EmailWriteAdapter` does not send.

No-go reasons:

- No send adapter should be added until approval identity, recipient allowlists, message redaction, and audit are production-grade.

## gnubok Shadow-Ledger Safety

Current state: useful as local advisory validation. It is not a source of truth.

No-go reasons:

- Shadow validation is fail-soft by design.
- BAS/VAT coverage is deliberately incomplete.
- No real gnubok runtime, client isolation, import/export safety, or legal-accounting guarantees.

## Prioritized Fix List

1. Keep live Microsoft 365, Fortnox writes, email sending, client documents, payments, filings, deletes, settings changes, and supplier bank updates disabled.
2. Implement fail-closed policy evidence: missing/unknown duplicate, VAT, OCR, supplier, bank-detail, client mapping, source document, or period state must not default to safe.
3. Build a trusted approval and permit store: approval request id, actor, role, no self-approval, immutable event linkage, permit lookup by adapters.
4. Add persistent idempotency and adapter event storage before any live Fortnox sandbox attempt.
5. Lock down agent-facing tool exposure to the restricted facade only; add tool-inventory tests.
6. Add encrypted per-client storage/database boundaries and hard fail for `unmapped` real sources.
7. Centralize redaction and stop storing raw extracted fields/full source text in audit and reviewer artifacts.
8. Add tamper-evident audit logs with hash chaining and actor identity.
9. Add Microsoft Graph only as a separate read-only, explicitly enabled adapter with keychain/secret-manager token handling.
10. Re-check current Fortnox API semantics before any sandbox write; prove supplier-invoice draft creation cannot book, approve, send, pay, or alter supplier settings.
11. Add bypass tests for direct permit construction, omitted risk facts, duplicate invoices, changed bank details, uncertain VAT, unknown suppliers, and locked periods.
12. Keep bank reconciliation fixture-only; before any real bank feed or Fortnox reconciliation adapter, add persistent idempotency, trusted approvals, client isolation, and adapter/gateway tests.
13. Keep architecture docs current as the implementation changes. The
    post-implementation audit refreshed the old docs-only wording, but future
    implementation slices should update the architecture and safety docs in the
    same change.

## Final Decision

**NO-GO for real Microsoft 365, Fortnox, or client data.**

Allowed now:

- Synthetic fixtures.
- Local dry-run demos.
- Local approval-packet experiments.
- Mock/restricted Fortnox facade tests.
- gnubok local shadow comparisons on synthetic data.

Forbidden now:

- Real Microsoft 365 tenant/mailbox/OneDrive/Teams data.
- Real Fortnox credentials or live Fortnox writes.
- Real client supplier invoices, receipts, bank statements, or bookkeeping data.
- Email sending.
- Payments, filings, final posting, supplier invoice approval, deletes, settings changes, or supplier bank-detail updates.
