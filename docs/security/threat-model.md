# Overview

Status: PRELIMINARY — NOT APPROVED

This repository-scoped threat model was generated for the public Accounting
Agent core. It does not authorize real-client data, live-provider access, or a
production deployment. It distinguishes the current public core from the
future commercial cloud described in `docs/production_program.md`; planned
cloud controls are assumptions and requirements, not existing mitigations.

The current public core is a Python library and nine-command local CLI. Its
runtime surfaces are synthetic fixture intake, deterministic accounting and
risk rules, immutable tenant/document/archive contracts, typed canonical
accounting records, read-only connection/sync/reconciliation contracts,
identity-bound approval and external-draft envelopes, tenant-qualified advisory
model policies, an atomic durable execution-attempt store, local SQLite stores,
append-oriented evidence, guarded Fortnox reads, a loopback-only local-model
adapter, and generated static cockpit artifacts. It has no HTTP application,
identity provider, multi-tenant cloud database, managed archive, production
secrets broker, draft gateway, or authorized external write. The highest-value
current assets are accounting integrity, tenant/client and legal-entity
separation in local records, approval and permit provenance, evidence integrity,
operator credentials, local files, and the structural absence of posting,
payment, filing, sending, approval, deletion, settings, and
supplier-bank-detail authority.

The future commercial cloud is expected to add authentication, multi-tenant
storage, statutory archive functions, connector credentials, workers, hosted
models, and a separately deployed draft gateway. Those additions would make
identity, tenant boundaries, archive immutability, key management, service
availability, data residency, audit roots, and external-action safety primary
production assets. They must receive a separate architecture and deployment
review before any real-client byte is accepted.

# Threat Model, Trust Boundaries, and Assumptions

## Actors and controlled inputs

- **Untrusted users or fixture authors** can control CLI arguments, fixture
  content, filenames, document text, invoice fields, currency/locale strings,
  connector identifiers, model prompts, and generated-output destinations.
- **Untrusted external systems** can control Fortnox response status, headers,
  size and JSON shape, and a local Ollama-compatible endpoint's responses. A
  future ERP, mailbox, identity provider, model provider, queue message, browser
  session, or webhook is also untrusted until authenticated and reconciled.
- **Operators** control local paths, environment configuration, provider
  enablement, connector bindings, policy configuration and deployment inputs.
  Operator intent does not make hostile data safe and must not bypass policy.
- **Developers and maintainers** control source, dependencies, CI, package
  metadata and releases. A compromised contribution, action or dependency can
  subvert every local invariant and is therefore a supply-chain boundary.
- **Models, subagents and computer-use tools** are untrusted advisers. Their
  text and proposed structures are data, never approval, identity, policy, or
  execution authority.

## Current trust boundaries

1. **Filesystem and package boundary.** `accounting_agent/cli.py`, local intake,
   preview builders and QA scripts cross from operator-supplied paths and
   packaged fixtures into local SQLite and generated files. Path confinement,
   symlink rejection, bounded fixture formats and privacy scans must hold.
2. **Accounting authority boundary.** `policy.py`, `approvals.py`, `permits.py`,
   `external_writes.py` and `restricted_fortnox_mcp.py` separate proposals from
   human decisions and external actions. A model, UI role, connector declaration
   or caller-supplied object cannot mint trusted approval or weaken a decision.
3. **Client and entity boundary.** Canonical client/entity identifiers, exact
   evidence binding, SQLite uniqueness and connector bindings prevent records,
   duplicates, approvals, permits and results from being substituted across
   scopes. Current local isolation is not a substitute for cloud RLS.
4. **Network boundary.** `adapters/fortnox.py` permits guarded HTTPS GET only,
   validates Fortnox origin/path/query, disables redirects and environment
   proxies, bounds response bodies, and structurally rejects HTTP POST. The
   local-model boundary validates a loopback endpoint and disables redirects
   and proxies. No other runtime network authority is assumed.
5. **Evidence boundary.** Hashes, policy versions, approval bindings, permit
   expiry and append-only permit IDs make later mutation detectable. Local JSON,
   JSONL and SQLite remain operator-writable and are not a certified immutable
   archive or independent audit anchor.
6. **Durable attempt boundary.** `execution_attempts.py` atomically binds one
   idempotency key to permit, client, entity, case, provider, action and payload.
   Completed and ambiguous outcomes are immutable; ambiguity cannot auto-retry.
   This records authority and observations but performs no provider call.
7. **Canonical fact and synchronization boundary.** `contracts/canonical.py`
   and `contracts/sync.py` bind typed accounting facts to exact tenant, client,
   entity, connection, sync, checkpoint, snapshot and mapping provenance.
   Completion requires ordered cursor chains plus source count/hash
   reconciliation. These are immutable interchange records, not proof that an
   untrusted provider or mapping was substantively correct.
8. **Model and draft-envelope boundary.** `contracts/model.py` records one
   tenant-qualified advisory provider with explicit classification, region,
   retention, redaction, consent, evidence and budgets. `contracts/commands.py`
   records MFA-backed human decisions and hash-only supplier-invoice draft
   envelopes. Construction, parsing or hashing grants no provider credential,
   network capability, approval or execution authority. An external receipt is
   safe only after exact read-back of an unbooked reversible draft; every other
   outcome freezes for human review.
