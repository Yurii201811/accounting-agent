# Data protection impact assessment (DPIA) working template

Status: PRELIMINARY — NOT APPROVED

This is a conservative working template, not a completed DPIA or legal opinion.
It does not authorize real-client data. The accountable controller, privacy
lead/DPO and qualified counsel must decide applicability, scope, residual risk
and any need for prior consultation before launch.

IMY describes a DPIA as an ongoing documented process for personal-data
processing likely to result in high risk. Its minimum content includes the
planned processing and purpose, necessity and proportionality, risks to
individuals, and planned safeguards. This program treats DPIA completion as a
release gate without claiming that this draft satisfies Article 35.

Source: [IMY, Konsekvensbedömning enligt GDPR](https://www.imy.se/verksamhet/dataskydd/det-har-galler-enligt-gdpr/konsekvensbedomning/).

## Assessment ownership and scope

- Controller(s), representative and DPO: PENDING
- Processor and subprocessors: PENDING
- Product/architecture revision: PENDING
- Supported workflows and excluded workflows: PENDING
- Consultation with affected people/representatives or documented reason not to:
  PENDING
- Review trigger and review interval: PENDING

## Planned processing description

Assess identity and membership, direct upload, approved Microsoft Graph intake,
read-only ERP sync, deterministic extraction/risk review, human approval,
statutory archive, audit, support, optional hosted/local AI, edge execution and
the isolated draft gateway separately. For each, document data subjects, fields,
sources, recipients, location, volume/frequency, retention, security, automated
elements and human authority.

## Necessity and proportionality questions

- Which fields and document regions are necessary for each purpose?
- Can metadata, deterministic rules or local processing replace raw-document or
  hosted-model processing?
- Are role, entity and purpose restrictions enforced below application code?
- How are transparency, access, correction, objection, restriction, portability
  and erasure requests handled when accounting retention applies?
- What prevents AI advice becoming a solely automated accounting decision?
- Are retention and archive obligations separated from operational telemetry and
  rejected/quarantined bytes?

## Preliminary rights-and-freedoms risk register

| Risk scenario | Potential effect on people | Required safeguards | Residual risk |
| --- | --- | --- | --- |
| Cross-tenant invoice or identity disclosure | Financial/privacy harm, fraud | RLS, composite scope, object context, adversarial tests | PENDING |
| Incorrect role or self-approval | Unfair or unauthorized accounting action | IdP membership, segregation, step-up, immutable audit | PENDING |
| Excessive mailbox or ERP scope | Disproportionate collection | Folder/entity allowlists, minimal OAuth, scope-drift freeze | PENDING |
| Hosted-model disclosure or silent fallback | Unexpected recipient/transfer | Explicit consent, classification, redaction, region/retention policy, visible stop | PENDING |
| Inaccurate extraction or biased advice | Financial/administrative consequence | Deterministic validation, human review, provenance, correction | PENDING |
| Archive over-retention or unlawful deletion | Rights conflict or record loss | Reviewed retention classes, legal holds, export, deletion decision log | PENDING |
| Support or incident over-access | Secondary disclosure | Metadata-only support, dual-approved break glass, customer-visible audit | PENDING |

## Measures and validation evidence

Technical measures, organizational controls, independent test results, provider
terms, data-location proof, accessibility, training/AI-literacy, incident and
restore exercises must be linked here with immutable digests. Planned controls
or a passing unit test cannot be recorded as implemented assurance.

## Residual-risk decision

- High residual risk after measures: PENDING
- Prior consultation assessment: PENDING
- DPO advice and response: PENDING
- Controller acceptance/rejection and conditions: PENDING

## Approval record

- Decision: PENDING
- Required reviewers: accountable controller; privacy lead/DPO; security owner;
  qualified legal counsel
- Approved revision and date: PENDING
- Next review trigger/date: PENDING
