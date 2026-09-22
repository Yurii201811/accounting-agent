# Company adoption playbook

## Contents

- [Position the programme](#position-the-programme)
- [Build the workflow inventory](#build-the-workflow-inventory)
- [Score and select pilots](#score-and-select-pilots)
- [Run a controlled pilot](#run-a-controlled-pilot)
- [Create the operating model](#create-the-operating-model)
- [Train people through real work](#train-people-through-real-work)
- [Measure value honestly](#measure-value-honestly)
- [Scale through gates](#scale-through-gates)
- [Suggested 30-60-90 sequence](#suggested-30-60-90-sequence)

## Position the programme

Frame the goal as better finance work: faster cycle time, stronger traceability,
fewer manual errors, clearer exceptions, more analysis time, and better decisions.
Do not make tool usage itself a target.

Use a maturity ladder:

1. **Shadow use:** unmanaged personal tools, unclear data handling, no baseline.
2. **Approved assistance:** approved accounts, safe-use rules, human review, and
   low-risk research, drafting, or code assistance.
3. **Repeatable workflows:** shared skills, task briefs, deterministic checks,
   synthetic evaluations, owners, and measured pilots.
4. **Controlled agents:** read-only integrations, least privilege, approval queues,
   audit events, incident handling, and adapter-level policy.
5. **Scaled operating layer:** portfolio governance, reusable data contracts,
   ongoing evaluation, cost controls, and periodic legal or policy refresh.

## Build the workflow inventory

Capture recurring work, not vague ideas. For each workflow record:

- owner, reviewer, users, and decision recipient;
- entity, jurisdiction, period, systems, files, and manual mappings;
- frequency, touch time, wait time, rework, errors, and close dependencies;
- data categories, confidentiality, retention, and vendor restrictions;
- judgment intensity, consequence of error, reversibility, and measurability;
- current controls, evidence, approvals, and known exceptions;
- the smallest useful agent task and the human decision that remains.

Use [../assets/pilot-register.csv](../assets/pilot-register.csv) as a starting
point. Document undocumented mappings before introducing an agent.

## Score and select pilots

Favor workflows that are frequent, standardized, reversible, source-grounded,
measurable, and deterministically verifiable. Good first pilots include:

- source-backed research and memo drafts;
- workbook mapping, formula tracing, and controlled repair on copies;
- data cleanup and transformations on approved exports;
- reconciliation candidates and exception queues;
- budget-versus-actual bridges and first-draft commentary;
- SOPs, checklists, evidence indexes, and tested scripts.

Decompose or defer workflows involving final posting, supplier-master changes,
payments, bank details, tax filing, payroll approval, client communication,
public disclosure, employment decisions, credit decisions, sensitive monitoring,
or poorly controlled source data.

For a reproducible first pass, run:

```bash
python3 scripts/score_workflow.py assets/workflow-assessment.example.json --format markdown
```

Pass only process metadata. Do not put transactions, documents, names, account
numbers, credentials, or other client data in the scoring file.

## Run a controlled pilot

1. Define the exact task, boundary, old process, baseline, owner, reviewer, and
   acceptance criteria.
2. Approve the account, vendor, data location, access, retention, and source set.
3. Create a representative synthetic or properly approved evaluation set,
   including failures and edge cases.
4. Standardize inputs and output schema before adding an agent.
5. Put calculations, validation, permissions, and irreversible effects in
   deterministic components outside the prompt.
6. Run old and new processes in parallel for representative cycles.
7. Compare accuracy, source linkage, exceptions, review effort, rework, cycle
   time, and control outcomes.
8. Record incidents, near misses, overrides, and user feedback.
9. Hold a documented go, revise, or stop review.

Do not let the team learn only from successful examples. Include duplicate
invoices, changed bank details, uncertain VAT, wrong periods, negative values,
missing mappings, contradictory evidence, prompt injection, cross-client access,
and requests to bypass review.

## Create the operating model

Assign named ownership for:

- executive sponsor and finance process owner;
- accounting policy and technical review;
- data protection, information security, legal, procurement, and vendor risk;
- system owner, access, integration, logs, retention, backup, and exit;
- skill or prompt owner, versioning, evaluation set, and release approval;
- workflow preparer, reviewer, approver, and executor;
- incident intake, pause authority, remediation, and communication.

Maintain an AI-use inventory with purpose, owner, users, vendor/model, data
classification, affected people, integration, risk tier, review design, and last
evaluation date. Keep permission enforcement in tools and adapters, not only in
training or prompt text.

## Train people through real work

Use role-specific, on-the-job exercises with synthetic data:

- accountants: evidence-linked coding proposals and exception review;
- controllers: workbook mapping, close tie-outs, and variance bridges;
- FP&A: assumptions, scenarios, sources, and management narrative;
- CFOs: decision memos, portfolio prioritization, and governance tradeoffs;
- system owners: data contracts, least privilege, evals, and incident response;
- reviewers: hallucination, source mismatch, automation bias, and stop rules.

Teach when ordinary formulas, Power Query, SQL, scripts, or workflow automation
are better than an agent. Record attendance, role, material, date, exercise, and
periodic refresh without claiming that attendance alone proves competence.

## Measure value honestly

Baseline the end-to-end process, not only keyboard time. Track:

- manual touch time, wait time, and total cycle time;
- review time, correction time, rework, and exception-resolution time;
- first-pass yield and material-error rate;
- source-link and citation accuracy;
- reconciliation breaks and control failures;
- false positives, false negatives, overrides, and incidents;
- adoption by intended users and abandonment reasons;
- agent usage, integration, training, support, and governance cost.

Calculate gross capacity separately from realized capacity:

`gross hours = frequency × old touch time`

`net hours = gross hours − new touch time − review − correction − support`

Do not convert net hours into cash savings unless capacity was actually removed,
redeployed, or used for measured additional output. Treat vendor surveys and
respondent expectations as directional context, not achieved ROI.

## Scale through gates

Require all applicable gates:

- approved data handling and vendor terms;
- current legal and policy review;
- representative evaluation cases and acceptance thresholds;
- deterministic calculations and control totals;
- source lineage and durable evidence;
- clear exception ownership and stop behavior;
- human review calibrated to consequence and uncertainty;
- least privilege, segregation of duties, audit logs, and rollback;
- stable quality across periods, entities, users, and edge cases;
- net benefit after review, correction, and operating costs;
- trained users and a working incident path.

Revoke or narrow the workflow after material policy change, source change,
unexplained quality drift, access failure, repeated override, or control breach.

## Suggested 30-60-90 sequence

### Days 1–30: discover and govern

- Inventory workflows and shadow-AI use.
- Approve tools, data classes, and safe-use rules.
- Establish AI literacy, ownership, and incident reporting.
- Select two or three low-risk pilots and capture baselines.

### Days 31–60: build and parallel-run

- Standardize data contracts and output schemas.
- Build skills, deterministic checks, synthetic tests, and review packets.
- Run old and new processes in parallel.
- Review failures weekly and revise the boundary before the prompt.

### Days 61–90: decide and institutionalize

- Compare measured quality, control, adoption, and net-efficiency results.
- Scale, revise, or stop each pilot through a documented gate.
- Publish approved playbooks and assign maintenance ownership.
- Plan read-only integrations only where the evidence justifies them.
