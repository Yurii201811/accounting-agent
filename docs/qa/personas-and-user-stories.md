# Personas and user stories

`qa/traceability.json` is the machine-readable source of truth. It maps every public Python symbol, all nine CLI commands, and all eight cockpit sections to a story, acceptance criteria, test evidence, safety class, and owner. This page is a readable index; changes belong in the JSON catalog first and must pass `tests/test_qa_traceability.py`.

| ID | Persona | Release journey | Primary evidence |
| --- | --- | --- | --- |
| QA-US-001 | Small-firm accountant | Run client-scoped intake and understand ready versus blocked work without contacting an external system. | Microsoft 365 intake and cockpit tests |
| QA-US-002 | Accountant | Prepare supplier invoices while duplicates, unknown suppliers, changed bank details, uncertain VAT, and locked periods stop for review. | Supplier-invoice and risk-review tests |
| QA-US-003 | Accountant | Reconcile exact, partial, duplicate-looking, fee, large unknown, and unmatched transactions without double consumption. | Reconciliation and locale-safety tests |
| QA-US-004 | Senior accountant or controller | Review escalations, preserve segregation of duties, and assess close readiness while period locking remains human-only. | Approval/permit and close tests |
| QA-US-005 | Auditor | Verify provenance, exact scope, append-only evidence, hash chains, and tamper detection. | Evidence, approval, and repository-safety tests |
| QA-US-006 | Agent operator | Run bounded preparation with checkpoint, resume, cancel, lease recovery, and a human terminal decision. | Autonomy and v1 integration tests |
| QA-US-007 | ERP integrator | Evaluate Fortnox, NetSuite, Oracle, SAP, Odoo, SIE, and CSV under one fail-closed connector contract. | Connector, Fortnox, and restricted-MCP tests |
| QA-US-008 | Model operator | Use deterministic or local advisory models without exposing credentials or granting execution authority. | Model-routing and autonomy tests |
| QA-US-009 | International accountant | Represent currency precision, locale amounts, evidence-bound FX, and jurisdiction packs without claiming unsupported compliance. | Money, journal, locale, and platform tests |
| QA-US-010 | Public preview viewer | Inspect a useful synthetic demonstration with no local path, private course content, secret, or external authority. | Cockpit, preview-bundle, and fixture-policy tests |
| QA-US-011 | Beginner or professional user | Use English or Swedish, Guided or Expert detail, and six role perspectives with accessible keyboard behavior. | Playwright matrix, axe, and manual VoiceOver evidence |
| QA-US-012 | Adversarial caller or failure operator | Prove forged permits, replay, redirects, proxies, hostile paths, corruption, and concurrency fail closed. | Permit, Fortnox, autonomy, storage, and privacy tests |

## Acceptance rule

A test file name alone is not traceability. Each story in the JSON catalog must contain concrete acceptance criteria and executable test evidence, and each public surface must reference at least one valid story. Any new public symbol, CLI command, or cockpit section must update the catalog in the same change.
