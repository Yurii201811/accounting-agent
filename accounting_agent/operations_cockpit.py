from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


DEFAULT_OUTPUT_PATH = Path("reports/operations_cockpit/index.html")
DEFAULT_FAKE_CLIENT_OUTPUT = Path(".local/fake_client_dry_run")
DEFAULT_DEMO_OUTPUT = Path(".local/demo_supplier_invoice_autopilot")
DEFAULT_DB_PATH = Path(".local/accounting_agent.sqlite")

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
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>Accounting Agent Operations Cockpit</title>",
            "<style>",
            _CSS,
            "</style>",
            "</head>",
            "<body>",
            '<main class="shell">',
            _render_header(data),
            _render_status_grid(data),
            _render_safety(data),
            _render_workflow(data, root, output),
            _render_review_queues(data, root, output),
            _render_artifacts(data, root, output),
            _render_actions(data),
            _render_footer(data),
            "</main>",
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
        if _looks_external(href):
            broken.append(Path(href))
            continue
        target = (page.parent / href).resolve()
        if not _is_relative_to(target, root) or not target.exists():
            broken.append(target)
    return broken


def _render_header(data: OperationsCockpitData) -> str:
    return f"""
<section class="top">
  <div>
    <p class="eyebrow">Read-only local dashboard</p>
    <h1>Accounting Agent Operations Cockpit</h1>
    <p class="subtitle">One static view over the local MVP workflow, safety state, review queues, generated outputs, and current blockers.</p>
  </div>
  <div class="stamp">
    <span>Generated</span>
    <strong>{_e(data.generated_at)}</strong>
  </div>
</section>""".strip()


def _render_status_grid(data: OperationsCockpitData) -> str:
    cards = [
        ("Last run", data.last_run, "status"),
        ("Local readiness", data.local_readiness, "ok" if "complete" in data.local_readiness else "warn"),
        ("Demo readiness", data.demo_readiness, "ok" if "complete" in data.demo_readiness else "warn"),
        ("Live Fortnox calls", str(data.live_counters.get("live_fortnox_calls", 0)), "zero"),
        ("Live Microsoft 365 calls", str(data.live_counters.get("live_microsoft365_calls", 0)), "zero"),
        ("Emails / payments / filings", str(data.live_counters.get("emails_payments_filings", 0)), "zero"),
    ]
    body = "".join(
        f"""
  <article class="metric {tone}">
    <span>{_e(label)}</span>
    <strong>{_e(value)}</strong>
  </article>"""
        for label, value, tone in cards
    )
    queue = "".join(
        f"<li><span>{_e(key.replace('_', ' '))}</span><strong>{count}</strong></li>"
        for key, count in sorted(data.queue_counts.items())
    )
    queue_block = (
        f'<ul class="mini-list">{queue}</ul>'
        if queue
        else '<p class="muted">No local SQLite queue counts found yet.</p>'
    )
    return f"""
<section class="panel">
  <div class="section-heading">
    <h2>Operational status</h2>
    <p>Local artifacts only. No provider calls are made to build this page.</p>
  </div>
  <div class="metrics">{body}</div>
  <div class="inline-block">
    <h3>Local SQLite counts</h3>
    {queue_block}
  </div>
</section>""".strip()


def _render_safety(data: OperationsCockpitData) -> str:
    allowed = "".join(f"<li>{_e(item)}</li>" for item in data.allowed_boundaries)
    blocked = "".join(f"<li>{_e(item)}</li>" for item in data.blocked_boundaries)
    warnings = "".join(f"<li>{_e(item)}</li>" for item in data.warnings)
    warning_block = (
        f"""
  <div class="warning-strip">
    <strong>Policy alignment warnings</strong>
    <ul>{warnings}</ul>
  </div>"""
        if warnings
        else ""
    )
    return f"""
<section class="safety">
  <div class="banner">Observe and review only. This cockpit never executes accounting actions and is not an approval authority.</div>
  {warning_block}
  <div class="split">
    <div>
      <h2>Allowed boundaries</h2>
      <ul class="checklist allowed">{allowed}</ul>
    </div>
    <div>
      <h2>Blocked boundaries</h2>
      <ul class="checklist blocked">{blocked}</ul>
    </div>
  </div>
</section>""".strip()


