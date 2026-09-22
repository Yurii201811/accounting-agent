# Payment evidence checkpoint

Verified on 2026-09-22 in the canonical checkout, on `main` at base commit
`aed4507`. This continues `docs/review_workflow_checkpoint.md`. Changes remain
local and uncommitted; earlier matching, model, finance-workflow, and UI work
was preserved.

## Changes

- Bank transactions and open items require a supplied, supported currency.
  Codes are trimmed and uppercased for both fixture input and direct typed
  construction. Missing currency no longer silently becomes SEK.
- Amount, currency, and payment-direction conflicts require canonical review,
  including a one-minor-unit overpayment whose score remains high. Such cases
  now produce a review packet. A date-distance signal alone keeps the existing
  confidence policy, and exact signed matches can still become local drafts.
- Reconciliation payloads omit residual amounts for incompatible currencies,
  opposite directions, or zero-direction comparisons. Supported currencies
  without configured policy thresholds serialize the escalation decision
  without crashing; they do not acquire implicit SEK thresholds.
- Case details now contain invoice net/VAT/total and dates, or the proposed
  payment match, bank amount, open amount, and conditional remainder/overpayment.
  Missing values are explicit. Incomparable amounts show no numeric remainder.
- Payment differences have specific English/Swedish guidance. Secondary checks
  remain visible while repeated primary instructions are reduced. Facts are
  searchable in both languages, escaped, and read-only.

## Verification

- `python3 -m unittest`: **330 tests passed** (previous checkpoint: 318).
  Twelve new tests cover explicit currency, signed exact/overpayments,
  incomparable amounts, unchanged date-distance behavior, and pipeline-backed
  cockpit amount evidence, localization, and escaping.
- Fresh full synthetic month: **15 invoices/receipts, 20 bank transactions, and
  five customer-invoice catalogue items**. Final run: **zero unsafe misses,
  false positives, unclear outputs, and policy alignment warnings**. Fourteen
  unique cases still require review.
- The month run caught an overbroad candidate-flag rule that unnecessarily
  escalated an exact late payment. The rule was narrowed to financial comparison
  conflicts and a regression test now preserves the expected late-payment result.
- All **11 v1 system checks passed**, with zero external calls, hosted-model
  calls, and ERP writes. Synthetic-run live counters all remain zero.
- The rebuilt cockpit has **zero broken links**. In-app browser verification
  covered English desktop (1440 × 1000 / 1200 and normal viewport), Swedish
  mobile (390 × 844), partial-payment details, invoice facts, keyboard disclosure
  open/close, localized amounts, and clear-filter focus recovery. No horizontal
  overflow or relevant console warnings/errors were observed. Visible mobile
  review controls met the existing 44 px minimum height.
- `git diff --check` and `compileall`: **passed**.

Evidence is outside the repository at
a local temporary validation workspace:
`payment-evidence-unittest.log`, `payment-evidence-validation.json`, and the
fresh generated synthetic month/cockpit. The local preview remains at
`http://127.0.0.1:8766/reports/operations_cockpit/index.html#review`.

Screenshots are saved under
a local visualization directory outside the repository
as `accounting-partial-payment-desktop.png` and
`accounting-partial-payment-mobile.png`.

## Limits and next action

No real client data or live accounting systems were used. Synthetic test success
does not establish real-client accuracy or production readiness. The cockpit
does not approve a match or apply a balance. Cross-currency matching has no
exchange-rate evidence adapter; it remains subject to review/escalation.
Near-tie thresholds, persistent reconciliation allocation across runs, and
real OCR accuracy remain separate work. Browser coverage is the in-app browser,
not a complete cross-browser or screen-reader audit.

The next useful step is a bounded synthetic input-contract pass for amount
types and precision before intake, plus explicit scenario expectations for
credit notes and near-tied candidates before changing scoring policy.
