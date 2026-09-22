# Research evidence and open-source patterns

**Research checked on: 2026-07-10.** Treat maintenance signals, product features,
survey results, and community discussions as time-sensitive.

## Contents

- [Evidence labels](#evidence-labels)
- [Why the skill is a copilot](#why-the-skill-is-a-copilot)
- [Swedish and finance adoption evidence](#swedish-and-finance-adoption-evidence)
- [Practitioner evidence](#practitioner-evidence)
- [Open-source patterns](#open-source-patterns)
- [Cross-platform skill format](#cross-platform-skill-format)
- [Rules for public claims](#rules-for-public-claims)

## Evidence labels

Label every public claim as one of:

- **Binding or authoritative:** law, regulator, tax authority, or applicable standard.
- **Peer reviewed:** published research; still inspect scope and identification.
- **Preprint or benchmark:** useful failure evidence, not a production guarantee.
- **Survey:** sentiment or association shaped by sample and sponsor.
- **Vendor or platform documentation:** capability and limitation claims from its maker.
- **Community anecdote:** experience and vocabulary, never prevalence or proof.
- **Inference:** a design recommendation derived from evidence, not a quoted rule.

## Why the skill is a copilot

[Human + AI in Accounting](https://onlinelibrary.wiley.com/doi/10.1111/1475-679x.70052?af=R),
published in the Journal of Accounting Research on 2026-04-16, combines a survey
of 277 accountants with transaction data from 79 SMEs. The study reports positive
associations with service capacity, more granular ledgers, and faster close, while
its controlled task also shows that following non-consensus AI advice can increase
errors. Do not turn field associations into universal causal savings claims.

[FinBalance](https://arxiv.org/abs/2606.15949), a 2026-06-14 expert-reviewed
synthetic benchmark preprint, found that current models often failed to produce an
exact balanced final statement, sometimes disagreed with journal entries replayed
from their own output, and could cite the wrong source even when an entry was
otherwise correct. Deterministic ledger feedback improved some consistency but did
not remove every reasoning failure.

[Finch](https://arxiv.org/abs/2512.13168), a 2025-12-15 preprint covering 172
messy cross-file finance workflows, reports low pass rates for the specific model
versions it tested. Do not reuse those model-specific percentages as a current SLA.

These sources support the design inference: use an agent to orchestrate, research,
draft, and author transparent tools; use deterministic components for arithmetic,
ledger replay, validation, and permissions; require source checks and human judgment.

## Swedish and finance adoption evidence

- [Statistics Sweden, AI in enterprises 2025](https://www.scb.se/en/finding-statistics/statistics-by-subject-area/research-and-the-digital-society/ovrigt/artificial-intelligence-in-sweden/pong/statistical-news/artificiell-intelligens-i-sverige-2025/?menu=open)
  reported that 35% of Swedish enterprises with at least ten employees used AI.
  Among AI-using firms, 14% reported accounting, controlling, or financial
  management as a purpose. Among firms that considered but did not adopt AI,
  74.7% cited missing expertise. Treat this as 2025 official survey evidence,
  not a forecast.
- A [FAR/Balans 2024 survey](https://www.faronline.se/dokument/balans/2024/december/balans_2024120901/)
  of 331 Swedish audit, accounting, tax, and payroll professionals at small and
  midsize firms found use centered on knowledge search, text, and administration;
  data integrity, security, over-trust, skills, and loss of judgment were recurring
  concerns. Check sample and date before generalizing.
- [Finansinspektionen's 2024 financial-sector survey](https://www.fi.se/en/published/reports/reports/2024/ai-increasingly-common-in-the-financial-sector-but-risk-management-is-lagging-behind/)
  found widespread public generative-AI use and a gap between pilots and formally
  approved policy among supervised firms. This is highly relevant to governance,
  but its population is not ordinary Swedish finance teams.
- [AICPA/CIMA's 2025 finance survey](https://www.aicpa-cima.com/news/article/ai-transformation-opens-door-for-finance-professionals-to-build-future-ready)
  reports high expected impact but low readiness and a preference for on-the-job
  learning. It is a global professional-body survey, not Sweden-specific proof.
- A [2025 Deloitte controllership webcast poll](https://www.deloitte.com/us/en/about/press-room/trust-main-barrier-to-agentic-ai-adoption-in-finance-and-accounting.html)
  highlights trust, integration, and preference for defined decision frameworks.
  Webcast attendees are not a representative probability sample.
- The [Nordic Finance AI Report 2026](https://www.rillion.com/finance-labs/ai-in-finance-nordics/)
  describes high AI use alongside low confidence and manual correction among 250
  Nordic finance leaders. It is vendor-sponsored and directional only.

Use measured local baselines and pilot results for ROI. Never substitute a survey's
expected time saving for achieved end-to-end benefit.

## Practitioner evidence

The following sources are anecdotes and may contain promotion, selection bias,
deleted content, or unverifiable claims. Use them to identify jobs, language, and
failure modes, not to establish facts.

- A [2026-06-24 r/Accounting reconciliation discussion](https://www.reddit.com/r/Accounting/comments/1ue5zr7/i_automated_a_bank_reconciliation_process_now_my/)
  favored using an agent to help create a repeatable Python or VBA implementation
  while retaining the prior Excel process as a validation baseline.
- A [2026-04-20 r/CFO discussion](https://www.reddit.com/r/CFO/comments/1sqxcw7/what_we_use_ai_for_in_finance/)
  mentioned monthly reporting, PDF-to-entry preparation, coding-drift review, and
  reusable report skills, alongside recurring complaints about incorrect values,
  format drift, and repeated errors.
- A [2026-05-01 r/CFO adoption thread](https://www.reddit.com/r/CFO/comments/1t0lnyf/push_to_use_ai_in_finance/)
  emphasized data access, undocumented mappings, controlled exports, and narrow
  workflows over an unrestricted finance chatbot.
- A [2025-10-17 r/CFO thread](https://www.reddit.com/r/CFO/comments/1o91xk7/are_agentic_ai_tools_really_making_finance_teams/)
  offered a skeptical view: research and summarization helped, but core processes
  did not automatically change.
- A [2024-12-30 r/Accounting case study](https://www.reddit.com/r/Accounting/comments/1hpy054/case_study_of_using_chatgpt_and_python_to_make/)
  described agent-assisted Python for repetitive invoice processing. Treat the
  workflow shape as useful; do not repeat savings as verified evidence.

The durable theme is `agent as conductor, deterministic tools as calculators,
approved sources as evidence, and people as decision makers`.

## Open-source patterns

Study patterns and licenses; do not copy code without checking the exact file's
license and compatibility with the destination project.

| Project | Pattern to borrow | Caveat |
| --- | --- | --- |
| [Agent Skills specification](https://agentskills.io/specification) | Portable `SKILL.md`, progressive disclosure, validation | Validate against the current spec |
| [OpenAI Skills](https://github.com/openai/skills) | Skill structure, concise routing, deterministic resources | Licenses can be per skill |
| [Anthropic Skills](https://github.com/anthropics/skills) | Cross-agent skill examples and document workflows | Some document skills are source-available, not open source |
| [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | Code-calculated numbers, LLM-assisted narrative, provenance, role separation | Investment-research focus; do not borrow trading execution |
| [Rever](https://github.com/makerever/rever) | Vendor master, duplicate prevention, match states, approvals, audit history | AGPL-3.0; integration and OCR maturity must be verified |
| [ERPNext](https://github.com/frappe/erpnext) | Workflow states, role permissions, period locks, segregation of duties | Large GPL ERP; not a Swedish compliance pack |
| [Booksky](https://github.com/TheJonaz/Booksky) | Integer öre, balanced entries, immutable posted state, correction vouchers, hash chain | No license found during research; study only, do not copy |
| [byrokrat/accounting](https://github.com/byrokrat/accounting) | Deterministic SIE4 parsing and generation | GPL-3.0 and limited recent maintenance |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Tool approvals, resumable review, structured output, tracing | Framework guardrails do not replace adapter authorization |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Checkpoints, pause/resume, approve/reject, editable proposals | Work before an interrupt may repeat; side effects need idempotency |
| [Open Policy Agent](https://github.com/open-policy-agent/opa) | Policy-as-code outside the prompt and fail-closed decisions | Enforce at the tool boundary |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | Provider-neutral regression and red-team cases | Use synthetic data; passing evals is not compliance |
| [Temporal Python SDK](https://github.com/temporalio/sdk-python) | Durable close workflows, retries, approval queues | Retries do not make non-idempotent external effects exactly once |

For Sweden-specific interoperability, link to current official
[BAS charts](https://www.bas.se/kontoplaner/) and [SIE material](https://sie.se/).
Pin the BAS year and SIE version, preserve raw imports, use integer minor units
where appropriate, test encoding and round trips, and distinguish source data from
agent interpretation.

## Cross-platform skill format

OpenAI states that its skills use the Agent Skills open standard and are supported
in ChatGPT, Codex, and the API. See
[Skills in ChatGPT](https://help.openai.com/en/articles/20001066).

Anthropic documents the same required `SKILL.md` name and description fields plus
on-demand resources for Claude products. See the
[Claude Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
and [authoring guidance](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).

Keep the core skill provider-neutral. Platform-specific UI metadata can remain in
an optional `agents/` folder. Test installation and tool availability separately
on each target platform; format portability does not imply identical connectors,
permissions, data handling, or spreadsheet behavior.

## Rules for public claims

- Put the date, population, sample, geography, method, and sponsor near a statistic.
- Distinguish association from causation and expected savings from observed savings.
- Label preprints and model-specific benchmarks; do not market them as current SLAs.
- Label vendor material and community anecdotes.
- Cite the direct source, not a search page or unattributed summary.
- Avoid timeless legal claims; show a law-checked date and current-rule link.
- Publish failures and limits alongside successful workflows.
- Prefer the organization's measured baseline, quality, review time, exceptions,
  and control outcomes over industry averages.