def _render_workflow(
    data: OperationsCockpitData,
    root: Path,
    output: Path,
) -> str:
    steps = []
    for index, step in enumerate(data.workflow, start=1):
        link = _optional_link(step.artifact_path, root, output, "Evidence")
        steps.append(
            f"""
  <article class="workflow-step {step.status}">
    <span class="step-number">{index:02d}</span>
    <h3>{_e(step.label)}</h3>
    <p>{_e(step.detail)}</p>
    <div class="step-meta"><span>{_e(step.status.replace('_', ' '))}</span>{link}</div>
  </article>"""
        )
    return f"""
<section class="panel">
  <div class="section-heading">
    <h2>Workflow map</h2>
    <p>Intake through audit/report, with current local evidence attached where present.</p>
  </div>
  <div class="workflow">{''.join(steps)}</div>
</section>""".strip()


def _render_review_queues(
    data: OperationsCockpitData,
    root: Path,
    output: Path,
) -> str:
    queues = []
    for queue in data.review_queues:
        items = queue.items[:8]
        if items:
            rows = "".join(
                f"""
      <li>
        <span><strong>{_e(item.item_id)}</strong><em>{_e(item.source)} · {_e(item.mode)}</em></span>
        <span>{_e(item.reason)}</span>
        {_optional_link(item.artifact_path, root, output, "Open")}
      </li>"""
                for item in items
            )
            extra = (
                f'<p class="muted">{queue.count - len(items)} more items not shown.</p>'
                if queue.count > len(items)
                else ""
            )
            content = f'<ul class="queue-list">{rows}</ul>{extra}'
        else:
            content = '<p class="muted">No current items found in local artifacts.</p>'
        queues.append(
            f"""
  <article class="queue-card">
    <div class="queue-head">
      <h3>{_e(queue.label)}</h3>
      <strong>{queue.count}</strong>
    </div>
    {content}
  </article>"""
        )
    return f"""
<section class="panel">
  <div class="section-heading">
    <h2>Review queues</h2>
    <p>Cases are derived from generated approval packets, policy decisions, and bank reconciliation proposals.</p>
  </div>
  <div class="queues">{''.join(queues)}</div>
</section>""".strip()


def _render_artifacts(
    data: OperationsCockpitData,
    root: Path,
    output: Path,
) -> str:
    rows = []
    for artifact in data.artifacts:
        label = _e(artifact.label)
        kind = _e(artifact.kind)
        note = f"<span>{_e(artifact.note)}</span>" if artifact.note else ""
        if artifact.exists:
            href = _href(root / artifact.path, output)
            target = f'<a href="{href}">{label}</a>'
            status = "available"
        else:
            target = f"<span>{label}</span>"
            status = "missing"
        rows.append(
            f"""
      <li class="{status}">
        <span>{target}<em>{kind}</em></span>
        {note}
        <strong>{status}</strong>
      </li>"""
        )
    return f"""
<section class="panel">
  <div class="section-heading">
    <h2>Artifact links</h2>
    <p>Links are only emitted for existing repo-local targets.</p>
  </div>
  <ul class="artifact-list">{''.join(rows)}</ul>
</section>""".strip()


def _render_actions(data: OperationsCockpitData) -> str:
    safe = "".join(f"<li><code>{_e(command)}</code></li>" for command in data.safe_next_actions)
    blocked = "".join(f"<li>{_e(action)}</li>" for action in data.not_allowed_actions)
    return f"""
<section class="panel">
  <div class="split">
    <div>
      <h2>Safe next actions</h2>
      <ul class="command-list">{safe}</ul>
    </div>
    <div>
      <h2>Not allowed</h2>
      <ul class="checklist blocked">{blocked}</ul>
    </div>
  </div>
</section>""".strip()


def _render_footer(data: OperationsCockpitData) -> str:
    return f"""
<footer>
  <p>Source root: <code>{_e(data.repo_root)}</code></p>
  <p>This file is static HTML with embedded CSS. It uses no server, CDN, external asset, or live integration.</p>
</footer>""".strip()


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


def _optional_link(path: str | None, root: Path, output: Path, label: str) -> str:
    if not path:
        return ""
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    if not target.exists() or not _is_relative_to(target.resolve(), root):
        return ""
    return f'<a href="{_href(target, output)}">{_e(label)}</a>'


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


