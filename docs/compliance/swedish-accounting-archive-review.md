# Swedish accounting and archive external review brief

Status: PRELIMINARY — NOT APPROVED

This brief collects questions for qualified Swedish accounting and legal review.
It is not an opinion, statutory-archive designation or compliance claim. It does
not authorize real-client data. Until the supported record classes and controls
are accepted, the product remains synthetic-only and cannot present itself as a
statutory archive.

## Proposed narrow launch scope to review

Candidate workflows are supplier-invoice preparation with Fortnox/Microsoft 365
and read-only NetSuite reconciliation/close. Customer ERPs remain authoritative
ledgers. Candidate archive material may include accepted originals,
presentation copies, manifests, processing history, policy/mapping versions and
review evidence. Payroll, tax filing, payments, customer invoice sending, final
posting, ERP approval, deletion, settings and supplier-bank-detail changes are
excluded. Reviewers must narrow or reject this scope rather than infer coverage.

## Questions requiring an external decision

| Topic | Question/evidence requested | Decision |
| --- | --- | --- |
| Record classes | Which originals, verifications, system documentation, treatment history and agreements are accounting information for each workflow? | PENDING |
| Receipt/original form | What exact received form/format must be preserved, and when is a transfer or destruction permissible? | PENDING |
| Presentation | Which system, software/version and documentation must remain available to present records throughout retention? | PENDING |
| Retention endpoint | How is the seventh-year endpoint calculated for calendar and split fiscal years, reorganizations, cessation and holds? | PENDING |
| Storage location | Which Sweden/EEA storage, access, notification and immediate-presentation conditions apply to each architecture/provider? | PENDING |
| Integrity/provenance | Are checksum, manifest, immutable-version, process-history and audit-root controls sufficient for the supported records? | PENDING |
| Format migration | What validation and documentation are needed when creating a new readable version while retaining the original? | PENDING |
| ERP handoff | Which source remains authoritative, and how should exports/drafts/reconciliations be evidenced without double-booking ambiguity? | PENDING |
| Legal holds/conflicts | How should holds, data-subject rights, contract exit and statutory retention conflicts be decided and documented? | PENDING |
| Tenant exit/cessation | Which exports, viewers, keys, instructions and custody transfer are needed for continued accessibility? | PENDING |
| International use | Which Sweden-specific controls can be reused as engineering foundations without implying another jurisdiction's compliance? | PENDING |

## Source observations to validate

BFN currently explains that accounting information is preserved for seven years
after the calendar year in which the financial year ended, and gives a split
financial-year example resulting in seven years and six months. BFN also
discusses received electronic format, presentation choices, transfer/destruction
conditions and storage outside Sweden. These statements are inputs to review,
not a complete retention engine specification.

- [BFN, Arkivering](https://www.bfn.se/fragor-och-svar/arkivering/)
- [Sveriges riksdag, Bokföringslag (1999:1078)](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/bokforingslag-19991078_sfs-1999-1078/)

The reviewer must record the source version/date, assumptions, entity and fiscal
year cases, supported record classes, required controls, exclusions and change
triggers. Repository tests may verify the accepted formula later; they cannot
make the legal/accounting decision.

## Required acceptance evidence

- Signed or otherwise independently attributable review bound to architecture,
  data map, workflow and code/release revision.
- Explicit supported and excluded record classes.
- Testable retention, preservation, presentation, location, access, migration,
  hold, export and exit requirements.
- Named owner for monitoring BFN/law changes and revalidation.
- No unresolved ambiguity for the first pilot entity.

## Approval record

- Decision: PENDING
- Required reviewers: qualified Swedish accounting professional; Swedish
  accounting/archive counsel; archive control owner; product safety owner
- Supported scope and revision: PENDING
- Source check and review date: PENDING