9. **Presentation boundary.** The generated cockpit and public preview render
   synthetic or local artifacts. They must not turn attacker-controlled text
   into active HTML, load unexpected network resources, disclose local paths,
   or imply that navigation or role perspective changes authority.
10. **Release boundary.** Source archives, wheels, CI actions, npm packages and
   deployment artifacts cross from development into user environments. The
   provenance scan, locked dependencies, reproducible builds, secret scanning,
   package inspection and signed-release plan reduce but do not eliminate this
   risk.

## Security invariants

- Unknown suppliers, possible duplicates, changed bank details, uncertain VAT,
  missing evidence, locked periods, and scope/environment drift stop for review.
- Final posting, approval, sending, payment, filing, deletion, settings changes
  and supplier-bank-detail changes remain structurally absent.
- A permit is short-lived, single-scope, exact-payload and exact-policy bound;
  duplicate permit IDs cannot replace prior material.
- Provider, tenant/client, legal entity and environment bindings are rechecked
  at the execution boundary; request-body labels alone are not authority.
- Canonical money uses interoperable-range integer minor units, journals
  balance, known lifecycle states cannot silently regress or reactivate from
  inactive, and a locked period cannot reopen through a record successor.
- A read sync cannot complete without ordered, cursor-continuous checkpoints
  and exact per-resource source count/hash reconciliation. Write capabilities
  are rejected from connection contracts.
- Model policies select exactly one provider, reject credentials, keep private
  course material local, bind consent to fresh authenticated evidence, require
  hosted-provider qualification and sensitive data redaction, and structurally
  forbid silent fallback, approval and execution authority.
- External-draft commands contain hashes and scope only. They bind the exact
  connection, evidence, policy decision, approval receipt, approval decision,
  permit and payload; they expose no payload bytes, credentials or execute
  method.
- External ambiguity fails closed. Timeouts cannot be treated as success, and a
  future draft gateway must read after write before resolving ambiguity.
- Receipt safety is command-bound: a caller must verify the exact command and
  matching payload/read-back hashes before an exact-match receipt can avoid a
  freeze.
- Raw client documents, credentials, tokens and bank secrets do not enter source
  control, ordinary logs, model prompts, synthetic tests or public previews.
- International schemas do not imply jurisdictional, tax, filing or archive
  compliance. Unsupported compliance questions stop for qualified review.

## Assumptions and exclusions

Local users currently control their own machine and data directory. Protection
against a fully compromised local administrator is out of scope for the public
core, though tamper evidence should still expose accidental or unauthorized
mutation. Denial of service against a single local CLI run is lower severity
than corruption or cross-scope substitution. Live cloud authentication, RLS,
S3 Object Lock, KMS signatures, OAuth brokerage, production queues, BankID and
the external-draft gateway do not exist in this repository and cannot be
credited as mitigations.

# Attack Surface, Mitigations, and Attacker Stories

## Accounting and authority manipulation

An attacker may alter invoice fields, supplier identity, bank details, VAT
confidence, currency, period state, reviewer claims, evidence hashes, policy
versions, approval decisions or permit payloads to obtain a lower-risk outcome.
Deterministic validation, monotonic policy, independent reviewer roles, exact
hash bindings, append-only permit IDs and reload-before-use requirements are the
principal current mitigations. Typed canonical records additionally reject
non-integer money, unbalanced journals, forged source lineage, lifecycle
regression and locked-period reopening. Security review must prioritize any
route that skips these controls, accepts stale approval, replays a permit, lets
a preparer approve their own work, or exposes a forbidden external method.

## Scope confusion and future tenant escape

Unicode aliases, empty identifiers, caller-supplied client/entity fields,
connector/environment mismatches and storage keys without composite scope can
cause cross-client substitution. Canonical identities and scope-bound records
mitigate local cases. In the future cloud, every table, foreign key, object key,
cache key, queue lease and audit record must carry tenant, client and legal
entity, with authenticated membership revalidated server-side and RLS tested
under adversarial roles.

## Files, documents and generated content

Hostile paths, symlinks, decompression bombs, oversized inputs, active PDF
content, malformed Unicode, spreadsheet formulas and embedded prompt injection
can target intake, evidence and previews. Current fixture and evidence tooling
rejects symlinks and suspicious/private material, confines release artifacts,
and uses synthetic inputs. Production intake still requires quarantine,
malware scanning, media and decompression limits, isolated extraction, active
content rejection, safe rendering, immutable originals and provenance.

## Connector, HTTP and local-model traffic

SSRF, credential leakage, redirect abuse, proxy capture, unsafe path/query
encoding, response exhaustion and malformed JSON are realistic where network
transports exist. Fortnox reads use an exact HTTPS origin, safe resource grammar,
no redirects/proxies and bounded responses; invalid preflight must make zero
transport calls. The Ollama route is loopback-only and advisory. Future OAuth,
Graph, NetSuite and gateway services require minimal scopes, encrypted secrets,
revocation, rate limits, checkpoints, reconciliation, kill switches and a
separate threat model. A forged provider response must never be accepted without
ordered checkpoint-chain and source-count/hash reconciliation or
read-after-write comparison. Current connection/sync contracts reject write
capabilities and incomplete completion evidence, but contain no OAuth client or
transport and cannot establish the truth of provider-supplied source totals.

