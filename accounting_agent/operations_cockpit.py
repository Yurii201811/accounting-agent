from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

from accounting_agent.erp import (
    COMPUTER_USE_BOUNDARY,
    CapabilityMode,
    ErpProvider,
    list_erp_profiles,
)


DEFAULT_OUTPUT_PATH = Path("reports/operations_cockpit/index.html")
DEFAULT_FAKE_CLIENT_OUTPUT = Path(".local/fake_client_dry_run")
DEFAULT_DEMO_OUTPUT = Path(".local/demo_supplier_invoice_autopilot")
DEFAULT_DB_PATH = Path(".local/accounting_agent.sqlite")
DEFAULT_TOKENS_PATH = Path("tokens.css")
DEFAULT_ICON_PATH = Path("favicon.svg")

WORKFLOW_STEPS = (
    ("intake", "Intake"),
    ("document_registry", "Document registry"),
    ("extraction", "Extraction"),
    ("accounting_proposal", "Accounting proposal"),
    ("policy_gate", "Policy gate"),
    ("approval_packet", "Approval packet"),
    ("execution_permit", "Execution permit"),
    ("fortnox_dry_run", "Fortnox dry-run"),
    ("gnubok_shadow_validation", "gnubok shadow validation"),
    ("bank_reconciliation", "Bank reconciliation"),
    ("audit_report", "Audit/report"),
)

ALLOWED_BOUNDARIES = (
    "Read repo-local synthetic fixtures and generated metadata.",
    "Build approval packets, summaries, reports, and this static cockpit.",
    "Prepare Fortnox-shaped payloads in dry-run mode only.",
    "Mirror proposals into the local gnubok shadow validation stub.",
    "Generate bank reconciliation proposals and review packets locally.",
)

BLOCKED_BOUNDARIES = (
    "Live Fortnox calls, final posting, supplier invoice approval, payments, deletes, or settings changes.",
    "Live Microsoft Graph, email sending, client communication, payment initiation, or tax filing.",
    "Real client documents, secrets, credentials, tokens, bank secrets, or broad tenant data.",
    "Using gnubok, Obsidian, reports, or this cockpit as an execution authority.",
)

SAFE_NEXT_ACTIONS = (
    "python3 -m accounting_agent.cli fake-client-dry-run",
    "python3 -m accounting_agent.cli demo-supplier-invoice-autopilot",
    "python3 -m accounting_agent.cli process-fixtures",
    "python3 -m accounting_agent.cli reconcile-bank-fixtures",
    "python3 -m accounting_agent.cli build-operations-cockpit",
    "python3 -m unittest",
)

NOT_ALLOWED_ACTIONS = (
    "Create live Fortnox supplier invoices, vouchers, payments, or final postings.",
    "Approve supplier invoices or send customer invoices.",
    "Send emails or contact clients from MVP code.",
    "Call Microsoft Graph, Fortnox, payment, tax, or filing APIs.",
    "Process real client documents or write secrets into the repo.",
)

_BOUNDARY_SV = {
    "Read repo-local synthetic fixtures and generated metadata.": "Läs lokala syntetiska testdata och genererad metadata.",
    "Build approval packets, summaries, reports, and this static cockpit.": "Bygg granskningspaket, sammanfattningar, rapporter och denna statiska cockpit.",
    "Prepare Fortnox-shaped payloads in dry-run mode only.": "Förbered Fortnox-formade nyttolaster endast i torrkörningsläge.",
    "Mirror proposals into the local gnubok shadow validation stub.": "Spegla förslag till den lokala gnubok-stubben för skuggvalidering.",
    "Generate bank reconciliation proposals and review packets locally.": "Generera förslag till bankavstämning och granskningspaket lokalt.",
    "Live Fortnox calls, final posting, supplier invoice approval, payments, deletes, or settings changes.": "Fortnox-anrop i live-system, slutlig bokföring, attest av leverantörsfakturor, betalningar, radering eller inställningsändringar.",
    "Live Microsoft Graph, email sending, client communication, payment initiation, or tax filing.": "Microsoft Graph-anrop i live-system, e-postutskick, klientkommunikation, betalningsinitiering eller skatteinlämning.",
    "Real client documents, secrets, credentials, tokens, bank secrets, or broad tenant data.": "Verkliga klientdokument, hemligheter, inloggningsuppgifter, token, bankhemligheter eller bred tenantdata.",
    "Using gnubok, Obsidian, reports, or this cockpit as an execution authority.": "Användning av gnubok, Obsidian, rapporter eller denna cockpit som exekveringsbehörighet.",
    "Create live Fortnox supplier invoices, vouchers, payments, or final postings.": "Skapa leverantörsfakturor, verifikationer, betalningar eller slutlig bokföring i Fortnox live.",
    "Approve supplier invoices or send customer invoices.": "Attestera leverantörsfakturor eller skicka kundfakturor.",
    "Send emails or contact clients from MVP code.": "Skicka e-post eller kontakta klienter från MVP-kod.",
    "Call Microsoft Graph, Fortnox, payment, tax, or filing APIs.": "Anropa Microsoft Graph-, Fortnox-, betalnings-, skatte- eller inlämnings-API:er.",
    "Process real client documents or write secrets into the repo.": "Behandla verkliga klientdokument eller skriva hemligheter i källkodsförrådet.",
}

SPECIALIST_STAGES = (
    (
        "Scope",
        "Coordinator",
        "Locks client, jurisdiction, ERP, evidence set, capability ceiling, time budget, and stop conditions.",
    ),
    (
        "Inspect in parallel",
        "Intake · Extraction · Supplier risk · VAT and jurisdiction",
        "Specialists share the same read-only evidence envelope and cannot widen permissions.",
    ),
    (
        "Propose",
        "Accounting proposal · Reconciliation",
        "Produces draft classifications, matches, and explanations without posting anything.",
    ),
    (
        "Verify",
        "Evidence verifier",
        "Checks provenance, contradictions, policy alignment, completeness, and reproducibility.",
    ),
    (
        "Decide",
        "Human reviewer",
        "Approves, rejects, requests evidence, or stops the case. Agents never self-approve.",
    ),
)


@dataclass(frozen=True)
class ArtifactLink:
    label: str
    path: str
    kind: str
    exists: bool
    note: str = ""


@dataclass(frozen=True)
class WorkflowStep:
    key: str
    label: str
    status: str
    detail: str
    artifact_path: str | None = None


@dataclass(frozen=True)
class ReviewItem:
    item_id: str
    source: str
    mode: str
    reason: str
    artifact_path: str | None = None


@dataclass(frozen=True)
class ReviewQueue:
    key: str
    label: str
    count: int
    items: tuple[ReviewItem, ...] = ()


@dataclass(frozen=True)
class PrioritizedReviewItem:
    item_id: str
    source: str
    mode: str
    severity: str
    title: str
    reasons: tuple[str, ...]
    categories: tuple[str, ...]
    artifact_path: str | None = None


@dataclass(frozen=True)
class OperationsCockpitData:
    generated_at: str
    repo_root: str
    output_path: str
    last_run: str
    local_readiness: str
    demo_readiness: str
    live_counters: dict[str, int]
    queue_counts: dict[str, int]
    workflow: tuple[WorkflowStep, ...]
    review_queues: tuple[ReviewQueue, ...]
    artifacts: tuple[ArtifactLink, ...]
    allowed_boundaries: tuple[str, ...] = ALLOWED_BOUNDARIES
    blocked_boundaries: tuple[str, ...] = BLOCKED_BOUNDARIES
    safe_next_actions: tuple[str, ...] = SAFE_NEXT_ACTIONS
    not_allowed_actions: tuple[str, ...] = NOT_ALLOWED_ACTIONS
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationsCockpitBuildResult:
    output_path: Path
    data: OperationsCockpitData
    link_targets_checked: int
    broken_links: tuple[str, ...] = ()


def build_operations_cockpit(
    *,
    repo_root: str | Path = Path("."),
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    fake_client_output: str | Path = DEFAULT_FAKE_CLIENT_OUTPUT,
    demo_output: str | Path = DEFAULT_DEMO_OUTPUT,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> OperationsCockpitBuildResult:
    """Build the read-only static operations cockpit from local artifacts."""

    root = Path(repo_root).resolve()
    output = _resolve_under_root(root, output_path)
    _ensure_tokens_file(root)
    _ensure_icon_file(root)
    data = collect_operations_cockpit_data(
        repo_root=root,
        output_path=output,
        fake_client_output=fake_client_output,
        demo_output=demo_output,
        db_path=db_path,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_operations_cockpit(data), encoding="utf-8")
    broken_links = verify_generated_links(output, root)
    return OperationsCockpitBuildResult(
        output_path=output,
        data=data,
        link_targets_checked=len(_extract_hrefs(output.read_text(encoding="utf-8"))),
        broken_links=tuple(str(path) for path in broken_links),
    )


def collect_operations_cockpit_data(
    *,
    repo_root: str | Path = Path("."),
    output_path: str | Path = DEFAULT_OUTPUT_PATH,
    fake_client_output: str | Path = DEFAULT_FAKE_CLIENT_OUTPUT,
    demo_output: str | Path = DEFAULT_DEMO_OUTPUT,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> OperationsCockpitData:
    root = Path(repo_root).resolve()
    output = _resolve_under_root(root, output_path)
    fake_root = _resolve_under_root(root, fake_client_output)
    demo_root = _resolve_under_root(root, demo_output)
    db = _resolve_under_root(root, db_path)

    fake_manifest_path = fake_root / "manifest.json"
    fake_summary_path = fake_root / "summary.json"
    demo_manifest_path = demo_root / "manifest.json"
    demo_summary_path = demo_root / "summary.json"

    fake_manifest = _read_json_object(fake_manifest_path)
    fake_summary = _read_json_object(fake_summary_path)
    demo_manifest = _read_json_object(demo_manifest_path)
    demo_summary = _read_json_object(demo_summary_path)
    bank_proposals = _read_json_list(fake_root / "bank_reconciliation_proposals.json")

    supplier_cases = _supplier_cases_from_manifest(fake_manifest, root)
    review_items = _collect_review_items(
        supplier_cases=supplier_cases,
        bank_proposals=bank_proposals,
        fake_manifest=fake_manifest,
        root=root,
    )
    review_queues = _build_review_queues(review_items)
    artifacts = _collect_artifacts(root, fake_root, demo_root)
    queue_counts = _read_queue_counts(db)
    live_counters = _live_counters(fake_manifest, demo_manifest)
    workflow = _build_workflow(
        root=root,
        fake_root=fake_root,
        demo_root=demo_root,
        fake_manifest=fake_manifest,
        fake_summary=fake_summary,
        demo_manifest=demo_manifest,
        demo_summary=demo_summary,
        bank_proposals=bank_proposals,
        supplier_cases=supplier_cases,
    )
    warnings = _collect_warnings(fake_manifest)

    return OperationsCockpitData(
        generated_at=_utc_now(),
        repo_root=str(root),
        output_path=str(output),
        last_run=_last_run(fake_manifest_path, fake_manifest, demo_manifest_path, demo_manifest),
        local_readiness=_local_readiness(fake_manifest, fake_summary),
        demo_readiness=_demo_readiness(demo_manifest, demo_summary),
        live_counters=live_counters,
        queue_counts=queue_counts,
        workflow=workflow,
        review_queues=review_queues,
        artifacts=artifacts,
        warnings=warnings,
    )


def render_operations_cockpit(data: OperationsCockpitData) -> str:
    root = Path(data.repo_root)
    output = Path(data.output_path)
    tokens_href = _href(root / DEFAULT_TOKENS_PATH, output)
    icon_href = _href(root / DEFAULT_ICON_PATH, output)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en-GB">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>Accounting Agent Operations Cockpit</title>",
            '<meta name="description" content="A read-only local workbench for accounting review, evidence, and guarded automation.">',
            f'<link rel="icon" type="image/svg+xml" href="{icon_href}">',
            f'<link rel="stylesheet" href="{tokens_href}">',
            "<style>",
            _CSS,
            "</style>",
            "</head>",
            '<body data-view="guided" data-role="small-firm">',
            '<a class="skip-link" href="#main-content">Skip to main content</a>',
            _render_environment_strip(),
            _render_header(data),
            _render_section_nav(),
            '<main id="main-content" class="shell">',
            _render_status_grid(data),
            _render_review_queues(data, root, output),
            _render_workflow(data, root, output),
            _render_integrations(),
            _render_controls(data, root, output),
            "</main>",
            _render_footer(data),
            _render_command_dialog(),
            "<script>",
            _SCRIPT,
            "</script>",
            "</body>",
            "</html>",
            "",
        ]
    )


def verify_generated_links(html_path: str | Path, repo_root: str | Path) -> list[Path]:
    page = Path(html_path)
    root = Path(repo_root).resolve()
    broken: list[Path] = []
    for href in _extract_hrefs(page.read_text(encoding="utf-8")):
        if not href or href.startswith("#"):
            continue
        if _looks_external(href):
            broken.append(Path(href))
            continue
        target = (page.parent / href).resolve()
        if not _is_relative_to(target, root) or not target.exists():
            broken.append(target)
    return broken


def _render_environment_strip() -> str:
    return """
<aside class="environment-strip" aria-label="Environment and safety context" data-aria-label-en="Environment and safety context" data-aria-label-sv="Miljö- och säkerhetskontext">
  <div class="shell environment-inner">
    <strong data-i18n data-en="Local synthetic dry-run" data-sv="Lokal syntetisk torrkörning">Local synthetic dry-run</strong>
    <span data-i18n data-en="Sweden" data-sv="Sverige">Sweden</span>
    <span>SEK</span>
    <span>BAS 2026</span>
    <span data-i18n data-en="Provider-neutral ERP profile" data-sv="Leverantörsneutral ERP-profil">Provider-neutral ERP profile</span>
    <span class="boundary-state" data-i18n data-en="Live writes blocked" data-sv="Skrivning i live-system blockerad">Live writes blocked</span>
  </div>
</aside>""".strip()


