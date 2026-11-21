# Security and privacy incident response plan

Status: PRELIMINARY — NOT APPROVED

This is a design and exercise template. It does not authorize real-client data,
live notification, production access or a production launch. Names, contact
routes, on-call coverage, decision authority, customer terms and regulator
jurisdiction remain pending before the first real-client byte.

## Scope and principles

The current public core is local and synthetic-only. This plan becomes relevant
to the future cloud, edge worker and managed connectors only after their exact
architecture is reviewed. Preserve evidence, minimize access, maintain tenant
isolation, stop external authority, and do not guess whether an event is a
personal-data breach, accounting-record incident or reportable event.

## Roles to appoint

| Role | Required authority | Named owner |
| --- | --- | --- |
| Incident commander | Coordinate containment and recovery | PENDING |
| Security lead | Forensics, credentials, infrastructure and evidence | PENDING |
| Privacy lead/DPO | Rights-and-freedoms assessment and notification advice | PENDING |
| Accounting/archive lead | Record integrity, retention and presentation impact | PENDING |
| Customer communications lead | Approved controller/customer notices | PENDING |
| Legal counsel | Privilege, contractual and regulatory assessment | PENDING |

No engineer, model or agent may send a regulator or customer notification
without the authorized human decision path. A processor must follow the
controller agreement and escalation route once approved.

## Response workflow

1. **Detect and record:** create a time-stamped incident ID, source, affected
   environment, suspected tenants/entities, data classes and reporter. Do not
   copy raw financial documents into ordinary tickets or chat.
2. **Contain:** revoke sessions and credentials, disable affected connectors or
   draft gateways, isolate workers, activate tenant/provider/global kill
   switches, and preserve immutable logs. Do not delete suspected evidence.
3. **Assess:** determine confidentiality, integrity and availability impact;
   affected people, record classes and providers; likelihood and severity; and
   whether accounting/archive evidence or external actions changed.
4. **Decide notifications:** privacy lead and counsel document the legal and
   contractual decision, recipients, content, deadline and decision owner.
5. **Eradicate and recover:** remove root cause, rotate credentials, verify
   manifests and audit chains, restore in isolation, reconcile every affected
   source, and require two-person production return.
6. **Learn:** document causal and contributing factors, corrective actions,
   owners and deadlines; update threat models, runbooks, tests and customer
   controls; repeat the exercise where the fix changes the path.

## Privacy incident decision record

IMY states that all personal-data incidents should be documented, including
what happened, affected data, consequences and mitigations. For a controller's
notification to IMY or another competent supervisory authority, the cited
guidance describes the applicable risk threshold and a 72-hour deadline after
awareness, with later information supplied as a complement where needed.
Notification to affected people follows a separate likely-high-risk test and,
when required, must occur without undue delay. A processor's notice to its
controller is also a separate route governed by applicable law and the approved
processor agreement. The accountable privacy and legal reviewers must apply
the current rules and contractual timing to the actual facts; this template
does not make that decision.

Record: awareness time; controller and processor roles; affected categories and
counts; risk analysis; safeguards; reasons to notify or not notify the authority
and affected people; decision time and owner; notification evidence; follow-up.

Source: [IMY, Hantering av personuppgiftsincidenter](https://www.imy.se/verksamhet/dataskydd/det-har-galler-enligt-gdpr/personuppgiftsincidenter/hantering-av-personuppgiftsincidenter/).

## Exercise and release gate

Before the first real-client byte, run at least these synthetic scenarios:
cross-tenant object access; stolen connector credential; archive-manifest
mismatch; malicious document/prompt injection; ambiguous external draft; lost
KMS access; database or region outage. Measure detection, containment,
notification decision and tenant restore. Unresolved critical/high findings or
unknown notification ownership block launch.

## Approval record

- Decision: PENDING
- Required reviewers: security owner; privacy lead/DPO; Swedish legal counsel;
  service owner; accounting/archive owner
- Named contacts and tested channels: PENDING
- Tabletop date and artifact digest: PENDING
