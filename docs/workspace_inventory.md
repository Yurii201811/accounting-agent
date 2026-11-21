# Workspace Inventory

Generated: 2026-05-16

## Scope

Goal: identify the correct durable workspace for a Swedish accounting automation system without modifying production code or data.

I inspected:

- the current folder: `<accounting-agent-workspace>`
- the workspace registry: `<workspace-registry>`
- nearby project-like sibling folders under `<documents-root>`
- the existing Openclaw/Hermes repo at `<openclaw-hermes-workspace>`
- the generated Openclaw/Hermes Obsidian mirror

I did not open `.env`, wallet env files, local token files, SQLite row data, or live API configuration values.

## Current Folder Verdict

`<accounting-agent-workspace>` began as an empty durable workspace seed, not an initialized repo and not a working application.

Evidence:

- directory listing contained no tracked project files before this report
- `git status` failed with `fatal: not a git repository`
- there was no local `AGENTS.md`, README, package file, queue, app source, or config

This folder is safe for documentation and scaffold work. It is the best target for a dedicated accounting-agent repo because it avoids mixing client accounting execution with the existing general Openclaw/Hermes operating-system repo.

Post-implementation note: the workspace now contains a minimal Python package, tests, and policy/permit documentation for a local policy gatekeeper and execution permit foundation. It still has no live Fortnox, email, payment, tax filing, or real client-data processing path.

## Inventory

| Repo or folder | Likely purpose | Tech stack | Important files found | Safe to modify? | Related to accounting-agent? |
| --- | --- | --- | --- | --- | --- |
| `<accounting-agent-workspace>` | Dedicated accounting-agent workspace seed | None yet | `docs/workspace_inventory.md`, `docs/accounting_agent_architecture.md` after this pass | Yes for docs and future scaffold. No production code or client data exists here yet. | Yes. Recommended target workspace. |
| `<openclaw-hermes-workspace>` | Openclaw/Hermes OS, a policy-governed local agent operating layer | Python 3.11, pytest, PyYAML, Telethon, SQLite queue, YAML policies/config | `AGENTS.md`, `README.md`, `pyproject.toml`, `orchestrator/`, `config/`, `policies/`, `docs/task_queue.md`, `docs/autonomy_policy.md`, `.local/task_queue.sqlite`, `agents/finance_admin.md`, `trading-agent/` | Read/reference only for this task. It had a dirty worktree and runtime state during the original inventory. | Adjacent but not the target. It has useful governance patterns, but no Fortnox/Capego/SIE/gnubok implementation was found. |
| `<openclaw-hermes-vault>` | Generated Obsidian mirror/dashboard for Openclaw/Hermes | Markdown vault | `08 System Architecture/`, `06 Approvals/`, `01 Daily Reports/`, `13 Policies/` | Treat as read-only/export-only unless explicitly scoped. | Related only as reference documentation. It must not become the executable task queue. |
| `<codex-workspace>` | Codex task scratch, generated reports, temporary artifacts | Mixed scratch artifacts | `WORKSPACES.md` | Usually safe for reports, not for durable source unless promoted. | Not the target. Use only as workspace registry/scratch. |
| `<adjacent-finance-workspace>` | Personal-finance migration and local CSV bridge | Node.js script, CSV migration files | Project README files and an unopened local environment path | Do not modify for this task. It contains unrelated local data and environment material. | Not the target. Financially adjacent but unrelated to Swedish bookkeeping automation. |
| `<unrelated-workspace-1>` | Empty git repo | Git only | `.git/` | No reason to modify. | No evidence of relevance. |
| `<unrelated-workspace-2>` | Empty git repo | Git only | `.git/` | No reason to modify. | No evidence of relevance. |
| `<unrelated-workspace-3>` | Empty git repo | Git only | `.git/` | No reason to modify. | No evidence of relevance. |
| `<unrelated-workspace-4>` | Empty git repo plus `tmp/` | Git only | `.git/`, `tmp/` | No reason to modify. | No evidence of relevance. |
| `<unrelated-artifact-workspace>` | Artifact-only folder | Unknown/artifacts | `.artifacts/` | No reason to modify. | No evidence of relevance. |