def _render_header(data: OperationsCockpitData) -> str:
    return f"""
<header class="app-header shell">
  <div class="header-copy">
    <h1>Accounting Agent Operations Cockpit</h1>
    <p data-i18n data-en="Review what needs judgment, understand why it stopped, and trace every proposal back to local evidence." data-sv="Granska det som kräver bedömning, förstå varför arbetet stoppades och spåra varje förslag till lokalt underlag.">Review what needs judgment, understand why it stopped, and trace every proposal back to local evidence.</p>
  </div>
  <div class="header-tools" aria-label="Workspace preferences" data-aria-label-en="Workspace preferences" data-aria-label-sv="Inställningar för arbetsytan">
    <button class="command-trigger" id="command-trigger" type="button" aria-haspopup="dialog" aria-controls="command-dialog">
      <span data-i18n data-en="Find a section" data-sv="Hitta en sektion">Find a section</span>
      <kbd id="command-shortcut">⌘ K</kbd>
    </button>
    <label class="field-control">
      <span data-i18n data-en="Guidance perspective" data-sv="Vägledningsperspektiv">Guidance perspective</span>
      <select id="role-select" name="role">
        <option value="small-firm" data-i18n data-en="Small-firm accountant" data-sv="Redovisningskonsult, mindre byrå">Small-firm accountant</option>
        <option value="accountant" data-i18n data-en="Accountant" data-sv="Redovisningsekonom">Accountant</option>
        <option value="senior" data-i18n data-en="Senior accountant" data-sv="Senior redovisningsekonom">Senior accountant</option>
        <option value="controller" data-i18n data-en="Financial controller" data-sv="Financial controller">Financial controller</option>
        <option value="auditor" data-i18n data-en="Auditor" data-sv="Revisor">Auditor</option>
        <option value="operator" data-i18n data-en="Agent operator" data-sv="Agentoperatör">Agent operator</option>
      </select>
    </label>
    <label class="field-control locale-control">
      <span data-i18n data-en="Language" data-sv="Språk">Language</span>
      <select id="locale-select" name="locale">
        <option value="en-GB">English</option>
        <option value="sv-SE">Svenska</option>
      </select>
    </label>
    <fieldset class="view-toggle">
      <legend data-i18n data-en="Detail level" data-sv="Detaljnivå">Detail level</legend>
      <label><input type="radio" name="view" value="guided" checked><span data-i18n data-en="Guided" data-sv="Guidad">Guided</span></label>
      <label><input type="radio" name="view" value="expert"><span data-i18n data-en="Expert" data-sv="Expert">Expert</span></label>
    </fieldset>
  </div>
  <p class="role-guidance" id="role-guidance">Queue-first guidance with plain-language evidence and explicit human decisions.</p>
  <p class="role-boundary" data-i18n data-en="Perspective changes guidance only; safety policy and risk priority stay fixed." data-sv="Perspektivet ändrar bara vägledningen; säkerhetspolicy och riskprioritet ligger fast.">Perspective changes guidance only; safety policy and risk priority stay fixed.</p>
  <p class="generation-stamp"><span data-i18n data-en="Snapshot generated" data-sv="Ögonblicksbild skapad">Snapshot generated</span> <time datetime="{_e(data.generated_at)}">{_e(_display_time(data.generated_at))}</time></p>
</header>""".strip()


def _render_section_nav() -> str:
    return """
<nav class="section-nav" aria-label="Cockpit sections" data-aria-label-en="Cockpit sections" data-aria-label-sv="Cockpitens sektioner">
  <div class="shell section-nav-inner">
    <a href="#today" data-i18n data-en="Today" data-sv="Idag">Today</a>
    <a href="#review" data-i18n data-en="Review" data-sv="Granskning">Review</a>
    <a href="#workflow" data-i18n data-en="Workflow" data-sv="Arbetsflöde">Workflow</a>
    <a href="#integrations" data-i18n data-en="Integrations" data-sv="Integrationer">Integrations</a>
    <a href="#controls" data-i18n data-en="Controls &amp; evidence" data-sv="Kontroller och underlag">Controls &amp; evidence</a>
  </div>
</nav>""".strip()


def _render_status_grid(data: OperationsCockpitData) -> str:
    priority_count = len(_prioritized_review_items(data.review_queues))
    local_complete = data.local_readiness == "local_fake_client_dry_run_complete"
    demo_complete = data.demo_readiness == "supplier_invoice_demo_complete"
    live_fortnox = data.live_counters.get("live_fortnox_calls", 0)
    live_microsoft = data.live_counters.get("live_microsoft365_calls", 0)
    external_actions = data.live_counters.get("emails_payments_filings", 0)
    local_value = "Complete · review remains" if local_complete and priority_count else "Complete" if local_complete else "Not ready"
    local_value_sv = "Klar · granskning återstår" if local_complete and priority_count else "Klar" if local_complete else "Inte klar"
    local_tone = "warning" if local_complete and priority_count else "safe" if local_complete else "neutral"
    demo_value = "Complete" if demo_complete else "Not ready"
    demo_value_sv = "Klar" if demo_complete else "Inte klar"
    cards = (
        ("Priority cases", "Prioriterade ärenden", str(priority_count), str(priority_count), "danger" if priority_count else "safe", "Unique cases, highest risk first", "Unika ärenden, högst risk först"),
        ("Local run", "Lokal körning", local_value, local_value_sv, local_tone, _display_time(data.last_run), _display_time(data.last_run)),
        ("Fixture demo", "Testdatademo", demo_value, demo_value_sv, "safe" if demo_complete else "neutral", "Synthetic evidence only", "Endast syntetiskt underlag"),
        ("Live ERP calls", "ERP-anrop i live-system", str(live_fortnox), str(live_fortnox), "safe" if live_fortnox == 0 else "danger", "Zero required", "Noll krävs"),
        ("Live Microsoft 365 calls", "Microsoft 365-anrop i live-system", str(live_microsoft), str(live_microsoft), "safe" if live_microsoft == 0 else "danger", "Zero required", "Noll krävs"),
        ("Emails, payments, or filings", "E-post, betalningar eller inlämningar", str(external_actions), str(external_actions), "safe" if external_actions == 0 else "danger", "Zero required", "Noll krävs"),
    )
    body = "".join(
        f"""
    <div class="stat" data-tone="{tone}">
      <dt {_i18n_attrs(label, label_sv)}>{_e(label)}</dt>
      <dd {_i18n_attrs(value, value_sv)}>{_e(value)}</dd>
      <span {_i18n_attrs(note, note_sv)}>{_e(note)}</span>
    </div>"""
        for label, label_sv, value, value_sv, tone, note, note_sv in cards
    )
    queue = "".join(
        f"<div><dt>{_e(key.replace('_', ' '))}</dt><dd>{count}</dd></div>"
        for key, count in sorted(data.queue_counts.items())
    )
    queue_block = (
        f'<dl class="ledger-counts">{queue}</dl>'
        if queue
        else '<p class="empty-state">No local SQLite queue counts found yet.</p>'
    )
    return f"""
<section class="workbench-section" id="today" aria-labelledby="today-title">
  <div class="section-heading">
    <div>
      <h2 id="today-title" data-i18n data-en="Today" data-sv="Idag">Today</h2>
      <p data-i18n data-en="Current local run state. Building this page never calls an ERP, email, payment, tax, or filing system." data-sv="Aktuellt lokalt körläge. När sidan byggs anropas inga ERP-, e-post-, betalnings-, skatte- eller inlämningssystem.">Current local run state. Building this page never calls an ERP, email, payment, tax, or filing system.</p>
    </div>
    <p class="last-run"><span data-i18n data-en="Latest evidence" data-sv="Senaste underlag">Latest evidence</span> <time datetime="{_e(data.last_run)}">{_e(_display_time(data.last_run))}</time></p>
  </div>
  <dl class="stat-strip">{body}</dl>
  <div class="boundary-notice" data-tone="danger">
    <strong data-i18n data-en="Observe and review only." data-sv="Endast observation och granskning.">Observe and review only.</strong>
    <span data-i18n data-en="This cockpit cannot approve itself or execute accounting actions. Any non-zero live counter above is a safety violation, never a success state." data-sv="Cockpiten kan inte godkänna sitt eget arbete eller utföra redovisningsåtgärder. Ett värde över noll i live-räknarna är ett säkerhetsfel, aldrig ett framgångsläge.">This cockpit cannot approve itself or execute accounting actions. Any non-zero live counter above is a safety violation, never a success state.</span>
  </div>
  <details class="local-counts expert-only">
    <summary data-i18n data-en="Local evidence table counts" data-sv="Lokala tabellräknare för underlag">Local evidence table counts</summary>
    {queue_block}
  </details>
</section>""".strip()


def _render_safety(data: OperationsCockpitData) -> str:
    allowed = "".join(
        f'<li {_i18n_attrs(item, _BOUNDARY_SV.get(item, item))}>{_e(item)}</li>'
        for item in data.allowed_boundaries
    )
    blocked = "".join(
        f'<li {_i18n_attrs(item, _BOUNDARY_SV.get(item, item))}>{_e(item)}</li>'
        for item in data.blocked_boundaries
    )
    warnings = "".join(f"<li>{_e(item)}</li>" for item in data.warnings)
    warning_block = (
        f"""
  <div class="boundary-notice" data-tone="warning">
    <strong data-i18n data-en="Policy alignment warnings" data-sv="Varningar om policyöverensstämmelse">Policy alignment warnings</strong>
    <ul>{warnings}</ul>
  </div>"""
        if warnings
        else ""
    )
    return f"""
<div class="safety-boundaries">
{warning_block}
  <div class="boundary-columns">
    <section aria-labelledby="allowed-title">
      <h3 id="allowed-title" data-i18n data-en="Allowed in this build" data-sv="Tillåtet i denna version">Allowed in this build</h3>
      <ul class="boundary-list allowed">{allowed}</ul>
    </section>
    <section aria-labelledby="blocked-title">
      <h3 id="blocked-title" data-i18n data-en="Always stopped for human decision" data-sv="Stoppas alltid för mänskligt beslut">Always stopped for human decision</h3>
      <ul class="boundary-list blocked">{blocked}</ul>
    </section>
  </div>
</div>""".strip()


def _render_workflow(
    data: OperationsCockpitData,
    root: Path,
    output: Path,
) -> str:
    steps = []
    for index, step in enumerate(data.workflow, start=1):
        link = _optional_link(step.artifact_path, root, output, "Evidence", "Underlag")
        state = _friendly_state(step.status)
        steps.append(
            f"""
    <li class="workflow-step" data-state="{_e(step.status)}">
      <span class="step-number" aria-hidden="true">{index:02d}</span>
      <div>
        <h3 {_i18n_attrs(step.label, _workflow_label_sv(step.label))}>{_e(step.label)}</h3>
        <p {_i18n_attrs(step.detail, _workflow_detail_sv(step.key, step.detail))}>{_e(step.detail)}</p>
      </div>
      <div class="step-meta"><span {_i18n_attrs(state, _friendly_state_sv(step.status))}>{_e(state)}</span>{link}</div>
    </li>"""
        )
    agents = "".join(
        f"""
    <li>
      <div class="agent-stage"><span>{index:02d}</span><strong {_i18n_attrs(stage, _SPECIALIST_SV[stage][0])}>{_e(stage)}</strong></div>
      <div><h3 {_i18n_attrs(owner, _SPECIALIST_SV[stage][1])}>{_e(owner)}</h3><p {_i18n_attrs(detail, _SPECIALIST_SV[stage][2])}>{_e(detail)}</p></div>
    </li>"""
        for index, (stage, owner, detail) in enumerate(SPECIALIST_STAGES, start=1)
    )
    return f"""
<section class="workbench-section" id="workflow" aria-labelledby="workflow-title">
  <div class="section-heading">
    <div>
      <h2 id="workflow-title" data-i18n data-en="Workflow" data-sv="Arbetsflöde">Workflow</h2>
      <p data-i18n data-en="A deterministic accounting path first; bounded specialist agents add analysis without changing the permission ceiling." data-sv="Först ett deterministiskt redovisningsflöde; avgränsade specialistagenter tillför analys utan att höja behörighetstaket.">A deterministic accounting path first; bounded specialist agents add analysis without changing the permission ceiling.</p>
    </div>
  </div>
  <ol class="workflow-sequence">{''.join(steps)}</ol>
  <div class="subsection-heading">
    <h3 data-i18n data-en="Bounded specialist-agent pipeline" data-sv="Avgränsad pipeline med specialistagenter">Bounded specialist-agent pipeline</h3>
    <p data-i18n data-en="Parallel where evidence can be inspected independently, sequential where judgment depends on verified results." data-sv="Parallellt när underlag kan granskas oberoende, sekventiellt när bedömningen beror på verifierade resultat.">Parallel where evidence can be inspected independently, sequential where judgment depends on verified results.</p>
  </div>
  <ol class="agent-pipeline">{agents}</ol>
  <div class="boundary-notice" data-tone="neutral">
    <strong data-i18n data-en="Coordinator rule" data-sv="Koordinatorregel">Coordinator rule</strong>
    <span data-i18n data-en="Every specialist inherits the same client, jurisdiction, evidence, capability, timeout, and stop boundaries. A monitor may stop work, but no agent may approve its own output." data-sv="Varje specialist ärver samma klient, jurisdiktion, underlag, behörighet, tidsgräns och stoppvillkor. En monitor får stoppa arbetet, men ingen agent får godkänna sitt eget resultat.">Every specialist inherits the same client, jurisdiction, evidence, capability, timeout, and stop boundaries. A monitor may stop work, but no agent may approve its own output.</span>
  </div>
</section>""".strip()


