# Role playbooks

## Contents

- [Shared method](#shared-method)
- [Accountant and bookkeeper](#accountant-and-bookkeeper)
- [Accounts payable and receivable](#accounts-payable-and-receivable)
- [Financial controller and close team](#financial-controller-and-close-team)
- [Business controller and FP&A](#business-controller-and-fpa)
- [CFO and finance leader](#cfo-and-finance-leader)
- [Audit, tax, and payroll](#audit-tax-and-payroll)
- [Finance operations and systems owner](#finance-operations-and-systems-owner)
- [Output contract](#output-contract)

## Shared method

For every role:

1. Establish entity, jurisdiction, period, currency, materiality, policy, owner,
   reviewer, approved sources, and allowed actions.
2. Preserve the raw source and separate it from transformations and narrative.
3. Use formulas, scripts, or ledger functions for arithmetic and validation.
4. Use the agent for orchestration, research, code assistance, exception ranking,
   explanation, and first drafts.
5. Route uncertainty to an exception queue. Never force a complete-looking result.
6. Reconcile to the source of truth, retain evidence, and label the output state.

## Accountant and bookkeeper

Suitable work:

- Extract structured fields from approved invoices and receipts.
- Compare current coding with an approved supplier history.
- Propose BAS accounts, cost centers, projects, and VAT treatment with sources.
- Prepare accrual, prepaid, fixed-asset, and intercompany support schedules.
- Create bank-reconciliation candidates and list unmatched items.
- Draft accounting memos and missing-information questions.
- Build evidence packets for review or audit requests.

Required controls:

- Tie each proposed entry to a source-document identifier and period.
- Replay proposed entries through deterministic debit/credit and balance checks.
- Keep proposed, reviewed, posted, corrected, and rejected states separate.
- Block unknown suppliers, duplicates, bank-detail changes, unclear business
  purpose, uncertain VAT, missing documents, and closed periods.
- Never let the agent post or approve the entry it prepared.

## Accounts payable and receivable

Suitable work:

- Detect likely duplicates using invoice number, supplier, amount, date, and hash.
- Compare purchase order, receipt, and invoice data and explain mismatches.
- Draft exception questions and payment-run review summaries.
- Identify overdue items and draft collection or supplier queries.
- Reconcile subledger exports to control accounts.

Required controls:

- Treat changed bank details as a security escalation requiring out-of-band
  verification and segregation of duties.
- Keep payment initiation, supplier-master changes, invoice approval, invoice
  sending, and external communication human-controlled.
- Do not infer a missing purchase order, receipt, tax code, or payment status.
- Separate communication drafts from sent messages.

## Financial controller and close team

Suitable work:

- Normalize ERP exports and compare entity, account, dimension, and period totals.
- Prepare close checklists, tie-outs, reconciliation packs, and exception queues.
- Trace mapping changes, sign reversals, formula breaks, and unexplained movements.
- Build actual-versus-budget and actual-versus-prior-year bridges.
- Draft variance commentary linked to exact source rows and owner responses.
- Prepare audit support with source, preparer, reviewer, and change history.

Required controls:

- State the cutoff, consolidation scope, FX source, mapping version, and locked
  period status.
- Reconcile every bridge to the reported variance and every subledger to its
  control account.
- Put failed checks first. Do not hide them behind a management summary.
- Measure first-pass accuracy, correction time, unresolved exceptions, and close
  cycle time in addition to gross time saved.

## Business controller and FP&A

Suitable work:

- Build or refresh driver-based forecasts and base/upside/downside scenarios.
- Prepare 13-week cash forecasts without initiating payments or bank actions.
- Analyze price, volume, mix, rate, timing, headcount, margin, working capital,
  vendor spend, and unit economics.
- Create management-review packs and draft decision-oriented commentary.
- Turn repeated manual mappings or transformations into tested Power Query,
  Python, SQL, or spreadsheet logic.

Required controls:

- Separate actuals, assumptions, calculation logic, scenarios, and narrative.
- State units, periodicity, fiscal calendar, sign convention, scenario, owner,
  version, and refresh timestamp.
- Keep assumptions in visible cells or tables with source and as-of date.
- Reconcile scenario outputs to common starting balances and explain deltas.
- Label estimates as estimates and never present model narrative as a forecast fact.

## CFO and finance leader

Suitable work:

- Assemble source-backed board, lender, and monthly-business-review drafts.
- Compare strategy options, liquidity scenarios, capital allocation, and cost or
  working-capital opportunities.
- Define KPIs, owners, source systems, calculation rules, and decision thresholds.
- Map finance processes, prioritize AI candidates, and review pilot economics.
- Govern AI usage, vendor spend, access, policy, literacy, and control ownership.

Required controls:

- Separate facts, assumptions, inference, recommendation, and decision.
- Show downside and sensitivity, not only the preferred case.
- Include the cost of review, corrections, tool usage, integration, security,
  training, and change management in ROI claims.
- Keep board release, financing decisions, public disclosure, payment, filing,
  and policy approval with authorized people.

## Audit, tax, and payroll

Suitable work:

- Summarize approved standards and source material with paragraph-level citations.
- Prepare planning, risk-assessment, research, sampling, and evidence-index drafts.
- Flag missing, contradictory, or unusual evidence for a qualified reviewer.
- Draft payroll-control and tax-research checklists using current official sources.

Required controls:

- Do not issue an audit opinion, tax position, filing, payroll approval, or client
  advice as an agent decision.
- Preserve independence, confidentiality, scope, and engagement-specific rules.
- Distinguish binding law, official guidance, professional standards, internal
  policy, interpretation, and community commentary.
- Recheck every date-sensitive tax rate, threshold, form, and filing requirement.

## Finance operations and systems owner

Suitable work:

- Document current processes, data contracts, mappings, exception codes, and owners.
- Convert recurring work into versioned formulas, code, skills, and regression tests.
- Design read-only integrations, approval queues, audit events, idempotency, and
  least-privilege access.
- Maintain synthetic evaluation cases and monitor failure modes.

Required controls:

- Put authorization at the adapter or tool boundary, not only in a prompt.
- Keep read, draft, review, approval, and execution as distinct capabilities.
- Make unknown tools, missing evidence, stale policy versions, and schema errors
  fail closed.
- Test prompt injection, cross-client isolation, wrong periods, wrong units,
  duplicates, changed bank details, uncertain VAT, and approval bypass attempts.

## Output contract

Return a compact review packet containing:

1. Question and scope
2. Entity, jurisdiction, currency, period, policy, and materiality
3. Source map and as-of dates
4. Deterministic calculations and reconciliation results
5. Agent-generated analysis or draft
6. Assumptions and inferred items
7. Exceptions, contradictions, and missing evidence
8. Changes made and before/after evidence
9. Output state and forbidden actions
10. Named owner, reviewer, and next human decision