## Source Search Findings

### Current accounting workspace

No source files existed before these reports. No README, package file, queue, config, policy, MCP server, database, or agent registry was present.

### Openclaw/Hermes repo

Useful existing patterns:

- one shared SQLite task queue at `.local/task_queue.sqlite`
- policy-governed action modes: `auto_allowed`, `draft_only`, `approval_required`, `escalation_required`, `forbidden`
- shared policy, approval, logging, memory, budget, reporting, and integration layers
- disabled `finance_admin` pod for cost/invoice/tax/admin review work
- explicit rule that Obsidian is not the executable queue

Search results for accounting-system specifics:

- Found generic finance/admin references and accounting-export language.
- Found no Fortnox, Capego, SIE, gnubok, Microsoft 365 accounting intake, or dedicated Swedish bookkeeping automation modules.
- Found no dedicated accounting-agent package or production Fortnox adapter.

Important mismatch:

- Openclaw/Hermes has a future Finance/Admin pod, but its docs explicitly frame it as invoice/cost/tax/admin review and not as production bookkeeping execution.
- The Swedish accounting-agent system needs client-isolated accounting operations, Fortnox-first workflows, approval permits, and auditability. That is more specific and higher risk than the current general Openclaw/Hermes OS scope.

## Recommendation

Use `<accounting-agent-workspace>` as the correct durable target workspace for the Swedish accounting automation build.

Rationale:

- It is named for the product and currently contains no conflicting app architecture.
- It avoids adding regulated/client-sensitive accounting execution into the broad Openclaw/Hermes OS repo.
- It can reuse Openclaw/Hermes governance ideas without inheriting the dirty worktree, unrelated trading-agent package, Telegram/personal-memory runtime, or broad future-pod surface.
- It can be initialized with local-first, client-isolated accounting boundaries from day one.

Do not use `<openclaw-hermes-workspace>` as the production accounting-agent repo. Use it as a reference for policy gates, SQLite queue shape, approval logging, audit trail expectations, and role vocabulary only.

## Missing Information

Before implementation, decide or collect:

- Fortnox environment: sandbox vs production, API app model, OAuth flow, and write restrictions
- Microsoft 365 tenant/account boundary, approved Graph scopes, and whether first intake is exported files or read-only API
- first pilot client boundary, data classification, and retention policy
- gnubok interface expectation: CLI, file format, database, or import/export adapter
- Capego/SIE target: SIE 4 export only, Capego upload prep, or a broader closing package
- OCR engine preference and where raw documents may be stored
- BAS account/VAT rule source and how often it must be updated
- approval owner and approval UI surface for MVP
- whether this workspace should be initialized as a git repo immediately

## Risks

- Client accounting data is high sensitivity. Do not store raw client documents, credentials, tokens, or secrets in tracked files.
- Live Fortnox writes, tax filings, payments, destructive ledger changes, and client communication must require policy gates and human approval.
- The Openclaw/Hermes repo has many uncommitted changes. Copying code from it without care risks inheriting unrelated state.
- Obsidian should stay read-only/export-only. It should not become the task queue or operational source of truth.
- Fortnox, Microsoft Graph, OCR, Capego/SIE, and Swedish accounting rules are moving external surfaces. Verify current vendor docs before implementing live adapters.

## Next-Step Plan

1. Treat `Accounting Agent` as the new durable repo root.
2. Add a repo-local `AGENTS.md` that tightens finance/client-data rules.
3. Add `README.md`, `pyproject.toml`, and a Python package skeleton.
4. Create a local SQLite-backed queue and audit schema as the executable source of truth.
5. Implement document intake from local exported Microsoft 365/OneDrive folders before live API reads.
6. Implement proposal-only accounting logic first: document classification, duplicate checks, BAS/VAT suggestions, and approval packets.
7. Add dry-run Fortnox and gnubok adapters before any live Fortnox write.
8. Add tests for policy gates, idempotency, audit logging, duplicate detection, and no-secret tracked config.