def _render_review_queues(
    data: OperationsCockpitData,
    root: Path,
    output: Path,
) -> str:
    items = _prioritized_review_items(data.review_queues)
    rows = []
    for item in items:
        categories = " · ".join(item.categories)
        raw_reason = "; ".join(item.reasons)
        guided_reason = _guided_review_reason(item)
        title_sv = _review_title_sv(item.title)
        guided_reason_sv = _guided_review_reason(item, swedish=True)
        evidence = _optional_link(item.artifact_path, root, output, "Open evidence", "Öppna underlag")
        missing_evidence = (
            f'<span {_i18n_attrs("Evidence not generated", "Underlag saknas")}>'
            "Evidence not generated</span>"
        )
        search_text = " ".join(
            (item.item_id, item.source, item.mode, item.severity, item.title, title_sv, categories, raw_reason, guided_reason, guided_reason_sv)
        ).lower()
        source_sv = _SOURCE_SV.get(item.source.title(), item.source.title())
        severity_sv = _SEVERITY_SV.get(item.severity, item.severity)
        rows.append(
            f"""
    <li class="attention-row" data-severity="{_e(item.severity)}" data-search="{_e(search_text)}">
      <div class="attention-priority">
        <span class="severity" data-severity="{_e(item.severity)}" {_i18n_attrs(item.severity, severity_sv)}>{_e(item.severity)}</span>
        <span {_i18n_attrs(item.source.title(), source_sv)}>{_e(item.source.title())}</span>
      </div>
      <div class="attention-copy">
        <h3 {_i18n_attrs(item.title, title_sv)}>{_e(item.title)}</h3>
        <p {_i18n_attrs(guided_reason, guided_reason_sv)}>{_e(guided_reason)}</p>
        <details class="expert-only">
          <summary {_i18n_attrs('Technical context', 'Teknisk kontext')}>Technical context</summary>
          <dl class="technical-context">
            <div><dt {_i18n_attrs('Case ID', 'Ärende-ID')}>Case ID</dt><dd><code>{_e(item.item_id)}</code></dd></div>
            <div><dt {_i18n_attrs('Policy mode', 'Policyläge')}>Policy mode</dt><dd><code>{_e(item.mode)}</code></dd></div>
            <div><dt {_i18n_attrs('Signals', 'Signaler')}>Signals</dt><dd>{_e(categories)}</dd></div>
            <div><dt {_i18n_attrs('Raw reasons', 'Råa orsaker')}>Raw reasons</dt><dd>{_e(raw_reason)}</dd></div>
          </dl>
        </details>
      </div>
      <div class="attention-action">{evidence or missing_evidence}</div>
    </li>"""
        )
    content = (
        f'<ol class="attention-list" id="attention-list">{"".join(rows)}</ol>'
        if rows
        else f'<p class="empty-state" {_i18n_attrs("No current items found in local artifacts.", "Inga aktuella ärenden hittades i lokala filer.")}>No current items found in local artifacts.</p>'
    )
    return f"""
<section class="workbench-section" id="review" aria-labelledby="review-title">
  <div class="section-heading">
    <div>
      <h2 id="review-title" data-i18n data-en="Review" data-sv="Granskning">Review</h2>
      <p data-i18n data-en="One row per case. Repeated risk signals are combined, and the most serious stop condition determines priority." data-sv="En rad per ärende. Upprepade risksignaler slås samman och det allvarligaste stoppvillkoret avgör prioriteten.">One row per case. Repeated risk signals are combined, and the most serious stop condition determines priority.</p>
    </div>
    <p class="result-count" id="review-result-count" aria-live="polite">{len(items)} items shown</p>
  </div>
  <div class="review-filters" aria-label="Review filters" data-aria-label-en="Review filters" data-aria-label-sv="Granskningsfilter">
    <label class="search-field">
      <span data-i18n data-en="Search review work" data-sv="Sök granskningsarbete">Search review work</span>
      <input id="review-search" type="search" autocomplete="off" placeholder="Supplier, VAT, duplicate, bank…" data-placeholder-en="Supplier, VAT, duplicate, bank…" data-placeholder-sv="Leverantör, moms, dubblett, bank…">
    </label>
    <label class="field-control">
      <span data-i18n data-en="Priority" data-sv="Prioritet">Priority</span>
      <select id="review-severity">
        <option value="all" data-i18n data-en="All priorities" data-sv="Alla prioriteter">All priorities</option>
        <option value="critical" data-i18n data-en="Critical" data-sv="Kritisk">Critical</option>
        <option value="high" data-i18n data-en="High" data-sv="Hög">High</option>
        <option value="medium" data-i18n data-en="Medium" data-sv="Medel">Medium</option>
        <option value="low" data-i18n data-en="Low" data-sv="Låg">Low</option>
      </select>
    </label>
  </div>
  <div class="empty-state review-empty" id="review-empty" hidden>
    <span data-i18n data-en="No review items match these filters." data-sv="Inga granskningsärenden matchar filtren.">No review items match these filters.</span>
    <button class="secondary-button" id="clear-review-filters" type="button" data-i18n data-en="Clear filters" data-sv="Rensa filter">Clear filters</button>
  </div>
  {content}
</section>""".strip()


def _render_artifacts(
    data: OperationsCockpitData,
    root: Path,
    output: Path,
) -> str:
    groups: dict[str, list[ArtifactLink]] = {}
    for artifact in data.artifacts:
        groups.setdefault(artifact.kind, []).append(artifact)
    rendered_groups = []
    for kind in sorted(groups):
        artifacts = groups[kind]
        available_count = sum(1 for artifact in artifacts if artifact.exists)
        availability_en = f"{available_count} of {len(artifacts)} available"
        availability_sv = f"{available_count} av {len(artifacts)} tillgängliga"
        rows = []
        for artifact in artifacts:
            label = _e(artifact.label)
            note = f'<span class="artifact-note">{_e(artifact.note)}</span>' if artifact.note else ""
            if artifact.exists:
                href = _href(root / artifact.path, output)
                target = (
                    f'<span class="artifact-label">{label}</span>'
                    f'<a class="artifact-open" href="{href}" {_i18n_attrs("Open file", "Öppna fil")}>Open file</a>'
                )
                status = "available"
                status_label = "Available"
            else:
                target = f"<span>{label}</span>"
                status = "missing"
                status_label = "Not generated"
            status_label_sv = "Tillgänglig" if status == "available" else "Inte genererad"
            rows.append(
                f"""
        <li data-state="{status}">
          <div>{target}{note}</div>
          <strong {_i18n_attrs(status_label, status_label_sv)}>{status_label}</strong>
        </li>"""
            )
        rendered_groups.append(
            f"""
    <details class="artifact-group">
      <summary><span {_i18n_attrs(kind.title(), _ARTIFACT_KIND_SV.get(kind, kind.title()))}>{_e(kind.title())}</span><span {_i18n_attrs(availability_en, availability_sv)}>{availability_en}</span></summary>
      <ul class="artifact-list">{''.join(rows)}</ul>
    </details>"""
        )
    if not rendered_groups:
        return f'<p class="empty-state" {_i18n_attrs("No local artifacts have been indexed yet.", "Inga lokala underlag har indexerats ännu.")}>No local artifacts have been indexed yet.</p>'
    return '<div class="artifact-groups">' + "".join(rendered_groups) + "</div>"


def _render_actions(data: OperationsCockpitData) -> str:
    safe = "".join(f"<li><code>{_e(command)}</code></li>" for command in data.safe_next_actions)
    blocked = "".join(
        f'<li {_i18n_attrs(action, _BOUNDARY_SV.get(action, action))}>{_e(action)}</li>'
        for action in data.not_allowed_actions
    )
    return f"""
<div class="action-columns">
  <details class="operator-actions expert-only">
    <summary data-i18n data-en="Safe local operator commands" data-sv="Säkra lokala operatörskommandon">Safe local operator commands</summary>
    <ul class="command-list">{safe}</ul>
  </details>
  <section aria-labelledby="not-allowed-title">
    <h3 id="not-allowed-title" data-i18n data-en="Actions this cockpit cannot take" data-sv="Åtgärder som cockpiten inte kan utföra">Actions this cockpit cannot take</h3>
    <ul class="boundary-list blocked">{blocked}</ul>
  </section>
</div>""".strip()


def _render_integrations() -> str:
    rendered_rows = []
    for provider, channel, state, permitted, blocked in _integration_profiles():
        rendered_rows.append(
            f"""
      <tr>
        <th scope="row">{_e(provider)}</th>
        <td data-label="Channel" data-label-en="Channel" data-label-sv="Kanal">{_e(channel)}</td>
        <td data-label="Current state" data-label-en="Current state" data-label-sv="Aktuellt läge" {_i18n_attrs(state, _integration_text_sv(state))}>{_e(state)}</td>
        <td data-label="Permitted" data-label-en="Permitted" data-label-sv="Tillåtet" {_i18n_attrs(permitted, _integration_text_sv(permitted))}>{_e(permitted)}</td>
        <td data-label="Blocked" data-label-en="Blocked" data-label-sv="Blockerat" {_i18n_attrs(blocked, _integration_text_sv(blocked))}>{_e(blocked)}</td>
      </tr>"""
        )
    rows = "".join(rendered_rows)
    return f"""
<section class="workbench-section" id="integrations" aria-labelledby="integrations-title">
  <div class="section-heading">
    <div>
      <h2 id="integrations-title" data-i18n data-en="Integrations" data-sv="Integrationer">Integrations</h2>
      <p data-i18n data-en="One capability contract across ERP providers. A configured connection may narrow permissions, but it can never widen this build's boundary." data-sv="Ett gemensamt behörighetskontrakt gäller för alla ERP-leverantörer. En konfigurerad anslutning får begränsa behörigheter men aldrig utöka versionens gräns.">One capability contract across ERP providers. A configured connection may narrow permissions, but it can never widen this build's boundary.</p>
    </div>
  </div>
  <div class="table-frame">
    <table class="integration-table">
      <caption data-i18n data-en="Provider-neutral capability matrix" data-sv="Leverantörsneutral behörighetsmatris">Provider-neutral capability matrix</caption>
      <thead><tr><th scope="col" data-i18n data-en="Provider" data-sv="Leverantör">Provider</th><th scope="col" data-i18n data-en="Channel" data-sv="Kanal">Channel</th><th scope="col" data-i18n data-en="Current state" data-sv="Aktuellt läge">Current state</th><th scope="col" data-i18n data-en="Permitted" data-sv="Tillåtet">Permitted</th><th scope="col" data-i18n data-en="Blocked" data-sv="Blockerat">Blocked</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div class="boundary-notice" data-tone="warning">
    <strong data-i18n data-en="Computer use is a last-mile fallback." data-sv="Datoranvändning är en sista utväg.">Computer use is a last-mile fallback.</strong>
    <span data-i18n data-en="It stays visible, read-only, narrowly scoped, and supervised. Any credential request, unexpected instruction, or prompt-injection signal stops the task." data-sv="Den är synlig, skrivskyddad, snävt avgränsad och övervakad. En begäran om inloggningsuppgifter, en oväntad instruktion eller en signal om promptinjektion stoppar uppgiften.">It stays visible, read-only, narrowly scoped, and supervised. Any credential request, unexpected instruction, or prompt-injection signal stops the task.</span>
  </div>
</section>""".strip()


def _integration_profiles() -> tuple[tuple[str, str, str, str, str], ...]:
    rows: list[tuple[str, str, str, str, str]] = []
    for profile in list_erp_profiles():
        if profile.provider is ErpProvider.SUPERVISED_COMPUTER_USE:
            rows.append(
                (
                    profile.display_name,
                    profile.transport,
                    "Observation-only fallback",
                    " · ".join(COMPUTER_USE_BOUNDARY.allowed_tasks),
                    " · ".join(COMPUTER_USE_BOUNDARY.forbidden_tasks),
                )
            )
            continue
        permitted = [
            declaration.capability.value.replace("_", " ")
            for declaration in profile.capabilities
            if declaration.mode in {
                CapabilityMode.LOCAL_ONLY,
                CapabilityMode.GUARDED_READ_ONLY,
            }
        ]
        rows.append(
            (
                profile.display_name,
                profile.transport,
                profile.connection_status.replace("_", " ").capitalize(),
                " · ".join(permitted) or "No connected capabilities",
                "External draft · post · approve · send · pay · file · delete · settings",
            )
        )
    return tuple(rows)


_INTEGRATION_SV = {
    "Mocked dry run only": "Endast simulerad torrkörning",
    "Manifest only": "Endast manifest",
    "Local fixture path": "Lokal sökväg för testdata",
    "Observation-only fallback": "Reservläge för skrivskyddad observation",
    "No connected capabilities": "Inga anslutna funktioner",
    "External draft": "Externt utkast",
    "post": "bokför",
    "approve": "godkänn",
    "send": "skicka",
    "pay": "betala",
    "file": "lämna in",
    "delete": "radera",
    "settings": "inställningar",
    "discover schema": "identifiera schema",
    "discover capabilities": "identifiera funktioner",
    "read master data": "läs masterdata",
    "read transactions": "läs transaktioner",
    "read period locks": "läs periodlås",
    "import staged": "importera mellanlagrat",
    "export raw": "exportera rådata",
    "validate local": "validera lokalt",
    "prepare local draft": "förbered lokalt utkast",
    "simulate local": "simulera lokalt",
    "local_app_ui_testing": "lokal UI-testning",
    "whitelisted_erp_observation": "vitlistad ERP-observation",
    "screenshot_and_evidence_capture": "skärmbild och underlagsinsamling",
    "human_readable_action_plan_preparation": "förbered läsbar åtgärdsplan",
    "type_into_remote_erp_form": "skriv i fjärranslutet ERP-formulär",
    "submit_post_approve_send_pay_file_delete_or_change_settings": "skicka, bokför, godkänn, betala, lämna in, radera eller ändra inställningar",
    "tax_filing": "skatteinlämning",
    "client_communication": "klientkommunikation",
    "handle_credentials_or_secrets": "hantera inloggningsuppgifter eller hemligheter",
}


