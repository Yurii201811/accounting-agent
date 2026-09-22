# Synthetic accounting and review UI checkpoint

Continuation: `docs/payment_evidence_checkpoint.md` records the subsequent
currency, amount-difference, and case-evidence improvements and 330-test result.

Verified on 2026-09-22 in the canonical Accounting Agent checkout, on `main`
at base commit `aed4507`. Changes are local and uncommitted. Existing model,
cockpit, finance-workflow, and matching-reliability work was preserved.

## Changes

- Review rows now identify the supplier or counterparty, business reference,
  and precise currency amount. Invalid or missing amounts are omitted rather
  than presented as zero. All content remains escaped.
- Work-type filters use unique case counts and combine with text search and
  priority. Clear/reset controls restore the complete list and keyboard focus.
- Native expandable case details show the checks needed before reassessment.
  Guided mode includes evidence links and every tied matching candidate, with
  none selected automatically. Opening details does not approve a case or
  change its status.
- Supplier identity conflicts, missing payment details, and ambiguous bank
  matches have specific English and Swedish explanations. Senior review stays
  explicit when several risk categories apply to the same case.
- Invoice extraction rejects non-finite and unrepresentable monetary values;
  invalid VAT rates become missing evidence. Invalid amounts stop journal
  preparation until corrected.
- Added 14 tests across numeric input quality, synthetic accounting acceptance,
  and pipeline-to-cockpit review integration. The acceptance cases distinguish
  separate, similar-looking payments from repeated source identifiers and
  check the transition from invalid journal data to a permitted local draft.

## Verification

- `python3 -m unittest`: **318 tests passed** (previous checkpoint: 304).
- A fresh full synthetic month completed with **15 invoices/receipts and 20
  bank transactions**, plus a five-item customer-invoice catalogue. There were
  **zero unsafe misses and zero policy alignment warnings** in these scenarios.
  The resulting cockpit contains 14 unique review cases: seven supplier and
  seven bank cases.
- `python3 -m accounting_agent.cli v1-system-check --json`: **all 11 checks
  passed**, with zero external calls, ERP writes, and hosted-model calls.
- Public preview and full synthetic-month cockpit builds: **zero broken links**.
  A supplier evidence link was also requested through the in-app browser and
  served successfully with HTTP 200.
- In-app browser: desktop (1440 × 1000 and normal viewport) and mobile
  (390 × 844), English and Swedish, Guided/Expert switching, work-type filtering,
  combined search/priority empty results and recovery, keyboard detail expansion,
  all tied candidates, and explicit senior review were checked. No horizontal
  overflow or relevant console warnings/errors were observed. Visible mobile
  review buttons, inputs, selects, and disclosures were at least 44 px tall.
- `git diff --check`: **passed**.
- Bounded review of the case-context integration found no outstanding material
  findings; regression tests cover six-way matching ties, multi-risk senior
  review, missing amounts, HTML escaping, and evidence availability in Guided mode.

Run artifacts and the full test log are outside the repository under
a local temporary validation workspace.
The local server at `http://127.0.0.1:8766/reports/operations_cockpit/index.html`
serves this generated synthetic workspace. It is a temporary preview, not a
deployment. Screenshots are saved under
a local visualization directory outside the repository
as `accounting-review-desktop.png` and `accounting-review-mobile.png`.

## Open-source inspiration

Primary project material was inspected on 2026-09-22. The tests use invented
local data; no upstream financial records, fixtures, or datasets were copied.

- [hledger import and deduplication](https://hledger.org/1.52/hledger.html#deduplication)
  and [reconciliation guidance](https://hledger.org/reconciling.html) informed
  the distinction between source identity and legitimately similar payments,
  together with inspectable reconciliation evidence. This implementation rejects
  duplicate IDs within an incoming batch; it does **not** implement hledger's
  persistent import deduplication or cross-run invoice allocation.
- [LedgerSMB database schema](https://github.com/ledgersmb/LedgerSMB/blob/master/sql/Pg-database.sql)
  informed the emphasis on unapproved journal state, explicit approval authority,
  references, and rejecting non-finite amounts. No adapter permissions changed.
- [Beancount validation and reports](https://beancount.github.io/docs/running_beancount_and_generating_reports/)
  informed showing the affected entry and actionable correction context. The
  referenced page includes older command-line tooling; no commands were adopted.

## Limits and next action

These are deterministic synthetic checks, not proof of perfect accounting or
production readiness. Real OCR, real supplier identity, live services, and
real-client accuracy were not tested. The browser checks cover the in-app browser;
they are not a complete screen-reader or cross-browser accessibility audit.
Matching ambiguity currently detects exact ties at the existing rounded score;
near-tie policy and persistent allocation across runs remain separate work.

The next useful acceptance expansion is a generated matrix of near-tied matches,
partial payments, credit notes, and currency precision boundaries, with accountant-
reviewed expected outcomes before changing accounting policy or match scoring.