## Models, agents and computer use

Prompt injection may ask a model or subagent to reveal data, change scope,
approve work, call a connector, relax policy or use credentials. Current model
routing is advisory and deterministic policy remains authoritative. The
production route contract requires one tenant-qualified provider, explicit
classification, region, retention, redaction, budgets, qualification evidence
and no silent fallback; it has no invocation method. Future agents must receive
exact capability envelopes, redacted evidence references, budgets and signed
structured-result schemas. No agent may hold a raw connector or write tool,
approve its own work, or silently fall back to a hosted provider.
Computer use must remain supervised and read-only; login, credential, origin or
unexpected-instruction changes stop the task.

## Storage, concurrency and recovery

SQLite corruption, lock races, truncated writes, stale leases and process
crashes can duplicate or lose decisions. Transactions, uniqueness constraints,
schema/version checks, leases, exact-scope execution reservations, immutable
terminal states, integrity tests and explicit recovery paths are current
mitigations. Local files are not an immutable archive. Production must
add PostgreSQL isolation/RLS, transactional outbox semantics, encrypted backups,
independent restore checks, WORM archive storage and externally anchored audit
roots.

## UI, API and identity in the future cloud

The current repository has no HTTP API, session or production authentication.
The planned cloud will introduce IDOR, forged JWT claims, role escalation,
session revocation, CSRF, XSS, injection, unsafe object access, support-access
abuse and confused-deputy risks. Tenant administration must not imply accounting
approval, BankID identity must not grant roles, and all command endpoints must
enforce authenticated membership, entity scope, idempotency and optimistic
versioning. These are required future controls, not current findings.

## Supply chain and operational compromise

Malicious packages, GitHub Actions, leaked release credentials, unsigned images,
misconfigured infrastructure and unreviewed migrations could subvert all other
controls. Locked dependencies, least-privilege CI, secret scanning, SAST,
reproducible packages and artifact QA reduce present release risk. Production
still requires OIDC delivery, signed images, SBOMs, isolated accounts, two-person
promotion, migration rollback, monitored alerts, independent penetration tests
and restore/tabletop evidence.

# Severity Calibration

## Critical

- Cross-tenant disclosure or modification of real accounting records, identity
  material, connector secrets or archive objects in a deployed cloud.
- A route to post, approve, send, pay, file, delete, change settings or bank
  details despite the structural prohibition.
- Compromise of production signing, KMS or release authority enabling undetected
  alteration of archive/audit evidence or shipped code.

## High

- Forged or replayed approval/permit material that authorizes the wrong case,
  payload, policy, client, entity, provider or environment.
- SSRF or redirect/proxy abuse that leaks a Fortnox token or reaches a privileged
  internal service.
- Archive retention shortening, loss of required originals, or undetected audit
  tampering affecting a supported record class.
- Persistent stored XSS or authorization bypass in a future authenticated
  cockpit exposing another entity's financial information.

## Medium

- A confined local path traversal or stored-content issue requiring an operator
  to process a malicious fixture, without secrets or cross-client impact.
- A crash/retry defect causing duplicate proposals or stale checkpoints that
  remain visibly unposted and require human correction.
- Unintended hosted-model routing of synthetic or low-sensitivity content where
  no client data, credential or external authority is exposed.

## Low

- Information disclosure limited to synthetic examples, non-secret package
  metadata or local diagnostic state with no authority consequence.
- UI or availability defects in the static synthetic preview that do not hide a
  risk, change authority, expose private data or corrupt evidence.
- Resource exhaustion requiring trusted local operator control and affecting
  only a restartable synthetic run.

Severity increases with real data, cross-scope reach, persistent compromise,
credential exposure, accounting irreversibility, archive impact or bypass of
independent human authority. It decreases where the caller already has local
administrator control, all data is synthetic, the result is an obvious dry-run
failure, and no security boundary or accounting decision changes.

## Approval record

- Decision: PENDING
- Required reviewers: security owner; independent security assessor; product
  safety owner
- Reviewed revision: PENDING
- Review date: PENDING
- Notes: A repository document is not independent security assurance.

Repository: sha256:e7c461de6f8bfd676a7ecb697b004d84d3f30b82258754fd278098a92a1ce766
Version: 7e45e0ecd9e99e1eaf5468ba5a40889d02a71949

## Regeneration policy

`Version` is the exact code revision reviewed when this model was generated;
it is not a claim that the later documentation commit reviewed itself. Refresh
the model and both binding fields in `qa/production-gates.json` whenever a
public runtime, trust boundary, storage contract, network surface, authority
capability, or release candidate changes. Production readiness must reject a
missing, fabricated, or mismatched binding, and an external approval must name
the exact reviewed revision and document digest.