def _integration_text_sv(value: str) -> str:
    if value in _INTEGRATION_SV:
        return _INTEGRATION_SV[value]
    return " · ".join(_INTEGRATION_SV.get(part, part) for part in value.split(" · "))


def _render_controls(
    data: OperationsCockpitData,
    root: Path,
    output: Path,
) -> str:
    return f"""
<section class="workbench-section" id="controls" aria-labelledby="controls-title">
  <div class="section-heading">
    <div>
      <h2 id="controls-title" data-i18n data-en="Controls &amp; evidence" data-sv="Kontroller och underlag">Controls &amp; evidence</h2>
      <p data-i18n data-en="Policy boundaries, local evidence, and reproducible commands live together so a reviewer can verify before deciding." data-sv="Policygränser, lokalt underlag och reproducerbara kommandon finns samlade så att en granskare kan verifiera före beslut.">Policy boundaries, local evidence, and reproducible commands live together so a reviewer can verify before deciding.</p>
    </div>
  </div>
  {_render_safety(data)}
  <div class="subsection-heading">
    <h3 data-i18n data-en="Local evidence library" data-sv="Lokalt underlagsbibliotek">Local evidence library</h3>
    <p data-i18n data-en="Grouped by purpose. Links are emitted only for existing files under the workspace." data-sv="Grupperat efter syfte. Länkar skapas endast för befintliga filer i arbetsytan.">Grouped by purpose. Links are emitted only for existing files under the workspace.</p>
  </div>
  {_render_artifacts(data, root, output)}
  {_render_actions(data)}
</section>""".strip()


def _render_footer(data: OperationsCockpitData) -> str:
    return f"""
<footer class="site-footer">
  <div class="shell footer-line">
    <p><span data-i18n data-en="Local static cockpit" data-sv="Lokal statisk cockpit">Local static cockpit</span> · <time datetime="{_e(data.generated_at)}">{_e(_display_time(data.generated_at))}</time></p>
    <p data-i18n data-en="No external network assets · no live integration authority" data-sv="Inga externa nätverksresurser · ingen behörighet i live-integrationer">No external network assets · no live integration authority</p>
  </div>
</footer>""".strip()


def _render_command_dialog() -> str:
    commands = (
        ("#today", "Open Today", "Öppna Idag", "Run state and live counters", "Körläge och live-räknare"),
        ("#review", "Open Review", "Öppna Granskning", "Prioritised human decisions", "Prioriterade mänskliga beslut"),
        ("#workflow", "Open Workflow", "Öppna Arbetsflöde", "Deterministic and specialist-agent stages", "Deterministiska steg och specialistagenter"),
        ("#integrations", "Open Integrations", "Öppna Integrationer", "ERP and supervised computer-use boundaries", "ERP-gränser och övervakad datoranvändning"),
        ("#controls", "Open Controls & evidence", "Öppna Kontroller och underlag", "Policy, artifacts, and local commands", "Policy, underlag och lokala kommandon"),
    )
    items = "".join(
        f'<li><a href="{href}"><strong {_i18n_attrs(label, label_sv)}>{_e(label)}</strong><span {_i18n_attrs(detail, detail_sv)}>{_e(detail)}</span></a></li>'
        for href, label, label_sv, detail, detail_sv in commands
    )
    return f"""
<dialog class="command-dialog" id="command-dialog" aria-labelledby="command-title">
  <form method="dialog" class="command-shell">
    <div class="command-head">
      <h2 id="command-title" data-i18n data-en="Find a section" data-sv="Hitta en sektion">Find a section</h2>
      <button class="dialog-close" value="close" type="submit" data-i18n data-en="Close" data-sv="Stäng">Close</button>
    </div>
    <label class="search-field command-search">
      <span data-i18n data-en="Search this cockpit" data-sv="Sök i cockpiten">Search this cockpit</span>
      <input id="command-search" type="search" autocomplete="off" placeholder="Type a section name…" data-placeholder-en="Type a section name…" data-placeholder-sv="Skriv ett sektionsnamn…">
    </label>
    <ul class="command-listbox" id="command-list">{items}</ul>
    <p class="command-hint" data-i18n data-en="Use ↑ and ↓ to move, Enter to open, and Escape to close." data-sv="Använd ↑ och ↓ för att flytta, Enter för att öppna och Escape för att stänga.">Use ↑ and ↓ to move, Enter to open, and Escape to close.</p>
  </form>
</dialog>""".strip()


def _prioritized_review_items(
    review_queues: tuple[ReviewQueue, ...],
) -> tuple[PrioritizedReviewItem, ...]:
    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for queue in review_queues:
        for item in queue.items:
            key = (item.source, item.item_id)
            severity = _review_severity(item.mode, queue.key)
            current = combined.setdefault(
                key,
                {
                    "item": item,
                    "severity": severity,
                    "reasons": [],
                    "categories": [],
                    "artifact_path": item.artifact_path,
                },
            )
            if _severity_rank(severity) < _severity_rank(str(current["severity"])):
                current["severity"] = severity
                current["item"] = item
            if item.reason not in current["reasons"]:
                current["reasons"].append(item.reason)
            if queue.label not in current["categories"]:
                current["categories"].append(queue.label)
            if current["artifact_path"] is None and item.artifact_path:
                current["artifact_path"] = item.artifact_path

    prioritized = []
    for current in combined.values():
        item = current["item"]
        categories = tuple(str(category) for category in current["categories"])
        prioritized.append(
            PrioritizedReviewItem(
                item_id=item.item_id,
                source=item.source,
                mode=item.mode,
                severity=str(current["severity"]),
                title=_review_title(item.mode, categories),
                reasons=tuple(str(reason) for reason in current["reasons"]),
                categories=categories,
                artifact_path=current["artifact_path"],
            )
        )
    return tuple(
        sorted(
            prioritized,
            key=lambda item: (
                _severity_rank(item.severity),
                item.source.casefold(),
                item.title.casefold(),
                item.item_id.casefold(),
            ),
        )
    )


def _review_severity(mode: str, queue_key: str) -> str:
    if mode == "forbidden" or queue_key == "forbidden":
        return "critical"
    if mode == "escalation_required" or queue_key in {
        "changed_bank_details",
        "uncertain_vat",
        "duplicate_risk",
        "risky_suppliers",
    }:
        return "high"
    if mode == "approval_required" or queue_key in {
        "approval_required",
        "missing_info",
        "policy_alignment_warnings",
    }:
        return "medium"
    return "low"


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)


def _review_title(mode: str, categories: tuple[str, ...]) -> str:
    category_set = set(categories)
    if mode == "forbidden":
        return "Action is blocked"
    if "Changed bank details" in category_set:
        return "Supplier bank details changed"
    if "Uncertain VAT" in category_set:
        return "VAT treatment is uncertain"
    if "Duplicate risk" in category_set:
        return "Possible duplicate needs comparison"
    if mode == "escalation_required":
        return "Senior review is required"
    if "Missing info" in category_set:
        return "Evidence is missing"
    if "Policy alignment warnings" in category_set:
        return "Policy engines disagree"
    return "Human approval is required"


_REVIEW_TITLE_SV = {
    "Action is blocked": "Åtgärden är blockerad",
    "Supplier bank details changed": "Leverantörens bankuppgifter har ändrats",
    "VAT treatment is uncertain": "Momshanteringen är osäker",
    "Possible duplicate needs comparison": "Möjlig dubblett behöver jämföras",
    "Senior review is required": "Senior granskning krävs",
    "Evidence is missing": "Underlag saknas",
    "Policy engines disagree": "Policymotorerna är inte överens",
    "Human approval is required": "Mänskligt godkännande krävs",
}

_SEVERITY_SV = {
    "critical": "kritisk",
    "high": "hög",
    "medium": "medel",
    "low": "låg",
}

_SOURCE_SV = {
    "Supplier Invoice": "Leverantörsfaktura",
    "Bank Reconciliation": "Bankavstämning",
    "Customer Invoice": "Kundfaktura",
}


def _review_title_sv(title: str) -> str:
    return _REVIEW_TITLE_SV.get(title, title)


def _guided_review_reason(item: PrioritizedReviewItem, *, swedish: bool = False) -> str:
    category_set = set(item.categories)
    if item.mode == "forbidden":
        return (
            "Den här åtgärden är stoppad av en säkerhetsregel och kan inte fortsätta i denna version."
            if swedish
            else "A safety rule stops this action; it cannot continue in this build."
        )
    if "Changed bank details" in category_set:
        return (
            "Verifiera leverantörens betalningsuppgifter via en oberoende kanal innan arbetet fortsätter."
            if swedish
            else "Verify the supplier's payment details through an independent channel before continuing."
        )
    if "Uncertain VAT" in category_set:
        return (
            "En redovisningskunnig person måste bekräfta momshanteringen och underlaget."
            if swedish
            else "An accountant must confirm the VAT treatment and supporting evidence."
        )
    if "Duplicate risk" in category_set:
        return (
            "Jämför posterna och bekräfta om detta är en dubblett innan något utkast fortsätter."
            if swedish
            else "Compare the records and confirm whether this is a duplicate before any draft continues."
        )
    if "Missing info" in category_set:
        return (
            "Komplettera eller verifiera det saknade underlaget innan arbetet fortsätter."
            if swedish
            else "Supply or verify the missing evidence before continuing."
        )
    if "Policy alignment warnings" in category_set:
        return (
            "En ansvarig granskare måste lösa policykonflikten innan något utkast fortsätter."
            if swedish
            else "An accountable reviewer must resolve the policy conflict before any draft continues."
        )
    if item.mode == "escalation_required":
        return (
            "En senior redovisningskunnig person måste klassificera transaktionen och verifiera förslaget."
            if swedish
            else "A senior accountant must classify the transaction and verify the proposal."
        )
    return (
        "En mänsklig granskare måste godkänna, avvisa eller omfördela förslaget."
        if swedish
        else "A human reviewer must approve, reject, or reassign the proposal."
    )


def _friendly_state(status: str) -> str:
    return {
        "available": "Evidence available",
        "review_required": "Review required",
        "dry_run_only": "Dry-run only",
        "missing": "Not generated",
    }.get(status, status.replace("_", " ").capitalize())


def _friendly_state_sv(status: str) -> str:
    return {
        "available": "Underlag tillgängligt",
        "review_required": "Granskning krävs",
        "dry_run_only": "Endast torrkörning",
        "missing": "Inte genererat",
    }.get(status, status.replace("_", " "))


_WORKFLOW_LABEL_SV = {
    "Intake": "Inläsning",
    "Document registry": "Dokumentregister",
    "Extraction": "Extraktion",
    "Accounting proposal": "Konteringsförslag",
    "Policy gate": "Policykontroll",
    "Approval packet": "Granskningspaket",
    "Execution permit": "Exekveringstillstånd",
    "Fortnox dry-run": "Fortnox-torrkörning",
    "gnubok shadow validation": "gnubok-skuggvalidering",
    "Bank reconciliation": "Bankavstämning",
    "Audit/report": "Revision och rapport",
}


def _workflow_label_sv(label: str) -> str:
    return _WORKFLOW_LABEL_SV.get(label, label)


def _workflow_detail_sv(key: str, detail: str) -> str:
    match = re.match(r"(\d+)", detail)
    count = match.group(1) if match else "0"
    templates = {
        "intake": f"{count} normaliserade inläsningsärenden från syntetiska lokala exporter.",
        "document_registry": "Syntetiskt dokumentregister och hashvärden finns i lokala SQLite- och utdatafiler.",
        "extraction": f"{count} extraherade JSON-filer för fakturor.",
        "accounting_proposal": f"{count} konteringsförslag med BAS och moms.",
        "policy_gate": f"{count} ärenden kräver godkännande, eskalering eller stopphantering.",
        "approval_packet": f"{count} JSON-filer med granskningspaket för leverantörer.",
        "execution_permit": f"{count} lokala tillståndsposter; live-användning är fortsatt blockerad.",
        "fortnox_dry_run": f"{count} Fortnox-formade torrkörningsfiler; live-anrop är 0.",
        "gnubok_shadow_validation": f"{count} lokala jämförelsefiler för skugghuvudbok.",
        "bank_reconciliation": f"{count} förslag till bankavstämning.",
        "audit_report": f"{count} övergripande revisionshändelser samt Markdown-rapport.",
    }
    if key == "approval_packet" and "demo approval packets" in detail:
        return f"{count} granskningspaket från testdatademon."
    return templates.get(key, detail)


_SPECIALIST_SV = {
    "Scope": (
        "Omfattning",
        "Koordinator",
        "Låser klient, jurisdiktion, ERP, underlag, behörighetstak, tidsbudget och stoppvillkor.",
    ),
    "Inspect in parallel": (
        "Granska parallellt",
        "Inläsning · Extraktion · Leverantörsrisk · Moms och jurisdiktion",
        "Specialisterna delar samma skrivskyddade underlagsram och kan inte utöka behörigheterna.",
    ),
    "Propose": (
        "Föreslå",
        "Konteringsförslag · Avstämning",
        "Tar fram klassificeringar, matchningar och förklaringar utan att bokföra något.",
    ),
    "Verify": (
        "Verifiera",
        "Underlagsverifierare",
        "Kontrollerar proveniens, motsägelser, policyöverensstämmelse, fullständighet och reproducerbarhet.",
    ),
    "Decide": (
        "Besluta",
        "Mänsklig granskare",
        "Godkänner, avvisar, begär underlag eller stoppar ärendet. Agenter får aldrig självgodkänna.",
    ),
}