_CSS = """
:root {
  color-scheme: light;
  --bg: #f5f7f6;
  --panel: #ffffff;
  --text: #17211d;
  --muted: #5b6863;
  --line: #d9e0dc;
  --green: #0b7a52;
  --green-soft: #dff3e9;
  --amber: #9a5c00;
  --amber-soft: #fff1d6;
  --red: #a93434;
  --red-soft: #fde2df;
  --blue: #255c8a;
  --blue-soft: #e2edf6;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
a { color: var(--blue); text-decoration-thickness: 1px; text-underline-offset: 3px; }
code {
  background: #eef2f0;
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 2px 5px;
  font-size: 0.92em;
}
.shell { width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 44px; }
.top {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 24px;
  align-items: start;
  margin-bottom: 18px;
}
.eyebrow { margin: 0 0 6px; color: var(--blue); font-weight: 700; text-transform: uppercase; font-size: 12px; letter-spacing: 0; }
h1 { margin: 0; font-size: 34px; line-height: 1.1; letter-spacing: 0; }
h2 { margin: 0; font-size: 20px; letter-spacing: 0; }
h3 { margin: 0; font-size: 15px; letter-spacing: 0; }
.subtitle { max-width: 760px; margin: 10px 0 0; color: var(--muted); font-size: 17px; }
.stamp {
  min-width: 220px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--panel);
  padding: 12px;
}
.stamp span, .metric span, .artifact-list em, .queue-list em { display: block; color: var(--muted); font-size: 12px; font-style: normal; }
.stamp strong { display: block; margin-top: 3px; font-size: 14px; overflow-wrap: anywhere; }
.panel, .safety {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin-top: 16px;
}
.section-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: baseline;
  margin-bottom: 14px;
}
.section-heading p { margin: 0; color: var(--muted); max-width: 560px; }
.metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.metric {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 12px;
  min-height: 76px;
}
.metric strong { display: block; margin-top: 8px; font-size: 18px; overflow-wrap: anywhere; }
.metric.ok, .metric.zero { background: var(--green-soft); border-color: #b7dfcc; }
.metric.warn { background: var(--amber-soft); border-color: #efd29c; }
.metric.status { background: var(--blue-soft); border-color: #c7d9e8; }
.inline-block { margin-top: 14px; }
.mini-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  list-style: none;
  padding: 0;
  margin: 10px 0 0;
}
.mini-list li {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 10px;
}
.banner {
  background: var(--red-soft);
  border: 1px solid #f3b4ad;
  color: #70211f;
  border-radius: 7px;
  padding: 12px;
  font-weight: 700;
}
.warning-strip {
  margin-top: 12px;
  background: var(--amber-soft);
  border: 1px solid #efd29c;
  border-radius: 7px;
  padding: 12px;
}
.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-top: 14px;
}
.checklist, .command-list {
  margin: 10px 0 0;
  padding-left: 18px;
}
.checklist li, .command-list li { margin: 7px 0; }
.allowed li::marker { color: var(--green); }
.blocked li::marker { color: var(--red); }
.workflow {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.workflow-step {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 12px;
  min-height: 156px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.workflow-step p { margin: 0; color: var(--muted); }
.workflow-step.available { border-color: #b7dfcc; background: #f4fbf7; }
.workflow-step.review_required, .workflow-step.dry_run_only { border-color: #efd29c; background: #fffaf0; }
.workflow-step.missing { border-color: #e3c0bd; background: #fff7f5; }
.step-number { color: var(--muted); font-weight: 700; }
.step-meta {
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  color: var(--muted);
  font-size: 12px;
}
.queues {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.queue-card {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 12px;
  min-width: 0;
}
.queue-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.queue-head strong {
  min-width: 34px;
  border-radius: 999px;
  background: #eef2f0;
  text-align: center;
  padding: 3px 8px;
}
.queue-list, .artifact-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.queue-list li, .artifact-list li {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
  border-top: 1px solid var(--line);
  padding: 9px 0;
}
.queue-list li:first-child, .artifact-list li:first-child { border-top: 0; }
.queue-list span, .artifact-list span { min-width: 0; overflow-wrap: anywhere; }
.artifact-list .missing strong { color: var(--amber); }
.artifact-list .available strong { color: var(--green); }
.muted { color: var(--muted); margin: 0; }
footer { color: var(--muted); margin-top: 18px; }
@media (max-width: 900px) {
  .top, .split, .section-heading { grid-template-columns: 1fr; display: grid; }
  .metrics, .workflow, .queues, .mini-list { grid-template-columns: 1fr 1fr; }
  .queue-list li, .artifact-list li { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .shell { width: min(100% - 20px, 1180px); padding-top: 18px; }
  h1 { font-size: 28px; }
  .metrics, .workflow, .queues, .mini-list { grid-template-columns: 1fr; }
}
""".strip()
