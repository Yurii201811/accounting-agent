# Production data map

Status: PRELIMINARY — NOT APPROVED

This is an architecture discovery template, not a record of live processing. It
does not authorize real-client data. Controller/processor roles, legal bases,
retention, transfer safeguards and provider approvals require independent review
for each supported workflow and customer agreement.

## Current public-core boundary

The repository currently processes invented fixtures and operator-created local
artifacts only. It has no authenticated SaaS, production object store, statutory
archive, customer mailbox connection, production ERP token, billing, support
access or hosted-model client. `.local/` evidence is excluded from source
control and is not a certified archive.

## Proposed production data domains

| Domain | Candidate data | Proposed source | Proposed authoritative store | Access boundary | Decision still required |
| --- | --- | --- | --- | --- | --- |
| Identity/membership | Name, work email, IdP subject, auth strength, roles | Cognito/enterprise IdP/Signicat | Identity broker + tenant membership DB | Tenant/entity-scoped RBAC | Role attribution, BankID purpose, retention |
| Client/entity registry | Organization identifiers, fiscal settings, jurisdiction | Tenant admin and ERP | PostgreSQL | Membership-derived scope | Controller instructions, field minimization |
| Intake | Invoice/document bytes and metadata | Direct upload or approved Graph scope | Quarantine then immutable archive | Exact tenant/client/entity envelope | Supported media, legal basis, rejected-file retention |
| Accounting facts | Suppliers, invoices, journals, balances, periods, dimensions | Read-only ERP sync | Encrypted snapshots + canonical PostgreSQL | Connector + entity binding | Field allowlists, source-of-truth conflict rules |
| Review/approval | Findings, comments, decisions, identity, version | Authenticated users | PostgreSQL + audit | Segregation of duties | Signature/step-up requirements |
| Archive | Original/presentation bytes, hashes, manifests, holds | Accepted records | Stockholm immutable object storage | Archive role + entity scope | Supported record classes and retention formula |
| Audit/telemetry | Access and control events, request IDs, operational metrics | Application/services | Append-only audit + PII-minimized telemetry | Security/audit roles | Field-level redaction and operational retention |
| AI advisory | Minimized prompt, classification, route, output, cost | Approved case evidence | Policy record + approved output/evidence | Tenant consent and classification | Provider, region, retention, no-training terms |
| Support | Metadata, consent, case notes | Customer request | Support system | Metadata-only by default | Break-glass design and contractual basis |

## Planned flow boundaries

1. Upload or Graph data enters quarantine; malware/media/decompression controls
   run before extraction. Rejected bytes follow an approved short retention.
2. Isolated Stockholm workers derive text and presentation copies. Raw documents
   do not enter ordinary logs or model prompts.
3. Deterministic rules create canonical facts, risk findings and review packets.
4. Authenticated humans decide; agents cannot approve or call connectors.
5. Accepted record classes move to immutable originals, derived versions and
   manifests. ERP remains authoritative ledger unless a reviewed exception says
   otherwise.
6. Read-only connectors reconcile counts, cursors and hashes before sync success.
7. Any future external draft crosses a separate gateway only after exact signed
   command reload and read-after-write comparison.

## Data-location and transfer questions

Authoritative production and archive data is proposed for AWS Stockholm. Each
identity, email, observability, model, support and security service must still
be assessed for processing location, remote access, subprocessors and any
third-country transfer. “Region configured” is not proof of exclusive regional
processing.

## Required completion evidence

- Approved field inventory and classification per data domain.
- Named controller, processor and subprocessor roles per workflow.
- Purpose, legal basis/instruction, recipients, retention and deletion event.
- Complete transfer map including support and telemetry access.
- Data-subject request, tenant export and deletion/retention-conflict procedures.
- Architecture diagrams and test evidence bound to the reviewed revision.

Reference: [IMY ROPA guidance](https://www.imy.se/verksamhet/dataskydd/det-har-galler-enligt-gdpr/fora-register-over-behandling/).

## Approval record

- Decision: PENDING
- Required reviewers: privacy lead/DPO; security architect; service owner;
  Swedish accounting/archive reviewer
- Approved architecture revision: PENDING
- Data-flow validation date: PENDING