def _supplier_cases_from_manifest(
    fake_manifest: dict[str, Any],
    root: Path,
) -> list[dict[str, Any]]:
    supplier_manifest = fake_manifest.get("supplier_invoice_autopilot")
    if not isinstance(supplier_manifest, dict):
        return []
    summary = supplier_manifest.get("summary")
    if not isinstance(summary, dict):
        return []
    output_dir = _resolve_under_root(root, str(summary.get("output_dir") or ""))
    cases: list[dict[str, Any]] = []
    for item in supplier_manifest.get("cases", ()):
        if not isinstance(item, dict):
            continue
        artifacts = item.get("artifacts")
        packet_path = None
        packet = {}
        if isinstance(artifacts, dict):
            packet_path = _resolve_under_root(
                output_dir,
                str(artifacts.get("approval_packet_json") or ""),
            )
            packet = _read_json_object(packet_path)
        cases.append(
            {
                "summary": item,
                "packet": packet,
                "packet_path": packet_path,
            }
        )
    return cases


def _collect_review_items(
    *,
    supplier_cases: list[dict[str, Any]],
    bank_proposals: list[Any],
    fake_manifest: dict[str, Any],
    root: Path,
) -> dict[str, list[ReviewItem]]:
    queues: dict[str, list[ReviewItem]] = {
        "approval_required": [],
        "escalation_required": [],
        "forbidden": [],
        "missing_info": [],
        "risky_suppliers": [],
        "duplicate_risk": [],
        "changed_bank_details": [],
        "uncertain_vat": [],
        "policy_alignment_warnings": [],
    }

    for case in supplier_cases:
        summary = case["summary"]
        packet = case["packet"]
        case_id = str(summary.get("case_id") or _nested(packet, "case", "case_id") or "unknown")
        scenario = str(summary.get("scenario") or _nested(packet, "case", "fixture_name") or case_id)
        mode = str(summary.get("execution_gate_mode") or _nested(packet, "policy_decision", "mode") or "unknown")
        artifact = _rel_to_root(case.get("packet_path"), root)
        source = "supplier invoice"

        _append_by_mode(queues, mode, case_id, source, _mode_reason(packet, summary), artifact)

        flags = _risk_flag_codes(packet)
        supplier_status = str(_nested(packet, "supplier_match", "status") or "")
        bank_status = str(_nested(packet, "supplier_match", "bank_details_status") or "")
        duplicate_status = str(_nested(packet, "duplicate_check", "status") or "")
        vat_status = str(_nested(packet, "vat_proposal", "status") or "")
        if supplier_status and supplier_status != "matched":
            queues["risky_suppliers"].append(
                ReviewItem(case_id, source, mode, f"{scenario}: supplier status {supplier_status}", artifact)
            )
        if duplicate_status == "possible_duplicate" or any("duplicate" in flag for flag in flags):
            queues["duplicate_risk"].append(
                ReviewItem(case_id, source, mode, f"{scenario}: duplicate risk", artifact)
            )
        if bank_status == "changed" or "changed_bank_details" in flags:
            queues["changed_bank_details"].append(
                ReviewItem(case_id, source, mode, f"{scenario}: changed bank details", artifact)
            )
            if not any(item.item_id == case_id for item in queues["risky_suppliers"]):
                queues["risky_suppliers"].append(
                    ReviewItem(case_id, source, mode, f"{scenario}: payment details changed", artifact)
                )
        if vat_status and vat_status != "normal":
            queues["uncertain_vat"].append(
                ReviewItem(case_id, source, mode, f"{scenario}: VAT status {vat_status}", artifact)
            )
        if any("vat" in flag and flag not in {"normal_vat"} for flag in flags):
            _append_unique(
                queues["uncertain_vat"],
                ReviewItem(case_id, source, mode, f"{scenario}: VAT review flag", artifact),
            )
        if (
            str(summary.get("fortnox_adapter_payload_status") or "")
            == "not_prepared"
            or _nested(packet, "adapter_payload_error")
        ):
            queues["missing_info"].append(
                ReviewItem(case_id, source, mode, f"{scenario}: incomplete adapter-ready fields or blocked payload", artifact)
            )

    for proposal in bank_proposals:
        if not isinstance(proposal, dict):
            continue
        case_id = str(_nested(proposal, "case", "case_id") or "unknown_bank_case")
        mode = str(_nested(proposal, "policy_decision", "mode") or "unknown")
        artifact = _rel_to_root(proposal.get("approval_packet_path"), root)
        source = "bank reconciliation"
        _append_by_mode(
            queues,
            mode,
            case_id,
            source,
            str(proposal.get("required_human_decision") or "Review proposal."),
            artifact,
        )
        flags = {
            str(flag.get("code"))
            for flag in _nested(proposal, "risk", "flags", default=())
            if isinstance(flag, dict)
        }
        if flags & {"unknown_transaction", "unusual_transaction", "low_match_confidence"} or proposal.get("selected_candidate") is None:
            queues["missing_info"].append(
                ReviewItem(case_id, source, mode, "Classify transaction or supply better match evidence.", artifact)
            )
        if any("duplicate" in flag for flag in flags):
            queues["duplicate_risk"].append(
                ReviewItem(case_id, source, mode, "Possible duplicate bank transaction.", artifact)
            )
        if "changed_bank_details" in flags:
            queues["changed_bank_details"].append(
                ReviewItem(case_id, source, mode, "Matched supplier item indicates changed bank details.", artifact)
            )

    metrics = fake_manifest.get("metrics") if isinstance(fake_manifest, dict) else {}
    warnings = metrics.get("policy_alignment_warnings") if isinstance(metrics, dict) else ()
    for index, warning in enumerate(warnings or (), start=1):
        if not isinstance(warning, dict):
            continue
        item_id = str(warning.get("item_id") or f"policy_alignment_warning_{index}")
        reason = str(warning.get("reason") or "Policy alignment warning")
        queues["policy_alignment_warnings"].append(
            ReviewItem(item_id, "policy alignment", "warning", reason, None)
        )
    return queues


def _build_review_queues(review_items: dict[str, list[ReviewItem]]) -> tuple[ReviewQueue, ...]:
    labels = (
        ("approval_required", "Approval required"),
        ("escalation_required", "Escalation required"),
        ("forbidden", "Forbidden"),
        ("missing_info", "Missing info"),
        ("risky_suppliers", "Risky suppliers"),
        ("duplicate_risk", "Duplicate risk"),
        ("changed_bank_details", "Changed bank details"),
        ("uncertain_vat", "Uncertain VAT"),
        ("policy_alignment_warnings", "Policy alignment warnings"),
    )
    return tuple(
        ReviewQueue(
            key=key,
            label=label,
            count=len(review_items.get(key, ())),
            items=tuple(review_items.get(key, ())),
        )
        for key, label in labels
    )


def _append_by_mode(
    queues: dict[str, list[ReviewItem]],
    mode: str,
    item_id: str,
    source: str,
    reason: str,
    artifact_path: str | None,
) -> None:
    if mode in {"approval_required", "escalation_required", "forbidden"}:
        queues[mode].append(ReviewItem(item_id, source, mode, reason, artifact_path))


def _append_unique(items: list[ReviewItem], item: ReviewItem) -> None:
    if not any(existing.item_id == item.item_id and existing.source == item.source for existing in items):
        items.append(item)


def _mode_reason(packet: dict[str, Any], summary: dict[str, Any]) -> str:
    reasons = _nested(packet, "policy_decision", "openclaw_risk_reasons", default=())
    if isinstance(reasons, list | tuple) and reasons:
        return ", ".join(str(reason) for reason in reasons[:3])
    required = _nested(packet, "required_human_decision")
    if required:
        return str(required)
    return str(summary.get("scenario") or "Review required by local policy.")


def _collect_artifacts(root: Path, fake_root: Path, demo_root: Path) -> tuple[ArtifactLink, ...]:
    artifacts: list[ArtifactLink] = []
    for label, rel_path, kind, note in (
        ("Fake-client manifest", ".local/fake_client_dry_run/manifest.json", "manifest", "full synthetic month run"),
        ("Fake-client summary", ".local/fake_client_dry_run/summary.json", "summary", "counts and readiness"),
        ("Fake-client audit log", ".local/fake_client_dry_run/audit_log.jsonl", "audit log", "append-only local events"),
        ("Bank reconciliation proposals", ".local/fake_client_dry_run/bank_reconciliation_proposals.json", "bank proposals", "local proposal batch"),
        ("Supplier autopilot manifest", ".local/fake_client_dry_run/supplier_invoice_autopilot/manifest.json", "manifest", "supplier workflow output"),
        ("Supplier autopilot summary", ".local/fake_client_dry_run/supplier_invoice_autopilot/summary.json", "summary", "supplier workflow counts"),
        ("Local demo manifest", ".local/demo_supplier_invoice_autopilot/manifest.json", "manifest", "small fixture demo"),
        ("Local demo summary", ".local/demo_supplier_invoice_autopilot/summary.json", "summary", "small fixture counts"),
        ("Fake-client report", "docs/fake_client_dry_run_report.md", "report", "operator report"),
        ("Architecture doc", "docs/accounting_agent_architecture.md", "doc", "system boundaries"),
        ("Fortnox adapter doc", "docs/fortnox_adapter.md", "doc", "dry-run adapter boundary"),
        ("gnubok shadow ledger doc", "docs/gnubok_shadow_ledger.md", "doc", "shadow validation boundary"),
        ("Bank reconciliation doc", "docs/bank_reconciliation_autopilot.md", "doc", "bank proposal workflow"),
        ("Supplier autopilot doc", "docs/local_demo_supplier_invoice_autopilot.md", "doc", "local demo workflow"),
    ):
        artifacts.append(_artifact(root, rel_path, label, kind, note))

    group_specs = (
        (fake_root / "supplier_invoice_autopilot" / "approval_packets" / "json", "*.json", "Supplier approval packet", "approval packet"),
        (fake_root / "supplier_invoice_autopilot" / "approval_packets" / "markdown", "*.md", "Supplier review packet", "approval packet"),
        (fake_root / "supplier_invoice_autopilot" / "fortnox_dry_run_payloads", "*.json", "Fortnox dry-run payload", "dry-run payload"),
        (fake_root / "supplier_invoice_autopilot" / "gnubok_shadow_outputs", "*.json", "gnubok shadow output", "shadow output"),
        (fake_root / "bank_reconciliation_packets", "*.json", "Bank reconciliation packet", "approval packet"),
        (demo_root / "approval_packets" / "json", "*.json", "Demo approval packet", "approval packet"),
    )
    for folder, pattern, label_prefix, kind in group_specs:
        paths = sorted(folder.glob(pattern), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        for path in paths[:6]:
            rel_path = _rel_to_root(path, root)
            if rel_path:
                artifacts.append(
                    ArtifactLink(
                        label=f"{label_prefix}: {path.stem}",
                        path=rel_path,
                        kind=kind,
                        exists=True,
                        note="latest local file",
                    )
                )
    return tuple(artifacts)


def _artifact(root: Path, rel_path: str, label: str, kind: str, note: str) -> ArtifactLink:
    path = root / rel_path
    return ArtifactLink(
        label=label,
        path=rel_path,
        kind=kind,
        exists=path.exists(),
        note=note,
    )


def _read_queue_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {}
    tables = (
        "intake_cases",
        "documents",
        "extracted_fields",
        "accounting_proposals",
        "policy_decisions",
        "approval_packets",
        "audit_events",
    )
    try:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        available = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        counts: dict[str, int] = {}
        for table in tables:
            if table not in available:
                continue
            row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0])
        return counts
    except sqlite3.Error:
        return {}
    finally:
        connection.close()


def _live_counters(
    fake_manifest: dict[str, Any],
    demo_manifest: dict[str, Any],
) -> dict[str, int]:
    fake_safety = fake_manifest.get("safety") if isinstance(fake_manifest, dict) else {}
    demo_safety = demo_manifest.get("safety") if isinstance(demo_manifest, dict) else {}
    fake_safety = fake_safety if isinstance(fake_safety, dict) else {}
    demo_safety = demo_safety if isinstance(demo_safety, dict) else {}
    emails_payments_filings = (
        _as_int(fake_safety.get("emails_sent"))
        + _as_int(fake_safety.get("payments_or_filings"))
        + _as_int(fake_safety.get("final_voucher_postings"))
        + _as_int(demo_safety.get("emails_sent"))
        + _as_int(demo_safety.get("payments_or_filings"))
        + _as_int(demo_safety.get("final_bookkeeping"))
    )
    return {
        "live_fortnox_calls": _as_int(fake_safety.get("live_fortnox_calls"))
        + _as_int(demo_safety.get("live_fortnox_calls")),
        "live_microsoft365_calls": _as_int(fake_safety.get("live_microsoft365_calls"))
        + _as_int(demo_safety.get("live_microsoft365_calls")),
        "emails_payments_filings": emails_payments_filings,
    }


