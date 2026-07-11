# Accounting Agent production program

This document is the durable program contract for evolving Accounting Agent
without weakening its public safety boundary. It is a roadmap and release-gate
definition, not a production-readiness claim. The current system is not production-ready
and remains synthetic-only.

## Open-source core and private cloud

The Apache-2.0 open-source core contains deterministic accounting contracts,
synthetic fixtures, local review workflows, dry-run or read-only adapters,
public documentation, and QA. The original 142 public v1 exports and all nine
CLI commands remain compatible through 1.x.

The private cloud is a separate repository and product boundary. Authenticated
membership, tenant storage, hosted operations, commercial service code,
production identity, deployment infrastructure, secrets, and provider-specific
runtime credentials do not belong in this public core. The private cloud may
consume a versioned public-core release; it must not make private implementation
an implicit capability of the open-source package.

## Safety ceiling

The public core can collect synthetic evidence, extract, validate, reconcile,
propose, explain, and assemble a human-review packet. The terminal state is
human decision.

Final ERP posting, supplier-invoice approval, invoice or email sending,
payments, tax filing, deletion, settings changes, and supplier bank-detail
changes remain structurally absent. Unknown suppliers, possible duplicates,
changed bank details, uncertain VAT, missing evidence, and scope or environment
drift fail closed for review. No role label, model, connector declaration,
cockpit action, or private-cloud plan can override this ceiling.

## Program phases

1. **Phase 0 — open-source baseline.** Licensing, governance, DCO, security,
   provenance, privacy, packaging, and publication gates.
2. **Phase 1 — versioned domain contracts.** Immutable tenant, document,
   archive, connector, reconciliation, approval, draft, and model-route types
   without breaking v1.
3. **Phase 2 — private-cloud API foundation.** Deny-by-default authentication,
   membership-derived scope, RBAC, idempotency, concurrency, RLS, and audit in
   the separate private repository, using local test adapters only.
4. **Phase 3 — infrastructure and delivery design.** Non-deploying IaC,
   environment separation, evidence retention, recovery targets, and
   approval-gated delivery definitions.
5. **Phase 4 — authenticated cockpit shell.** Accessible, role-aware review
   experiences whose navigation never grants authority.
6. **Phase 5 — bounded integrations.** Read-only fake transports and an
   isolated external-draft state machine that remains disabled without exact
   provider sandbox evidence.
7. **Phase 6 — verification and release checkpoint.** Traceability, local and
   artifact QA, independent reviews, and explicit remote/deployed/production
   state separation.

Completing a phase supplies evidence for the next one; it does not authorize
production use or collapse later gates.

## Release gates

The project records `local`, `artifact`, `remote`, `deployed`, and `production`
states separately. A green local run proves only the tested local revision.
External publication requires evidence-bound remote CI, deterministic package
inspection, a manual VoiceOver result for the exact preview, DCO and Git-history
review, provenance/privacy review, and legal and accounting review. Missing,
stale, mismatched, or ambiguous evidence is pending or failed, never passed.

Deployment and production are later decisions. Neither follows automatically
from publication, a package upload, a preview, or a completed automated test.

## External prerequisites

Before any real-client or live-provider use can even be evaluated, the program
requires independent legal/privacy and Swedish accounting review; provider
sandbox and reversible-semantics evidence; security architecture, penetration,
tenant-isolation, key-management, retention, and incident-response evidence;
manual accessibility acceptance; backup/restore and disaster-recovery
exercises; monitored operational ownership; and explicit human release
authority. These are prerequisites outside the current repository and are not
implied by code or documentation here.
