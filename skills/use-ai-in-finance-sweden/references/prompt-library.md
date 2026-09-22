# Prompt library

These are task briefs, not permission grants. Replace placeholders, use approved
sources, and keep the action boundary from `SKILL.md`.

## Contents

- [Workbook map](#workbook-map)
- [Formula diagnosis](#formula-diagnosis)
- [Controlled workbook change](#controlled-workbook-change)
- [Bank reconciliation](#bank-reconciliation)
- [Supplier invoice review](#supplier-invoice-review)
- [Month-end close pack](#month-end-close-pack)
- [Variance analysis](#variance-analysis)
- [Cash forecast](#cash-forecast)
- [Management or board narrative](#management-or-board-narrative)
- [Swedish technical research](#swedish-technical-research)
- [CFO workflow portfolio](#cfo-workflow-portfolio)
- [Swedish-language instruction](#swedish-language-instruction)

## Workbook map

> Use the approved workbook `[file]`. Entity `[entity]`, period `[period]`,
> currency `[currency]`. Do not edit. Map raw data, assumptions, formulas,
> external links, queries, mappings, checks, dashboards, and source ownership.
> Trace `[metric/cell]` to the narrowest source ranges. Report supported facts,
> inferred items, broken controls, and unresolved questions. Output state:
> `analysis-only`.

## Formula diagnosis

> Diagnose `[error/cell/range]` in `[workbook]`. Preserve the original. Trace
> precedents and dependents, compare adjacent formula patterns, units, signs, and
> periods, and identify the smallest safe fix. Do not edit until the root cause is
> evidenced. If editing is authorized, work on a copy, fix only the affected
> range, recalculate, scan related formulas, and report exact before/after values
> and formulas. Output state: `draft-for-review`.

## Controlled workbook change

> In a versioned copy of `[workbook]`, add `[requested output]` for `[period]`.
> Preserve all existing formulas, macros, named ranges, links, queries, formats,
> and sheet structure outside `[allowed tabs/ranges]`. Keep inputs visible, use
> formulas for derived values, add sources and checks, inspect every changed
> range, and list the diff. Do not save over the source or share externally.

## Bank reconciliation

> Reconcile approved exports `[bank source]` and `[ledger source]` for `[entity]`,
> `[account]`, and `[period]`. Preserve raw tabs. Document normalization and
> deterministic match rules, including one-to-many treatment. Prove matched plus
> unmatched totals equal each source. Create an exception queue with evidence and
> owner. Do not clear transactions, post entries, change bank data, or initiate a
> payment. Output state: `draft-for-review`.

## Supplier invoice review

> Review approved supplier-invoice data for `[entity/period]`. Extract fields and
> propose BAS account, dimension, and VAT treatment only when supported. Compare
> supplier history and detect possible duplicates. Block unknown suppliers,
> changed bank details, missing evidence, uncertain VAT, locked periods, and low
> confidence. Produce proposals and review reasons; do not create/update a
> supplier, approve/send an invoice, post, pay, or communicate externally.

## Month-end close pack

> Prepare a close review pack for `[entity]`, `[period]`, framework `[K2/K3/other]`,
> and materiality `[threshold]`. Use only `[approved reports]`. Build a checklist,
> tie-outs, source map, mapping/version changes, exceptions, preparer/reviewer
> fields, and a status summary with failed checks first. Do not unlock a period,
> post, approve, file, or sign. Separate evidence from proposed adjustments.

## Variance analysis

> Analyze actual versus `[budget/forecast/prior year]` for `[entity/period]`.
> Reconcile source totals first. Calculate amount and percent variances using
> visible formulas. Explain price, volume, mix, rate, timing, or one-off effects
> only when the data supports them. Link each material statement to exact source
> ranges, separate fact from inference, and draft owner questions for unresolved
> drivers. Do not release the commentary.

## Cash forecast

> Build a 13-week cash forecast for `[entity]` from approved opening cash,
> receivables, payables, payroll, tax, debt, and operating assumptions. Keep raw
> inputs separate, centralize assumptions, use formula-based base/upside/downside
> scenarios, reconcile opening and closing balances, and flag missing timing or
> double counting. This is analysis only: do not connect to a bank, schedule a
> payment, or represent the forecast as treasury approval.

## Management or board narrative

> Draft a management review for `[period]` using only `[approved pack]`. Show the
> headline KPIs, trend, variance, two to four drivers, downside, open questions,
> and decisions requested. Cite every material number to its exact source. Label
> facts, assumptions, inference, and recommendations separately. Do not publish,
> send, or state that management approved the draft.

## Swedish technical research

> Research `[question]` for Swedish entity `[entity type]`, period `[period]`, and
> context `[bookkeeping/VAT/tax/reporting/privacy/AI]`. Search current binding law
> and the relevant Swedish authority first. Record source title, section, URL,
> update/effective date, access date, and scope. Distinguish law, authority
> guidance, professional standard, interpretation, and inference. Do not give a
> final filing or tax decision; state what a qualified reviewer must decide.

## CFO workflow portfolio

> Inventory `[finance function]` workflows using process metadata only. For each,
> record owner, frequency, touch and wait time, rework, sources, data class,
> standardization, judgment, consequence, reversibility, current controls,
> smallest agent task, and retained human decision. Rank low-risk pilot candidates,
> decompose consequential work, propose baseline and acceptance metrics, and
> produce a 30-60-90 rollout. Do not claim savings without measured baselines.

## Swedish-language instruction

Append when Swedish output is useful:

> Svara på tydlig svenska och behåll exakta svenska redovisnings- och myndighets-
> begrepp. Ange även den engelska termen när det minskar risken för missförstånd.
> Använd SEK, tydliga perioder och källdatum. Skilj fakta, antaganden, slutsatser,
> avvikelser och beslut som måste fattas av en behörig person.