def _build_workflow(
    *,
    root: Path,
    fake_root: Path,
    demo_root: Path,
    fake_manifest: dict[str, Any],
    fake_summary: dict[str, Any],
    demo_manifest: dict[str, Any],
    demo_summary: dict[str, Any],
    bank_proposals: list[Any],
    supplier_cases: list[dict[str, Any]],
) -> tuple[WorkflowStep, ...]:
    del root, demo_root, demo_manifest
    supplier_root = fake_root / "supplier_invoice_autopilot"
    counts = {
        "intake": _count_json_list(supplier_root / "normalized_intake_cases.json"),
        "extraction": _count_files(supplier_root / "extracted_invoice_json", "*.json"),
        "accounting_proposal": _count_files(supplier_root / "accounting_proposals", "*.json"),
        "policy_gate": _count_files(supplier_root / "policy_decisions", "*.json"),
        "approval_packet": _count_files(supplier_root / "approval_packets" / "json", "*.json"),
        "execution_permit": _count_files(supplier_root / "execution_permits", "*.json"),
        "fortnox_dry_run": _count_files(supplier_root / "fortnox_dry_run_payloads", "*.json"),
        "gnubok_shadow_validation": _count_files(supplier_root / "gnubok_shadow_outputs", "*.json"),
        "bank_reconciliation": len(bank_proposals),
    }
    status_by_step = {
        "intake": _ready_status(counts["intake"]),
        "document_registry": _ready_status(_as_int(fake_summary.get("sample_counts", {}).get("supplier_invoices_or_receipts"))),
        "extraction": _ready_status(counts["extraction"]),
        "accounting_proposal": _ready_status(counts["accounting_proposal"]),
        "policy_gate": "review_required" if _review_total(fake_manifest) else _ready_status(counts["policy_gate"]),
        "approval_packet": _ready_status(counts["approval_packet"]),
        "execution_permit": "dry_run_only" if counts["execution_permit"] else "missing",
        "fortnox_dry_run": "dry_run_only" if counts["fortnox_dry_run"] else "missing",
        "gnubok_shadow_validation": _ready_status(counts["gnubok_shadow_validation"]),
        "bank_reconciliation": _ready_status(counts["bank_reconciliation"]),
        "audit_report": _ready_status(_as_int((fake_manifest.get("metrics") or {}).get("audit_events"))),
    }
    details = {
        "intake": f"{counts['intake']} normalized intake cases from synthetic local exports.",
        "document_registry": "Synthetic document registry and hashes are present in local SQLite/output artifacts.",
        "extraction": f"{counts['extraction']} extracted invoice JSON artifacts.",
        "accounting_proposal": f"{counts['accounting_proposal']} BAS/VAT accounting proposal artifacts.",
        "policy_gate": f"{_review_total(fake_manifest)} items need approval, escalation, or stop handling.",
        "approval_packet": f"{counts['approval_packet']} supplier approval packet JSON files.",
        "execution_permit": f"{counts['execution_permit']} local permit records; live use remains blocked.",
        "fortnox_dry_run": f"{counts['fortnox_dry_run']} Fortnox-shaped dry-run payload files; live calls are 0.",
        "gnubok_shadow_validation": f"{counts['gnubok_shadow_validation']} local shadow-ledger comparison files.",
        "bank_reconciliation": f"{counts['bank_reconciliation']} bank reconciliation proposals.",
        "audit_report": f"{_as_int((fake_manifest.get('metrics') or {}).get('audit_events'))} top-level audit events plus Markdown report.",
    }
    artifact_paths = {
        "intake": str(supplier_root / "normalized_intake_cases.json"),
        "document_registry": str(supplier_root / "demo.sqlite"),
        "extraction": str(supplier_root / "manifest.json"),
        "accounting_proposal": str(supplier_root / "summary.json"),
        "policy_gate": str(supplier_root / "manifest.json"),
        "approval_packet": str(supplier_root / "manifest.json"),
        "execution_permit": str(supplier_root / "manifest.json"),
        "fortnox_dry_run": str(supplier_root / "manifest.json"),
        "gnubok_shadow_validation": str(supplier_root / "manifest.json"),
        "bank_reconciliation": str(fake_root / "bank_reconciliation_proposals.json"),
        "audit_report": str(fake_root / "audit_log.jsonl"),
    }
    if not supplier_cases and demo_summary:
        details["approval_packet"] = f"{_as_int(demo_summary.get('approval_packets'))} demo approval packets."
    return tuple(
        WorkflowStep(
            key=key,
            label=label,
            status=status_by_step[key],
            detail=details[key],
            artifact_path=artifact_paths[key],
        )
        for key, label in WORKFLOW_STEPS
    )


def _collect_warnings(fake_manifest: dict[str, Any]) -> tuple[str, ...]:
    metrics = fake_manifest.get("metrics") if isinstance(fake_manifest, dict) else {}
    warnings = metrics.get("policy_alignment_warnings") if isinstance(metrics, dict) else ()
    collected = []
    for warning in warnings or ():
        if isinstance(warning, dict):
            item_id = warning.get("item_id") or "unknown item"
            reason = warning.get("reason") or "policy alignment warning"
            collected.append(f"{item_id}: {reason}")
    return tuple(collected)


def _last_run(
    fake_manifest_path: Path,
    fake_manifest: dict[str, Any],
    demo_manifest_path: Path,
    demo_manifest: dict[str, Any],
) -> str:
    candidates = []
    for path, manifest, keys in (
        (fake_manifest_path, fake_manifest, ("run", "generated_at")),
        (demo_manifest_path, demo_manifest, ("summary", "status")),
    ):
        generated = _nested(manifest, *keys)
        if generated and keys[-1] == "generated_at":
            candidates.append(str(generated))
        elif path.exists():
            candidates.append(_mtime_iso(path))
    return max(candidates) if candidates else "no local run found"


def _local_readiness(fake_manifest: dict[str, Any], fake_summary: dict[str, Any]) -> str:
    if _nested(fake_manifest, "run", "status") == "complete":
        return "local_fake_client_dry_run_complete"
    readiness = fake_summary.get("readiness") if isinstance(fake_summary, dict) else None
    if readiness:
        return str(readiness)
    return "not_ready_no_fake_client_run"


def _demo_readiness(demo_manifest: dict[str, Any], demo_summary: dict[str, Any]) -> str:
    if _nested(demo_manifest, "summary", "status") == "complete":
        return "supplier_invoice_demo_complete"
    if demo_summary.get("status") == "complete":
        return "supplier_invoice_demo_complete"
    return "not_ready_no_demo_run"


def _review_total(fake_manifest: dict[str, Any]) -> int:
    metrics = fake_manifest.get("metrics") if isinstance(fake_manifest, dict) else {}
    counts = metrics.get("primary_case_decision_counts") if isinstance(metrics, dict) else {}
    return sum(_as_int(counts.get(mode)) for mode in ("approval_required", "escalation_required", "forbidden"))


def _ready_status(count: int) -> str:
    return "available" if count else "missing"


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else {}


def _read_json_list(path: Path) -> list[Any]:
    payload = _read_json(path)
    return payload if isinstance(payload, list) else []


