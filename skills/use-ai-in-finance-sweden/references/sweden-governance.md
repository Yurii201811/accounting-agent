# Sweden governance and source routing

**Law checked on: 2026-07-10. Recheck before production use or publication.**

This is operational compliance guidance, not legal, tax, audit, or accounting
advice. Apply the company's policy and obtain qualified review for the exact
entity, engagement, period, data, and system.

## Contents

- [Source hierarchy](#source-hierarchy)
- [Bookkeeping and evidence](#bookkeeping-and-evidence)
- [Storage, cloud, and vendor location](#storage-cloud-and-vendor-location)
- [GDPR and confidential data](#gdpr-and-confidential-data)
- [EU AI Act and Swedish governance](#eu-ai-act-and-swedish-governance)
- [Tax, annual reporting, and signatures](#tax-annual-reporting-and-signatures)
- [Professional overlays](#professional-overlays)
- [Swedish workflow context](#swedish-workflow-context)
- [Official source register](#official-source-register)

## Source hierarchy

For Swedish claims, prefer:

1. Current EU and Swedish law in the Official Journal, EUR-Lex, or Riksdagen.
2. Current BFN, Skatteverket, Bolagsverket, IMY, Finansinspektionen, PTS, and
   other competent-authority guidance.
3. Applicable professional standards and the company's approved policy.
4. Contractual terms, system documentation, and engagement-specific instructions.
5. Research, vendor material, and community experience as non-authoritative context.

Record URL, title, section, publication or update date, access date, effective
date, entity scope, and interpretation owner. Do not rely on model memory for a
rate, threshold, deadline, form, BAS year, BFN category, or VAT treatment.

## Bookkeeping and evidence

The Swedish Bookkeeping Act requires continuous bookkeeping, a voucher for each
posting, system documentation, treatment history, traceability, correction
records, and durable, accessible preservation of accounting information through
the seventh year after the end of the calendar year in which the financial year
ended. See the
[Bookkeeping Act (1999:1078)](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/bokforingslag-19991078_sfs-1999-1078/),
especially Chapters 4, 5, and 7.

BFN's bookkeeping guidance adds operational detail on non-erasable booked data,
separate correction entries, fixed reconciliation routines, documented deviations,
backup, automatic posting rules, information flows, and treatment history. Use
the current [BFNAR 2013:2 guidance](https://www.bfn.se/wp-content/uploads/vl13-2-bokforing.pdf)
and BFN's [September 2024 update notice](https://www.bfn.se/andringar-i-vagledningen-bokforing/).

Encode these controls:

- Preserve source-document identity, content, period, and a compliant archive.
- Keep proposed, reviewed, posted, corrected, rejected, and exported states distinct.
- Retain proposed account and tax treatment, rationale, rule/source version,
  exceptions, preparer, reviewer, timestamps, and correction linkage.
- Keep automated rules and data transformations versioned and reproducible.
- Export reconciliations, exceptions, approvals, and material changes into durable
  records; do not use a chat transcript as the sole accounting record.
- Do not erase or silently overwrite booked or locked-period information.
- Test backup, restore, export, and vendor exit.

Recording the material prompt or skill version, model/tool version, and
configuration is an implementation recommendation, not an explicit statutory
field. It supports system documentation and later evaluation when AI materially
influences processing.

## Storage, cloud, and vendor location

The Bookkeeping Act defaults to storage in Sweden. Electronic records and the
systems needed to present them may be located elsewhere in the EU only under the
Act's conditions, including authority notification, immediate electronic access
for control, and printing in Sweden. Outside-EU storage has narrower conditions
or permission routes. Read the current text in
[Chapter 7, Sections 2–4](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/bokforingslag-19991078_sfs-1999-1078/).

Do not reduce this to an `EU hosted = compliant` checkbox. Separately establish:

- storage, processing, backup, support-access, and subprocessor countries;
- Bookkeeping Act notification or permission position;
- immediate authority access and Swedish print/export capability;
- processor roles, instructions, security, incident notice, audit, return/deletion,
  retention, portability, and exit terms;
- whether vendor inputs or outputs are used for model training or another purpose;
- any remote access or transfer outside the EU/EEA.

GDPR third-country transfer rules are separate. Use current
[IMY third-country guidance](https://www.imy.se/verksamhet/dataskydd/det-har-galler-enligt-gdpr/overforing-till-tredje-land/)
for adequacy, safeguards, transfer assessments, and supplementary measures.

## GDPR and confidential data

When AI use processes personal data, establish purpose, lawful basis, necessity,
minimization, accuracy, transparency, retention, access, security, controller and
processor roles, and accountability. The organization does not transfer its
responsibility merely by using a vendor.

Use IMY's current
[GDPR and AI guidance](https://www.imy.se/verksamhet/dataskydd/innovationsportalen/vagledning-om-gdpr-och-ai/gdpr-och-ai/ai-och-tillampning-av-gdpr/)
and its detailed
[generative-AI report dated 2025-02-05](https://www.imy.se/contentassets/1571d42dcc8346529658968c198cd4b5/gdpr-vid-anvandning-av-generativ-ai_imy-2024-9162.pdf).
The report is formally aimed at public administration but offers useful controls
for other organizations; do not misstate its scope.

Apply these defaults:

- Deny raw client, employee, payroll, bank, tax, invoice, supplier, customer,
  personal-identity, or confidential files in unapproved personal accounts.
- Procure and configure an approved business environment before production use.
- Minimize, redact, pseudonymize, or use synthetic data where the task permits.
- Mirror existing role-based access instead of giving the agent broader retrieval.
- Confirm processor agreement and vendor purposes before sending personal data.
- Segregate records retained for legal obligations from daily AI retrieval.
- Escalate large-scale, sensitive, monitoring, profiling, new-technology, or
  consequential uses for a privacy review and possible DPIA. See
  [IMY's DPIA guidance](https://www.imy.se/verksamhet/dataskydd/det-har-galler-enligt-gdpr/konsekvensbedomning/).

For decisions with legal or similarly significant effects, use current
[IMY automated-decision guidance](https://www.imy.se/verksamhet/dataskydd/innovationsportalen/vagledning-om-gdpr-och-ai/gdpr-och-ai/automatiserat-beslutsfattande/).
Require meaningful human decision-making, explanation, and applicable safeguards.

## EU AI Act and Swedish governance

As checked on 2026-07-10, the binding 2024 AI Act's AI-literacy and prohibited-use
provisions have applied since 2025-02-02; governance and general-purpose model
provider provisions applied from 2025-08-02. Use
[Regulation (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj?locale=en)
and the [AI Office literacy Q&A](https://digital-strategy.ec.europa.eu/en/faqs/ai-literacy-questions-answers).

The legal position is changing immediately. A Digital Omnibus amending text was
adopted and signed on 2026-07-08, but no Official Journal publication was located
during this 2026-07-10 check. The signed text would change Article 4's wording and
move important high-risk dates after it enters into force. Recheck the Official
Journal and consolidated regulation before stating a current obligation or
deadline. See the [Council register](https://www.consilium.europa.eu/en/documents/public-register/document-details/?DocumentLanguage=EN&ImmcIdentifier=PE-30-2026-INIT)
and [signed PE-CONS 30/26 text](https://data.consilium.europa.eu/doc/document/PE-30-2026-INIT/en/pdf).

Maintain:

- an AI-use inventory with owner, purpose, vendor, data class, affected persons,
  integration, risk tier, review, and last evaluation;
- role- and risk-specific literacy on hallucinations, source verification,
  confidentiality, automation bias, escalation, and prohibited uses;
- records of training, policy acknowledgement, exercises, and refresh;
- specialist classification for employment or worker management, individual
  creditworthiness, and relevant life or health insurance uses.

Ordinary accounting assistance is not automatically high risk merely because a
finance team uses it. Classify the specific use, affected persons, and legal role.

Sweden appointed interim competent authorities through 2026-12-31 in
[Government decision Fi2026/01365](https://www.regeringen.se/contentassets/0377f932c1b74404895c0bbdaa5abb08/uppdrag-att-vara-nationella-behoriga-myndigheter-enligt-ai-forordningen.pdf).
PTS is the single contact point; Finansinspektionen has specified responsibilities
for relevant finance-sector high-risk uses.

## Tax, annual reporting, and signatures

Keep this sequence:

`AI prepares → qualified human verifies → authorized human approves or signs → separate controlled submission`

Skatteverket states that the company remains responsible for complete and correct
information even when a representative submits it. See
[company representative guidance](https://www.skatteverket.se/foretag/drivaforetag/ombudforettforetag/ombudsbehorigheterforettforetag.4.16f588619a39f2c14a1920.html).

The [Tax Procedure Act (2011:1244)](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/skatteforfarandelag-20111244_sfs-2011-1244/)
governs declaration signatures and representatives. The
[Annual Accounts Act (1995:1554)](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/arsredovisningslag-19951554_sfs-1995-1554/)
requires the applicable board members and CEO to sign annual reports.

Never say that the agent signed, approved, filed, or assumed responsibility.
Recheck current tax rates, thresholds, forms, filing methods, and periods against
Skatteverket before using them.

## Professional overlays

For statutory audit work, apply independence, documentation, and confidentiality
requirements from the current
[Auditors Act (2001:883)](https://data.riksdagen.se/dokument/sfs-2001-883.html)
and the engagement's audit standards and firm policy.

For authorized FAR accounting or payroll consultants and relevant staff at member
firms, consult current [FAR Reko](https://www.far.se/kunskap/yrkesutovning-och-etik/reko/).
Reko is authoritative within its scope, not general law for every accountant,
controller, or CFO.

## Swedish workflow context

Record:

- country, legal entity, organization number handling, and reporting framework;
- applicable BFN category such as K2 or K3 when relevant;
- BAS chart year, SIE version, currency, language, and fiscal period;
- VAT registration, domestic/cross-border context, tax point, and source date;
- payroll or personnummer involvement and data classification;
- whether the output is education, internal analysis, bookkeeping support,
  management reporting, audit support, tax research, or an official submission.

Use Swedish and English output when useful. Preserve exact Swedish terms where an
English translation could change meaning. State whether the workbook or report is
analysis support or part of the official accounting record.

## Official source register

- [BFN decided accounting rules](https://www.bfn.se/redovisningsregler/beslutade-redovisningsregler/)
- [Skatteverket bookkeeping and closing](https://www.skatteverket.se/foretag/drivaforetag/bokforingochbokslut.4.58d555751259e4d661680006527.html)
- [Skatteverket VAT rates and exemptions](https://www.skatteverket.se/foretag/moms/saljavarorochtjanster/momssatserochundantagfranmoms.4.58d555751259e4d66168000409.html)
- [Bolagsverket](https://bolagsverket.se/)
- [IMY GDPR and AI](https://www.imy.se/verksamhet/ai/gdpr-och-ai/)
- [Finansinspektionen](https://www.fi.se/)
- [PTS AI Act information](https://www.pts.se/ai/ai-forordningen/)
- [BAS charts of accounts](https://www.bas.se/kontoplaner/)
- [SIE format organization](https://sie.se/)

Open these live and record the access date. Do not bundle controlled BAS or SIE
materials unless their reuse terms permit it.
