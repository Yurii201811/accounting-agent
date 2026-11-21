# Subprocessor approval and change policy

Status: PRELIMINARY — NOT APPROVED

This is a proposed governance policy. It does not authorize real-client data,
approve a provider, establish a transfer mechanism or satisfy a customer notice
requirement. Every subprocessor remains disabled until contract, security,
privacy, location and workflow-specific evidence is accepted.

## Default policy

No subprocessor is approved by repository text, environment configuration,
procurement intent or technical availability. Before activation, record the
service and legal entity, exact purpose/data classes, processing/storage/support
locations, subprocessors, retention/deletion, training use, security evidence,
incident terms, continuity/exit, DPA flow-down, transfer assessment and customer
authorization. Scope expansion repeats the review.

IMY guidance notes that a processor should obtain the controller's prior written
authorization before engaging a subprocessor and apply equivalent data-
protection obligations. The exact contractual implementation requires counsel.

Source: [IMY, Personuppgiftsbiträdesavtal](https://www.imy.se/verksamhet/dataskydd/det-har-galler-enligt-gdpr/personuppgiftsansvariga-och-personuppgiftsbitraden/personuppgiftsbitradesavtal/).

## Candidate register (not approvals)

| Candidate function | Candidate class | Permitted data/purpose | Review state |
| --- | --- | --- | --- |
| Stockholm cloud infrastructure | Infrastructure/managed services | NONE until review | NOT APPROVED |
| Enterprise identity federation | Identity provider/broker | NONE until review | NOT APPROVED |
| BankID integration | Identity-proofing broker | NONE until commercial/legal review | NOT APPROVED |
| Microsoft Graph | Mail/file intake | NONE until tenant consent and scope review | NOT APPROVED |
| Hosted model provider | Optional advisory processing | NONE until tenant opt-in and provider review | NOT APPROVED |
| Monitoring/support provider | PII-minimized operations | NONE until field and access review | NOT APPROVED |
| Penetration-test supplier | Controlled assessment evidence | Synthetic/staging only until contract | NOT APPROVED |

## Approval workflow

1. Service owner submits a purpose-limited assessment with the data-map and ROPA
   changes, alternatives and exit plan.
2. Security validates architecture, encryption, access, incident, vulnerability,
   continuity, deletion and independent-assurance evidence.
3. Privacy/legal reviews roles, DPA, locations, onward subprocessors, transfers,
   retention, rights and notice/objection terms.
4. Accounting/archive owner reviews any effect on original, presentation,
   retention, access and evidence requirements.
5. Authorized customer notice/approval is completed where applicable.
6. A separately controlled deployment allowlist activates only the reviewed
   provider, region, data classes and purpose. Drift freezes processing.

## Change, incident and exit

Material legal-entity, subprocessor, location, purpose, data, model-training,
security or retention changes trigger review and customer communication before
activation. Provider incidents follow `docs/security/incident-response.md`.
Exit requires access revocation, export/continuity validation, contract-aligned
deletion evidence and retained documentation of lawful exceptions.

## Approval record

- Decision: PENDING
- Required reviewers: privacy lead/DPO; qualified counsel; security owner;
  service owner; accounting/archive owner
- Approved register location: PENDING
- Customer notice/objection procedure test: PENDING