def _read_json(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _count_json_list(path: Path) -> int:
    payload = _read_json(path)
    return len(payload) if isinstance(payload, list) else 0


def _count_files(folder: Path, pattern: str) -> int:
    if not folder.exists():
        return 0
    return sum(1 for path in folder.glob(pattern) if path.is_file())


def _risk_flag_codes(packet: dict[str, Any]) -> set[str]:
    flags: set[str] = set()
    for section in ("risk",):
        for flag in _nested(packet, section, "flags", default=()):
            if isinstance(flag, dict) and flag.get("code"):
                flags.add(str(flag["code"]))
    for finding in packet.get("risk_findings", ()) if isinstance(packet, dict) else ():
        if isinstance(finding, dict):
            signal = finding.get("signal")
            if signal:
                flags.add(str(signal))
    return flags


def _nested(payload: Any, *keys: str, default: Any = None) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ensure_tokens_file(root: Path) -> None:
    target = root / DEFAULT_TOKENS_PATH
    if target.is_file():
        return
    if target.exists():
        raise FileExistsError(f"Required stylesheet path is not a file: {target.name}")
    source = resources.files("accounting_agent").joinpath("static", "tokens.css")
    if not source.is_file():
        raise FileNotFoundError("Required packaged stylesheet not found: accounting_agent/static/tokens.css")
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _ensure_icon_file(root: Path) -> None:
    target = root / DEFAULT_ICON_PATH
    if target.is_file():
        return
    if target.exists():
        raise FileExistsError(f"Required icon path is not a file: {target.name}")
    source = resources.files("accounting_agent").joinpath("static", "favicon.svg")
    if not source.is_file():
        raise FileNotFoundError("Required packaged icon not found: accounting_agent/static/favicon.svg")
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _resolve_under_root(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not _is_relative_to(resolved, root):
        raise ValueError(f"Path must stay under repo root: {path}")
    return resolved


def _rel_to_root(path: str | Path | None, root: Path) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not _is_relative_to(resolved, root):
        return None
    return resolved.relative_to(root).as_posix()


def _optional_link(
    path: str | None,
    root: Path,
    output: Path,
    label: str,
    label_sv: str | None = None,
) -> str:
    if not path:
        return ""
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    if not target.exists() or not _is_relative_to(target.resolve(), root):
        return ""
    i18n = f" {_i18n_attrs(label, label_sv)}" if label_sv else ""
    return f'<a href="{_href(target, output)}"{i18n}>{_e(label)}</a>'


def _href(target: Path, output: Path) -> str:
    rel = os.path.relpath(target.resolve(), output.parent.resolve())
    return quote(Path(rel).as_posix(), safe="/._-~")


def _extract_hrefs(markup: str) -> list[str]:
    return re.findall(r'href="([^"]+)"', markup)


def _looks_external(href: str) -> bool:
    return href.startswith(("http://", "https://", "//", "data:", "javascript:"))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()


def _display_time(value: str) -> str:
    if not value or value == "no local run found":
        return "No local run found"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value.replace("_", " ")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _i18n_attrs(english: str, swedish: str) -> str:
    return f'data-i18n data-en="{_e(english)}" data-sv="{_e(swedish)}"'


_ARTIFACT_KIND_SV = {
    "approval packet": "Godkännandepaket",
    "audit log": "Revisionslogg",
    "bank proposals": "Bankförslag",
    "doc": "Dokument",
    "dry-run payload": "Torrkörningsdata",
    "manifest": "Manifest",
    "report": "Rapport",
    "shadow output": "Skuggvalidering",
    "summary": "Sammanfattning",
}


_CSS = """
/* Hallmark · macrostructure: Workbench · tone: calm precise operational · anchor hue: cobalt */
/* Hallmark · pre-emit critique: P4 H5 E4 S5 R4 V4 · contrast: pass (40–41) · nav: N13 · footer: Ft2 · slop: pass (42–45) · honest: pass (46) · chrome: pass (47) · tokens: pass (48) · responsive: pass (49) · icons: pass (30) · mobile: pass (34, 49, 50–57) */
* { box-sizing: border-box; }
html { min-width: 0; overflow-x: clip; scroll-behavior: smooth; }
body {
  min-width: 0;
  overflow-x: clip;
  margin: 0;
  background: var(--color-canvas);
  color: var(--color-ink);
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: 1.55;
}
body[data-view="guided"] .expert-only { display: none; }
button, input, select { font: inherit; }
button, select, input { min-height: 2.75rem; }
button, select, input, summary, a {
  outline: var(--rule-heavy) solid transparent;
  outline-offset: var(--rule-thin);
  -webkit-tap-highlight-color: var(--color-transparent);
}
button { cursor: pointer; }
button:disabled, input:disabled, select:disabled { cursor: not-allowed; opacity: 0.55; }
a {
  color: var(--color-accent-strong);
  text-decoration-thickness: var(--rule-thin);
  text-underline-offset: var(--rule-heavy);
}
a:hover { text-decoration-thickness: var(--rule-heavy); }
a:active, button:active { transform: translateY(var(--rule-thin)); }
:focus-visible {
  outline: var(--rule-heavy) solid var(--color-focus);
  outline-offset: var(--rule-thin);
}
[hidden] { display: none !important; }
h1, h2, h3 { min-width: 0; overflow-wrap: anywhere; }
code, kbd {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  overflow-wrap: anywhere;
}
code {
  padding: var(--space-2xs) var(--space-xs);
  border: var(--rule-thin) solid var(--color-line);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}
kbd {
  padding: var(--space-2xs) var(--space-xs);
  border: var(--rule-thin) solid var(--color-line-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-ink-muted);
  white-space: nowrap;
}
.shell {
  width: min(calc(100% - var(--space-2xl)), 76rem);
  margin-inline: auto;
}
.skip-link {
  position: fixed;
  inset-block-start: var(--space-sm);
  inset-inline-start: var(--space-sm);
  z-index: 20;
  padding: var(--space-sm) var(--space-md);
  transform: translateY(-200%);
  border-radius: var(--radius-sm);
  background: var(--color-accent-strong);
  color: var(--color-accent-ink);
}
.skip-link:focus { transform: translateY(0); }
.environment-strip {
  position: sticky;
  inset-block-start: 0;
  z-index: 10;
  border-block-end: var(--rule-thin) solid var(--color-line-strong);
  background: var(--color-ink);
  color: var(--color-surface);
}
.environment-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs) var(--space-md);
  min-height: 2.75rem;
  padding-block: var(--space-xs);
  font-size: var(--text-xs);
}
.environment-inner span { color: var(--color-surface-strong); }
.environment-inner span::before {
  content: "·";
  margin-inline-end: var(--space-md);
  color: var(--color-line-strong);
}
.environment-inner .boundary-state { color: var(--color-warning-soft); font-weight: 700; }
.app-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(20rem, 0.78fr);
  gap: var(--space-lg) var(--space-2xl);
  padding-block: var(--space-xl) var(--space-2xl);
  border-block-end: var(--rule-thin) solid var(--color-line);
}
.header-copy h1 {
  max-width: 16ch;
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  line-height: 1.08;
  letter-spacing: -0.025em;
}
.header-copy p {
  max-width: 68ch;
  margin: var(--space-md) 0 0;
  color: var(--color-ink-muted);
  font-size: var(--text-lg);
}
.header-tools {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-sm);
  align-content: start;
}
.command-trigger {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  border: var(--rule-thin) solid var(--color-line-strong);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  color: var(--color-ink);
  text-align: start;
  transition: transform var(--dur-fast) var(--ease-out);
}
.command-trigger:hover { transform: translateY(calc(var(--rule-thin) * -1)); }
.command-trigger:disabled:hover { transform: none; }
.field-control, .search-field {
  display: grid;
  gap: var(--space-2xs);
  min-width: 0;
  color: var(--color-ink-muted);
  font-size: var(--text-xs);
  font-weight: 700;
}
select, input[type="search"] {
  width: 100%;
  min-width: 0;
  padding: var(--space-xs) var(--space-sm);
  border: var(--rule-thin) solid var(--color-line-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: var(--color-ink);
}
select:hover, input[type="search"]:hover { border-color: var(--color-accent); }
select:active, input[type="search"]:active { border-color: var(--color-accent-strong); }
input[type="search"]::placeholder { color: var(--color-ink-muted); }
.view-toggle {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--space-2xs);
  margin: 0;
  padding: var(--space-2xs);
  border: var(--rule-thin) solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-surface-muted);
}
.view-toggle legend { position: absolute; width: var(--rule-thin); height: var(--rule-thin); overflow: hidden; clip-path: inset(50%); }
.view-toggle label { position: relative; cursor: pointer; }
.view-toggle input { position: absolute; inline-size: var(--rule-thin); block-size: var(--rule-thin); opacity: 0; }
.view-toggle span {
  display: grid;
  min-height: 2.25rem;
  place-items: center;
  border-radius: var(--radius-sm);
  color: var(--color-ink-muted);
  font-size: var(--text-sm);
  font-weight: 700;
}
.view-toggle input:checked + span { background: var(--color-surface); color: var(--color-accent-strong); }
.view-toggle input:focus-visible + span { outline: var(--rule-heavy) solid var(--color-focus); outline-offset: var(--rule-thin); }
.role-guidance, .role-boundary {
  grid-column: 2;
  margin: 0;
  color: var(--color-ink-muted);
  font-size: var(--text-sm);
}
.role-boundary { font-size: var(--text-xs); }
.generation-stamp {
  grid-column: 1;
  grid-row: 2;
  margin: 0;
  align-self: end;
  color: var(--color-ink-muted);
  font-size: var(--text-xs);
}
.section-nav { border-block-end: var(--rule-thin) solid var(--color-line); background: var(--color-surface); }
.section-nav-inner { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2xs) var(--space-lg); padding-block: var(--space-sm); }
.section-nav a { min-inline-size: 2.75rem; min-height: 2.75rem; display: inline-flex; align-items: center; color: var(--color-ink-muted); font-size: var(--text-sm); font-weight: 700; text-decoration: none; white-space: nowrap; }
.section-nav a:hover { color: var(--color-accent-strong); text-decoration: underline; }
main.shell { padding-block: var(--space-sm) var(--space-3xl); }
.workbench-section {
  scroll-margin-block-start: var(--space-3xl);
  padding-block: var(--space-2xl);
  border-block-end: var(--rule-thin) solid var(--color-line);
}
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: end;
  gap: var(--space-lg);
  margin-block-end: var(--space-lg);
}
.section-heading h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-xl);
  line-height: 1.2;
}
.section-heading p, .subsection-heading p { max-width: 72ch; margin: var(--space-xs) 0 0; color: var(--color-ink-muted); }
.section-heading .last-run, .section-heading .result-count { margin: 0; color: var(--color-ink-muted); font-size: var(--text-sm); white-space: nowrap; }
.stat-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  margin: 0;
  border-block: var(--rule-thin) solid var(--color-line);
}
.stat {
  min-width: 0;
  padding: var(--space-md);
  border-inline-end: var(--rule-thin) solid var(--color-line);
}
.stat:last-child { border-inline-end: 0; }
.stat dt { color: var(--color-ink-muted); font-size: var(--text-xs); font-weight: 700; }
.stat dd { margin: var(--space-sm) 0 var(--space-2xs); font-family: var(--font-display); font-size: var(--text-lg); font-weight: 700; overflow-wrap: anywhere; }
.stat span { display: block; color: var(--color-ink-muted); font-size: var(--text-xs); }
.stat[data-tone="safe"] dd { color: var(--color-safe); }
.stat[data-tone="warning"] dd { color: var(--color-warning); }
.stat[data-tone="danger"] dd { color: var(--color-danger); }
.boundary-notice {
  display: grid;
  grid-template-columns: minmax(10rem, 0.32fr) minmax(0, 1fr);
  gap: var(--space-md);
  margin-block-start: var(--space-lg);
  padding: var(--space-md);
  border: var(--rule-thin) solid var(--color-line-strong);
  background: var(--color-surface-muted);
}
.boundary-notice[data-tone="danger"] { border-color: var(--color-danger); background: var(--color-danger-soft); }
.boundary-notice[data-tone="warning"] { border-color: var(--color-warning); background: var(--color-warning-soft); }
.boundary-notice[data-tone="neutral"] { border-color: var(--color-accent); background: var(--color-accent-soft); }
.boundary-notice ul { grid-column: 1 / -1; margin: 0; padding-inline-start: var(--space-lg); }
.local-counts, .artifact-group, .operator-actions {
  margin-block-start: var(--space-lg);
  border: var(--rule-thin) solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
summary {
  min-height: 2.75rem;
  padding: var(--space-sm) var(--space-md);
  cursor: pointer;
  font-weight: 700;
}
summary:hover { background: var(--color-surface-muted); }
summary:active { background: var(--color-surface-strong); }
details[aria-disabled="true"] summary { cursor: not-allowed; opacity: 0.55; }
.ledger-counts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-xs); margin: 0; padding: 0 var(--space-md) var(--space-md); }
.ledger-counts div { display: flex; justify-content: space-between; gap: var(--space-xs); padding: var(--space-xs); border-block-start: var(--rule-thin) solid var(--color-line); }
.ledger-counts dt { color: var(--color-ink-muted); }
.ledger-counts dd { margin: 0; font-weight: 700; }
.review-filters { display: grid; grid-template-columns: minmax(0, 1fr) minmax(10rem, 0.25fr); gap: var(--space-md); margin-block-end: var(--space-md); }
.attention-list { margin: 0; padding: 0; list-style: none; border-block-start: var(--rule-thin) solid var(--color-line); }
.attention-row {
  display: grid;
  grid-template-columns: minmax(9rem, 0.26fr) minmax(0, 1fr) minmax(8rem, auto);
  gap: var(--space-lg);
  padding-block: var(--space-lg);
  border-block-end: var(--rule-thin) solid var(--color-line);
}
.attention-priority { display: flex; flex-direction: column; align-items: flex-start; gap: var(--space-xs); color: var(--color-ink-muted); font-size: var(--text-sm); }
.severity { display: inline-flex; min-height: 1.5rem; align-items: center; padding-inline: var(--space-xs); border-block-end: var(--rule-heavy) solid var(--color-line-strong); font-size: var(--text-xs); font-weight: 800; text-transform: uppercase; }
.severity[data-severity="critical"] { border-color: var(--color-danger); color: var(--color-danger); }
.severity[data-severity="high"] { border-color: var(--color-warning); color: var(--color-warning); }
.severity[data-severity="medium"] { border-color: var(--color-accent); color: var(--color-accent-strong); }
.severity[data-severity="low"] { border-color: var(--color-line-strong); color: var(--color-ink-muted); }
.attention-copy h3 { margin: 0; font-family: var(--font-display); font-size: var(--text-base); }
.attention-copy p { margin: var(--space-xs) 0 0; color: var(--color-ink-muted); }
.attention-copy details { margin-block-start: var(--space-xs); }
.attention-copy details summary { min-height: 2rem; padding: var(--space-2xs) 0; color: var(--color-accent-strong); font-size: var(--text-sm); }
.technical-context { display: grid; gap: var(--space-xs); margin: var(--space-xs) 0 0; }
.technical-context div { display: grid; grid-template-columns: 7rem minmax(0, 1fr); gap: var(--space-sm); }
.technical-context dt { color: var(--color-ink-muted); }
.technical-context dd { margin: 0; overflow-wrap: anywhere; }
.attention-action { align-self: center; text-align: end; font-size: var(--text-sm); }
.attention-action a, .step-meta a, .artifact-open { display: inline-flex; min-height: 2.75rem; align-items: center; white-space: nowrap; }
.attention-action span { color: var(--color-ink-muted); }
.empty-state { margin: 0; padding: var(--space-xl); border: var(--rule-thin) dashed var(--color-line-strong); color: var(--color-ink-muted); text-align: center; }
.workflow-sequence, .agent-pipeline { margin: 0; padding: 0; list-style: none; }
.workflow-step {
  display: grid;
  grid-template-columns: 3rem minmax(0, 1fr) minmax(9rem, auto);
  gap: var(--space-md);
  align-items: start;
  padding-block: var(--space-md);
  border-block-start: var(--rule-thin) solid var(--color-line);
}
.workflow-step:last-child { border-block-end: var(--rule-thin) solid var(--color-line); }
.step-number { color: var(--color-ink-muted); font-variant-numeric: tabular-nums; }
.workflow-step h3, .agent-pipeline h3 { margin: 0; font-size: var(--text-base); }
.workflow-step p, .agent-pipeline p { margin: var(--space-2xs) 0 0; color: var(--color-ink-muted); }
.step-meta { display: flex; justify-content: flex-end; align-items: center; flex-wrap: wrap; gap: var(--space-sm); color: var(--color-ink-muted); font-size: var(--text-sm); text-align: end; }
.workflow-step[data-state="review_required"] .step-meta, .workflow-step[data-state="dry_run_only"] .step-meta { color: var(--color-warning); }
.workflow-step[data-state="missing"] .step-meta { color: var(--color-danger); }
.workflow-step[data-state="available"] .step-meta { color: var(--color-safe); }
.subsection-heading { margin-block: var(--space-2xl) var(--space-md); }
.subsection-heading h3 { margin: 0; font-family: var(--font-display); font-size: var(--text-lg); }
.agent-pipeline > li {
  display: grid;
  grid-template-columns: minmax(11rem, 0.32fr) minmax(0, 1fr);
  gap: var(--space-lg);
  padding-block: var(--space-md);
  border-block-start: var(--rule-thin) solid var(--color-line);
}
.agent-pipeline > li:last-child { border-block-end: var(--rule-thin) solid var(--color-line); }
.agent-stage { display: flex; gap: var(--space-sm); align-items: baseline; }
.agent-stage span { color: var(--color-accent); font-size: var(--text-xs); font-variant-numeric: tabular-nums; }
.table-frame { width: 100%; }
.integration-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.integration-table caption { padding-block-end: var(--space-sm); color: var(--color-ink-muted); font-size: var(--text-sm); text-align: start; }
.integration-table th, .integration-table td { padding: var(--space-sm); border-block-start: var(--rule-thin) solid var(--color-line); vertical-align: top; text-align: start; overflow-wrap: anywhere; }
.integration-table thead th { color: var(--color-ink-muted); font-size: var(--text-xs); }
.integration-table tbody th { font-family: var(--font-display); }
.integration-table th:nth-child(1) { width: 14%; }
.integration-table th:nth-child(2) { width: 14%; }
.integration-table th:nth-child(3) { width: 16%; }
.integration-table th:nth-child(4) { width: 27%; }
.integration-table th:nth-child(5) { width: 29%; }
.safety-boundaries { margin-block-start: var(--space-md); }
.boundary-columns, .action-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-xl); margin-block-start: var(--space-lg); }
.boundary-columns h3, .action-columns h3 { margin: 0; font-family: var(--font-display); font-size: var(--text-base); }
.boundary-list, .command-list { margin: var(--space-sm) 0 0; padding-inline-start: var(--space-lg); }
.boundary-list li, .command-list li { margin-block: var(--space-xs); }
.allowed li::marker { color: var(--color-safe); }
.blocked li::marker { color: var(--color-danger); }
.artifact-groups { display: grid; gap: var(--space-sm); }
.artifact-group { margin: 0; }
.artifact-group summary { display: flex; justify-content: space-between; gap: var(--space-md); }
.artifact-group summary span:last-child { color: var(--color-ink-muted); font-size: var(--text-sm); font-weight: 500; }
.artifact-list { margin: 0; padding: 0 var(--space-md) var(--space-md); list-style: none; }
.artifact-list li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-md); padding-block: var(--space-sm); border-block-start: var(--rule-thin) solid var(--color-line); }
.artifact-list li div { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: var(--space-2xs) var(--space-md); min-width: 0; overflow-wrap: anywhere; }
.artifact-list li .artifact-label { min-width: 0; }
.artifact-list li .artifact-note { grid-column: 1 / -1; display: block; color: var(--color-ink-muted); font-size: var(--text-xs); }
.artifact-list li strong { color: var(--color-safe); font-size: var(--text-xs); }
.artifact-list li[data-state="missing"] strong { color: var(--color-warning); }
.operator-actions { margin: 0; }
.command-list code { display: inline-block; max-width: 100%; }
.site-footer { padding-block: var(--space-lg) var(--space-2xl); color: var(--color-ink-muted); font-size: var(--text-xs); }
.footer-line { display: flex; align-items: center; justify-content: space-between; gap: var(--space-lg); padding-block-start: var(--space-md); border-block-start: var(--rule-thin) solid var(--color-line-strong); }
.footer-line p { margin: 0; }
.command-dialog {
  width: min(calc(100% - var(--space-xl)), 40rem);
  max-height: min(80dvh, 42rem);
  padding: 0;
  border: var(--rule-thin) solid var(--color-line-strong);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  color: var(--color-ink);
  box-shadow: var(--shadow-dialog);
}
.command-dialog::backdrop { background: var(--color-scrim); }
.command-shell { padding: var(--space-md); }
.command-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); }
.command-head h2 { margin: 0; font-family: var(--font-display); font-size: var(--text-lg); }
.dialog-close, .secondary-button { min-height: 2.75rem; padding: var(--space-xs) var(--space-sm); border: var(--rule-thin) solid var(--color-line); border-radius: var(--radius-sm); background: var(--color-surface); color: var(--color-ink); font-size: var(--text-sm); line-height: 1.2; }
.dialog-close:hover, .secondary-button:hover { background: var(--color-surface-muted); }
.dialog-close:active, .secondary-button:active { background: var(--color-surface-strong); }
.review-empty { align-items: center; justify-content: space-between; gap: var(--space-md); text-align: start; }
.review-empty:not([hidden]) { display: flex; }
.command-search { margin-block: var(--space-md); }
.command-listbox { max-height: 24rem; margin: 0; padding: 0; overflow-y: auto; list-style: none; border-block-start: var(--rule-thin) solid var(--color-line); }
.command-listbox li { border-block-end: var(--rule-thin) solid var(--color-line); }
.command-listbox a { display: grid; gap: var(--space-2xs); min-height: 3.25rem; padding: var(--space-sm); color: var(--color-ink); text-decoration: none; }
.command-listbox a:hover, .command-listbox a[data-active="true"] { background: var(--color-accent-soft); }
.command-listbox a span { color: var(--color-ink-muted); font-size: var(--text-sm); }
.command-hint { margin: var(--space-sm) 0 0; color: var(--color-ink-muted); font-size: var(--text-xs); }
.sr-only { position: absolute; width: var(--rule-thin); height: var(--rule-thin); overflow: hidden; clip-path: inset(50%); }
@media (max-width: 64rem) {
  .app-header { grid-template-columns: minmax(0, 1fr); }
  .role-guidance, .role-boundary, .generation-stamp { grid-column: 1; grid-row: auto; }
  .stat-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .stat:nth-child(3) { border-inline-end: 0; }
  .stat:nth-child(-n + 3) { border-block-end: var(--rule-thin) solid var(--color-line); }
}
@media (max-width: 48rem) {
  .shell { width: min(calc(100% - var(--space-lg)), 76rem); }
  .section-heading, .boundary-notice, .boundary-columns, .action-columns, .agent-pipeline > li { grid-template-columns: minmax(0, 1fr); display: grid; align-items: start; }
  .section-heading .last-run, .section-heading .result-count { white-space: normal; }
  .review-filters { grid-template-columns: minmax(0, 1fr); }
  .attention-row { grid-template-columns: minmax(0, 1fr); gap: var(--space-sm); }
  .attention-priority { flex-direction: row; align-items: center; }
  .attention-action { text-align: start; }
  .workflow-step { grid-template-columns: 2.5rem minmax(0, 1fr); }
  .workflow-step .step-meta { grid-column: 2; justify-content: flex-start; text-align: start; }
  .integration-table, .integration-table thead, .integration-table tbody, .integration-table tr, .integration-table th, .integration-table td { display: block; width: 100%; }
  .integration-table thead { position: absolute; width: var(--rule-thin); height: var(--rule-thin); overflow: hidden; clip-path: inset(50%); }
  .integration-table tbody tr { padding-block: var(--space-md); border-block-start: var(--rule-thin) solid var(--color-line-strong); }
  .integration-table tbody th { padding: 0 0 var(--space-xs); border: 0; }
  .integration-table tbody td { display: grid; grid-template-columns: 7rem minmax(0, 1fr); gap: var(--space-sm); padding: var(--space-xs) 0; border: 0; }
  .integration-table tbody td::before { content: attr(data-label); color: var(--color-ink-muted); font-size: var(--text-xs); font-weight: 700; }
  .footer-line { flex-direction: column; gap: var(--space-xs); }
}
@media (max-width: 30rem) {
  .environment-inner { gap: var(--space-2xs) var(--space-xs); }
  .environment-inner span::before { margin-inline-end: var(--space-xs); }
  .app-header { padding-block: var(--space-md) var(--space-lg); }
  .header-tools { grid-template-columns: minmax(0, 1fr); }
  .command-trigger, .view-toggle { grid-column: 1; }
  .stat-strip { grid-template-columns: minmax(0, 1fr); }
  .stat { border-inline-end: 0; border-block-end: var(--rule-thin) solid var(--color-line); }
  .stat:last-child { border-block-end: 0; }
  .section-nav-inner { gap: var(--space-2xs) var(--space-md); }
  .technical-context div, .integration-table tbody td { grid-template-columns: minmax(0, 1fr); }
  .artifact-group summary, .artifact-list li { grid-template-columns: minmax(0, 1fr); display: grid; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .command-trigger:hover, a:active, button:active { transform: none; }
}
@media (pointer: coarse) {
  a, button, select, input, summary, .view-toggle span { min-height: 2.75rem; }
}
@media (forced-colors: active) {
  :focus-visible { outline-color: var(--color-forced-focus); }
  .environment-strip, .boundary-notice, .severity, .stat, .workflow-step, .agent-pipeline > li { forced-color-adjust: auto; border-color: var(--color-forced-text); }
  .command-dialog { background: var(--color-forced-canvas); color: var(--color-forced-text); }
}
@media print {
  .environment-strip, .section-nav, .header-tools, .review-filters, .command-dialog, .skip-link { display: none !important; }
  body { background: var(--color-surface); }
  .shell { width: 100%; }
  .app-header, .workbench-section { break-inside: avoid; padding-block: var(--space-md); }
  .expert-only { display: block !important; }
  a { color: var(--color-ink); text-decoration: none; }
}
""".strip()


_SCRIPT = r"""
(() => {
  const body = document.body;
  const localeSelect = document.querySelector("#locale-select");
  const roleSelect = document.querySelector("#role-select");
  const roleGuidance = document.querySelector("#role-guidance");
  const commandShortcut = document.querySelector("#command-shortcut");
  const viewInputs = [...document.querySelectorAll('input[name="view"]')];

  const guidance = {
    "en-GB": {
      "small-firm": "Queue-first guidance with plain-language evidence and explicit human decisions.",
      "accountant": "Transaction-focused guidance with evidence, accounting proposals, and review reasons.",
      "senior": "Escalation-focused guidance with policy conflicts, complex VAT, and approval boundaries.",
      "controller": "Control-focused guidance with reconciliation, completeness, period, and variance evidence.",
      "auditor": "Evidence-first guidance with provenance, policy history, exceptions, and reproducible artifacts.",
      "operator": "Technical guidance with raw identifiers, capability states, local commands, and agent boundaries."
    },
    "sv-SE": {
      "small-firm": "Köfokuserad vägledning med tydliga underlag och uttryckliga mänskliga beslut.",
      "accountant": "Transaktionsfokuserad vägledning med underlag, konteringsförslag och granskningsorsaker.",
      "senior": "Eskaleringsfokuserad vägledning för policykonflikter, komplex moms och attestgränser.",
      "controller": "Kontrollfokuserad vägledning för avstämning, fullständighet, period och avvikelser.",
      "auditor": "Underlagsfokuserad vägledning med spårbarhet, policyhistorik, undantag och reproducerbara filer.",
      "operator": "Teknisk vägledning med råa ID:n, behörighetslägen, lokala kommandon och agentgränser."
    }
  };

  const readPreference = (key, fallback) => {
    try { return window.localStorage.getItem(key) || fallback; }
    catch (_) { return fallback; }
  };
  const writePreference = (key, value) => {
    try { window.localStorage.setItem(key, value); }
    catch (_) { /* Preferences remain session-only when storage is unavailable. */ }
  };

  const updateRoleGuidance = () => {
    if (!roleGuidance || !roleSelect || !localeSelect) return;
    const locale = guidance[localeSelect.value] ? localeSelect.value : "en-GB";
    roleGuidance.textContent = guidance[locale][roleSelect.value] || guidance[locale]["small-firm"];
  };

  const applyLocale = (locale) => {
    const resolved = locale === "sv-SE" ? "sv-SE" : "en-GB";
    document.documentElement.lang = resolved;
    body.dataset.locale = resolved;
    if (localeSelect) localeSelect.value = resolved;
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const text = resolved === "sv-SE" ? node.dataset.sv : node.dataset.en;
      if (text) node.textContent = text;
    });
    document.querySelectorAll("[data-placeholder-en]").forEach((node) => {
      node.setAttribute("placeholder", resolved === "sv-SE" ? node.dataset.placeholderSv : node.dataset.placeholderEn);
    });
    document.querySelectorAll("[data-aria-label-en]").forEach((node) => {
      node.setAttribute("aria-label", resolved === "sv-SE" ? node.dataset.ariaLabelSv : node.dataset.ariaLabelEn);
    });
    document.querySelectorAll("[data-label-en]").forEach((node) => {
      node.dataset.label = resolved === "sv-SE" ? node.dataset.labelSv : node.dataset.labelEn;
    });
    const dateFormatter = new Intl.DateTimeFormat(resolved, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "Europe/Stockholm"
    });
    document.querySelectorAll("time[datetime]").forEach((node) => {
      const parsed = new Date(node.getAttribute("datetime"));
      if (!Number.isNaN(parsed.getTime())) node.textContent = dateFormatter.format(parsed);
    });
    updateRoleGuidance();
    updateReviewResults();
  };

  const initialView = readPreference("accounting-cockpit-view", "guided");
  body.dataset.view = initialView === "expert" ? "expert" : "guided";
  viewInputs.forEach((input) => {
    input.checked = input.value === body.dataset.view;
    input.addEventListener("change", () => {
      if (!input.checked) return;
      body.dataset.view = input.value;
      writePreference("accounting-cockpit-view", input.value);
    });
  });

  if (roleSelect) {
    const savedRole = readPreference("accounting-cockpit-role", "small-firm");
    if ([...roleSelect.options].some((option) => option.value === savedRole)) roleSelect.value = savedRole;
    body.dataset.role = roleSelect.value;
    roleSelect.addEventListener("change", () => {
      writePreference("accounting-cockpit-role", roleSelect.value);
      body.dataset.role = roleSelect.value;
      updateRoleGuidance();
    });
  }
  if (localeSelect) {
    localeSelect.addEventListener("change", () => {
      writePreference("accounting-cockpit-locale", localeSelect.value);
      applyLocale(localeSelect.value);
    });
  }

  const reviewSearch = document.querySelector("#review-search");
  const reviewSeverity = document.querySelector("#review-severity");
  const reviewRows = [...document.querySelectorAll(".attention-row")];
  const reviewResultCount = document.querySelector("#review-result-count");
  const reviewEmpty = document.querySelector("#review-empty");
  const clearReviewFilters = document.querySelector("#clear-review-filters");
  function updateReviewResults() {
    if (!reviewResultCount) return;
    const query = reviewSearch ? reviewSearch.value.trim().toLocaleLowerCase() : "";
    const severity = reviewSeverity ? reviewSeverity.value : "all";
    let visible = 0;
    reviewRows.forEach((row) => {
      const matchesQuery = !query || row.dataset.search.includes(query);
      const matchesSeverity = severity === "all" || row.dataset.severity === severity;
      row.hidden = !(matchesQuery && matchesSeverity);
      if (!row.hidden) visible += 1;
    });
    const isSwedish = localeSelect && localeSelect.value === "sv-SE";
    reviewResultCount.textContent = isSwedish ? `${visible} poster visas` : `${visible} items shown`;
    if (reviewEmpty) reviewEmpty.hidden = visible !== 0;
  }
  reviewSearch?.addEventListener("input", updateReviewResults);
  reviewSeverity?.addEventListener("change", updateReviewResults);
  clearReviewFilters?.addEventListener("click", () => {
    if (reviewSearch) reviewSearch.value = "";
    if (reviewSeverity) reviewSeverity.value = "all";
    updateReviewResults();
    reviewSearch?.focus();
  });

  const trigger = document.querySelector("#command-trigger");
  const dialog = document.querySelector("#command-dialog");
  const commandSearch = document.querySelector("#command-search");
  const commandItems = [...document.querySelectorAll("#command-list li")];
  let activeIndex = 0;
  if (commandShortcut) commandShortcut.textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ K" : "Ctrl K";

  const visibleCommandLinks = () => commandItems
    .filter((item) => !item.hidden)
    .map((item) => item.querySelector("a"));
  const setActiveCommand = (index) => {
    const links = visibleCommandLinks();
    if (!links.length) return;
    activeIndex = (index + links.length) % links.length;
    links.forEach((link, itemIndex) => link.dataset.active = String(itemIndex === activeIndex));
    links[activeIndex].focus();
  };
  const filterCommands = () => {
    const query = commandSearch ? commandSearch.value.trim().toLocaleLowerCase() : "";
    commandItems.forEach((item) => item.hidden = Boolean(query) && !item.textContent.toLocaleLowerCase().includes(query));
    activeIndex = 0;
    visibleCommandLinks().forEach((link, index) => link.dataset.active = String(index === 0));
  };
  const openCommands = () => {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    if (commandSearch) {
      commandSearch.value = "";
      filterCommands();
      commandSearch.focus();
    }
  };
  const closeCommands = () => {
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  };

  trigger?.addEventListener("click", openCommands);
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "k") {
      event.preventDefault();
      openCommands();
      return;
    }
    if (!dialog?.open || !["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    setActiveCommand(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
  });
  commandSearch?.addEventListener("input", filterCommands);
  commandSearch?.addEventListener("keydown", (event) => {
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      event.stopPropagation();
      setActiveCommand(event.key === "ArrowDown" ? 0 : visibleCommandLinks().length - 1);
      return;
    }
    if (event.key === "Enter") {
      const firstLink = visibleCommandLinks()[0];
      if (!firstLink) return;
      event.preventDefault();
      firstLink.click();
    }
  });
  commandItems.forEach((item) => item.querySelector("a")?.addEventListener("click", closeCommands));
  dialog?.addEventListener("click", (event) => { if (event.target === dialog) closeCommands(); });
  dialog?.addEventListener("close", () => trigger?.focus());

  applyLocale(readPreference("accounting-cockpit-locale", "en-GB"));
  updateRoleGuidance();
  updateReviewResults();
})();
""".strip()
