#!/usr/bin/env python3
"""Report production evidence gates without creating or accepting approvals."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = Path("qa/production-gates.json")
ALLOWED_VERIFICATION_MODES = {
    "external_professional_review",
    "independent_assurance",
    "manual_acceptance",
    "operational_exercise",
}
REQUIRED_DOCUMENT_PHRASE = "does not authorize real-client data"
EXPECTED_DOCUMENT_STATUS = "PRELIMINARY — NOT APPROVED"
EXPECTED_REPOSITORY_TARGET = (
    "sha256:e7c461de6f8bfd676a7ecb697b004d84d3f30b82258754fd278098a92a1ce766"
)
EXPECTED_REVIEWED_REVISION = "d68efe951cb037e7b7fdc7554e43dd8578e79d25"
REVIEW_SENSITIVE_PREFIXES = ("accounting_agent/", ".github/workflows/", "scripts/")
REVIEW_SENSITIVE_FILES = {
    ".gitleaks.toml",
    "MANIFEST.in",
    "package-lock.json",
    "package.json",
    "playwright.config.ts",
    "pyproject.toml",
    "tokens.css",
    "uv.lock",
}
REVIEW_REFRESH_FILES = {
    "scripts/production_readiness.py",
}
TOP_LEVEL_KEYS = {
    "schema_version",
    "gate_set",
    "description",
    "default_outcome",
    "threat_model_binding",
    "required_control_documents",
    "evidence_policy",
    "gates",
}
THREAT_MODEL_BINDING_KEYS = {"repository", "version"}
EVIDENCE_POLICY_KEYS = {
    "templates_are_evidence",
    "repository_documents_can_approve",
    "cli_self_attestation_allowed",
    "trusted_external_verifier_configured",
    "note",
}
GATE_KEYS = {
    "id",
    "title",
    "category",
    "owner_role",
    "required",
    "initial_status",
    "automated_verification",
    "verification_mode",
    "evidence_location",
    "acceptance_criteria",
}
REQUIRED_CONTROL_DOCUMENTS = {
    "docs/security/threat-model.md",
    "docs/security/incident-response.md",
    "docs/compliance/data-map.md",
    "docs/compliance/dpia.md",
    "docs/compliance/ropa.md",
    "docs/compliance/dpa-control-matrix.md",
    "docs/compliance/subprocessor-policy.md",
    "docs/compliance/ai-system-inventory.md",
    "docs/compliance/swedish-accounting-archive-review.md",
}
REQUIRED_GATE_IDS = {
    "privacy-governance-review",
    "swedish-accounting-archive-review",
    "tenant-isolation-assurance",
    "encryption-key-management-assurance",
    "archive-retention-worm-assurance",
    "audit-anchoring-assurance",
    "backup-restore-exercise",
    "manual-accessibility-acceptance",
    "incident-tabletop-notification-test",
    "independent-penetration-test",
}


class DuplicateCatalogKey(ValueError):
    """Raised when JSON attempts to overwrite an earlier catalog key."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateCatalogKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_exact_keys(
    value: Mapping[str, Any],
    allowed: set[str],
    *,
    label: str,
) -> list[str]:
    actual = set(value)
    missing = sorted(allowed - actual)
    unexpected = sorted(actual - allowed)
    if not missing and not unexpected:
        return []
    return [f"{label} keys must match the fixed schema; missing={missing}, unexpected={unexpected}"]


def _control_document_errors(content: str) -> list[str]:
    errors: list[str] = []
    lines = content.splitlines()
    status_fields: list[tuple[int, str]] = []
    decision_fields: list[tuple[int, str]] = []
    status_mentions = 0
    decision_mentions = 0
    approval_headings: list[int] = []
    for line_number, line in enumerate(lines):
        status_mentions += len(re.findall(r"\bStatus\s*:", line, flags=re.IGNORECASE))
        decision_mentions += len(re.findall(r"\bDecision\s*:", line, flags=re.IGNORECASE))
        status_match = re.fullmatch(r"\s*Status\s*:\s*(.*?)\s*", line, flags=re.IGNORECASE)
        if status_match:
            status_fields.append((line_number, status_match.group(1)))
        decision_match = re.fullmatch(
            r"\s*(?:[-*]\s*)?Decision\s*:\s*(.*?)\s*",
            line,
            flags=re.IGNORECASE,
        )
        if decision_match:
            decision_fields.append((line_number, decision_match.group(1)))
        if re.fullmatch(r"\s*##\s+Approval record\s*", line, flags=re.IGNORECASE):
            approval_headings.append(line_number)

    if len(status_fields) != 1 or status_fields[0][1] != EXPECTED_DOCUMENT_STATUS:
        errors.append(
            "document must contain exactly one structural status field with value "
            f"{EXPECTED_DOCUMENT_STATUS}"
        )
    if status_mentions != 1:
        errors.append("document must not contain hidden or contradictory Status fields")
    if len(approval_headings) != 1:
        errors.append("document must contain exactly one Approval record section")
    if len(decision_fields) != 1 or decision_fields[0][1].casefold() != "pending":
        errors.append("document must contain exactly one structural Decision field set to PENDING")
    elif approval_headings:
        heading_index = approval_headings[0]
        next_section = next(
            (
                index
                for index in range(heading_index + 1, len(lines))
                if re.match(r"\s*#{1,2}\s+", lines[index])
            ),
            len(lines),
        )
        decision_index = decision_fields[0][0]
        if not heading_index < decision_index < next_section:
            errors.append("Decision field must be inside the Approval record section")
    if decision_mentions != 1:
        errors.append("document must not contain hidden or contradictory Decision fields")

    normalized_content = " ".join(content.casefold().split())
    if REQUIRED_DOCUMENT_PHRASE not in normalized_content:
        errors.append(f"document must state that it {REQUIRED_DOCUMENT_PHRASE}")
    return errors


def _threat_model_binding_errors(content: str) -> list[str]:
    errors: list[str] = []
    repositories = re.findall(r"(?m)^Repository: (sha256:[0-9a-f]{64})$", content)
    versions = re.findall(r"(?m)^Version: ([0-9a-f]{40})$", content)
    if repositories != [EXPECTED_REPOSITORY_TARGET]:
        errors.append("threat model repository target does not match the reviewed repository")
    if versions != [EXPECTED_REVIEWED_REVISION]:
        errors.append("threat model version does not match the reviewed code revision")
    if "## Regeneration policy" not in content:
        errors.append("threat model must define its regeneration policy")
    return errors


def _runtime_drift_errors(root: Path) -> list[str]:
    if not (root / ".git").exists():
        return []
    commands = (
        ("git", "diff", "--name-only", EXPECTED_REVIEWED_REVISION, "--"),
        ("git", "ls-files", "--others", "--exclude-standard"),
    )
    changed_paths: set[str] = set()
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return ["threat-model runtime drift could not be evaluated safely"]
        changed_paths.update(line.strip() for line in completed.stdout.splitlines() if line.strip())
    sensitive = sorted(
        path
        for path in changed_paths
        if path not in REVIEW_REFRESH_FILES
        and (
            path in REVIEW_SENSITIVE_FILES
            or any(path.startswith(prefix) for prefix in REVIEW_SENSITIVE_PREFIXES)
        )
    )
    if not sensitive:
        return []
    return ["threat model is stale for reviewed runtime path(s): " + ", ".join(sensitive)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(root: Path, candidate: Path, *, label: str) -> tuple[Path | None, str | None]:
    try:
        root_resolved = root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        return None, f"repository root is unavailable: {error}"

    root_absolute = Path(os.path.abspath(root))
    try:
        lexical_relative = (
            Path(os.path.abspath(candidate)).relative_to(root_absolute)
            if candidate.is_absolute()
            else candidate
        )
    except ValueError:
        return None, f"{label} escapes the repository root"
    if lexical_relative.is_absolute() or ".." in lexical_relative.parts:
        return None, f"{label} escapes the repository root"
    path_absolute = root_resolved / lexical_relative
    current = root_resolved
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            return None, f"{label} must not use symlinks"
    try:
        path_resolved = path_absolute.resolve(strict=True)
        path_resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError):
        return None, f"{label} must be a regular file below the repository root"

    if not path_resolved.is_file() or path_resolved.is_symlink():
        return None, f"{label} must be a regular file"
    return path_resolved, None


def _load_catalog(root: Path, catalog_path: Path) -> tuple[Mapping[str, Any] | None, list[str]]:
    path, path_error = _safe_file(root, catalog_path, label="production gate catalog")
    if path_error or path is None:
        return None, [path_error or "production gate catalog is unavailable"]
    try:
        loaded = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateCatalogKey) as error:
        return None, [f"production gate catalog is not valid UTF-8 JSON: {error}"]
    if not isinstance(loaded, Mapping):
        return None, ["production gate catalog must be a JSON object"]
    return loaded, []


def _validate_catalog(catalog: Mapping[str, Any]) -> list[str]:
    errors = _validate_exact_keys(catalog, TOP_LEVEL_KEYS, label="catalog")
    if catalog.get("schema_version") != 1:
        errors.append("catalog schema_version must be 1")
    if catalog.get("gate_set") != "first-real-client-byte":
        errors.append("catalog gate_set must be first-real-client-byte")
    if catalog.get("default_outcome") != "pending":
        errors.append("catalog default_outcome must remain pending")
    if not isinstance(catalog.get("description"), str) or not catalog["description"].strip():
        errors.append("catalog description must be a non-empty string")

    threat_model_binding = catalog.get("threat_model_binding")
    if not isinstance(threat_model_binding, Mapping):
        errors.append("catalog threat_model_binding must be an object")
    else:
        errors.extend(
            _validate_exact_keys(
                threat_model_binding,
                THREAT_MODEL_BINDING_KEYS,
                label="threat_model_binding",
            )
        )
        if threat_model_binding.get("repository") != EXPECTED_REPOSITORY_TARGET:
            errors.append("threat_model_binding.repository does not match the canonical target")
        if threat_model_binding.get("version") != EXPECTED_REVIEWED_REVISION:
            errors.append("threat_model_binding.version does not match the reviewed revision")

    evidence_policy = catalog.get("evidence_policy")
    if not isinstance(evidence_policy, Mapping):
        errors.append("catalog evidence_policy must be an object")
    else:
        errors.extend(
            _validate_exact_keys(
                evidence_policy,
                EVIDENCE_POLICY_KEYS,
                label="evidence_policy",
            )
        )
        required_false = (
            "templates_are_evidence",
            "repository_documents_can_approve",
            "cli_self_attestation_allowed",
            "trusted_external_verifier_configured",
        )
        for name in required_false:
            if evidence_policy.get(name) is not False:
                errors.append(f"evidence_policy.{name} must remain false")
        if not isinstance(evidence_policy.get("note"), str) or not evidence_policy["note"].strip():
            errors.append("evidence_policy.note must be a non-empty string")

    documents = catalog.get("required_control_documents")
    if not isinstance(documents, list) or not documents:
        errors.append("required_control_documents must be a non-empty list")
    elif any(not isinstance(path, str) or not path.strip() for path in documents):
        errors.append("required_control_documents entries must be non-empty strings")
    elif len(documents) != len(set(documents)):
        errors.append("required_control_documents must not contain duplicates")
    elif set(documents) != REQUIRED_CONTROL_DOCUMENTS:
        missing = sorted(REQUIRED_CONTROL_DOCUMENTS - set(documents))
        unexpected = sorted(set(documents) - REQUIRED_CONTROL_DOCUMENTS)
        errors.append(
            "required_control_documents must match the fixed control pack; "
            f"missing={missing}, unexpected={unexpected}"
        )
    elif any(Path(path).is_absolute() or ".." in Path(path).parts for path in documents):
        errors.append("required_control_documents paths must be safe relative paths")

    gates = catalog.get("gates")
    if not isinstance(gates, list) or not gates:
        return errors + ["gates must be a non-empty list"]
    seen: set[str] = set()
    for index, gate in enumerate(gates):
        if not isinstance(gate, Mapping):
            errors.append(f"gate at index {index} must be an object")
            continue
        errors.extend(_validate_exact_keys(gate, GATE_KEYS, label=f"gate at index {index}"))
        gate_id = gate.get("id")
        label = gate_id if isinstance(gate_id, str) and gate_id else f"index {index}"
        if not isinstance(gate_id, str) or not gate_id.strip():
            errors.append(f"gate {label} requires a non-empty id")
        elif gate_id in seen:
            errors.append(f"gate id {gate_id} is duplicated")
        else:
            seen.add(gate_id)
        if gate.get("required") is not True:
            errors.append(f"gate {label} must remain required")
        if gate.get("initial_status") != "pending":
            errors.append(f"gate {label} initial_status must remain pending")
        if gate.get("automated_verification") is not False:
            errors.append(f"gate {label} automated_verification must remain false")
        if gate.get("verification_mode") not in ALLOWED_VERIFICATION_MODES:
            errors.append(f"gate {label} has an unsupported verification_mode")
        if not isinstance(gate.get("owner_role"), str) or not gate["owner_role"].strip():
            errors.append(f"gate {label} requires an owner_role")
        if not isinstance(gate.get("title"), str) or not gate["title"].strip():
            errors.append(f"gate {label} requires a title")
        if not isinstance(gate.get("category"), str) or not gate["category"].strip():
            errors.append(f"gate {label} requires a category")
        criteria = gate.get("acceptance_criteria")
        if (
            not isinstance(criteria, list)
            or not criteria
            or any(not isinstance(item, str) or not item.strip() for item in criteria)
        ):
            errors.append(f"gate {label} requires non-empty acceptance_criteria")
        evidence_location = gate.get("evidence_location")
        if not isinstance(evidence_location, str) or not evidence_location.startswith(
            ".local/production-readiness/evidence/"
        ):
            errors.append(f"gate {label} evidence_location must remain below .local")
        elif Path(evidence_location).is_absolute() or ".." in Path(evidence_location).parts:
            errors.append(f"gate {label} evidence_location is unsafe")
    if seen != REQUIRED_GATE_IDS:
        missing = sorted(REQUIRED_GATE_IDS - seen)
        unexpected = sorted(seen - REQUIRED_GATE_IDS)
        errors.append(
            "gate ids must match the fixed first-real-client-byte gate set; "
            f"missing={missing}, unexpected={unexpected}"
        )
    return errors


def evaluate_readiness(root: Path, catalog_path: Path) -> dict[str, Any]:
    root = root.expanduser()
    catalog, errors = _load_catalog(root, catalog_path.expanduser())
    invalid_controls: list[dict[str, str]] = []
    document_receipts: list[dict[str, str]] = []
    gate_reports: list[dict[str, Any]] = []

    if catalog is not None:
        errors.extend(_validate_catalog(catalog))
        errors.extend(_runtime_drift_errors(root.resolve()))
        documents = catalog.get("required_control_documents", [])
        if isinstance(documents, list):
            for relative_path in documents:
                if not isinstance(relative_path, str):
                    continue
                path, path_error = _safe_file(
                    root,
                    Path(relative_path),
                    label=f"control document {relative_path}",
                )
                if path_error or path is None:
                    invalid_controls.append(
                        {
                            "path": relative_path,
                            "error": path_error or "control document is unavailable",
                        }
                    )
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError) as error:
                    invalid_controls.append(
                        {"path": relative_path, "error": f"cannot read UTF-8 document: {error}"}
                    )
                    continue
                document_errors = _control_document_errors(content)
                if relative_path == "docs/security/threat-model.md":
                    document_errors.extend(_threat_model_binding_errors(content))
                if document_errors:
                    invalid_controls.append(
                        {
                            "path": relative_path,
                            "error": "; ".join(document_errors),
                        }
                    )
                    continue
                document_receipts.append({"path": relative_path, "sha256": _sha256(path)})

        gates = catalog.get("gates", [])
        if isinstance(gates, list):
            for gate in gates:
                if not isinstance(gate, Mapping):
                    continue
                gate_reports.append(
                    {
                        "id": str(gate.get("id", "invalid")),
                        "status": "pending",
                        "verification_mode": gate.get("verification_mode"),
                        "reason": "independent or manual verification is not configured in this repository",
                    }
                )

    if invalid_controls:
        errors.append("one or more required control documents are missing or invalid")
    status = "invalid" if errors else "pending"
    return {
        "schema_version": 1,
        "gate_set": "first-real-client-byte",
        "status": status,
        "ready": False,
        "blocking_gate_count": len(gate_reports),
        "invalid_control_count": len(invalid_controls),
        "errors": errors,
        "invalid_controls": invalid_controls,
        "control_documents": document_receipts,
        "gates": gate_reports,
        "message": (
            "Production controls are invalid; repair the catalog or control pack."
            if errors
            else "All first-real-client-byte gates remain pending external or manual verification."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect fail-closed production evidence gates. This command cannot approve, "
            "attest, or verify an external gate."
        )
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root to inspect.")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Gate catalog path; relative paths are resolved below --root.",
    )
    parser.add_argument("--json", action="store_true", help="Write the report as JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_readiness(args.root, args.catalog)
    except Exception as evaluation_error:  # Defensive CLI boundary: no operator traceback.
        report = {
            "schema_version": 1,
            "gate_set": "first-real-client-byte",
            "status": "invalid",
            "ready": False,
            "blocking_gate_count": 0,
            "invalid_control_count": 0,
            "errors": [f"readiness evaluation failed safely: {type(evaluation_error).__name__}"],
            "invalid_controls": [],
            "control_documents": [],
            "gates": [],
            "message": "Production readiness could not be evaluated.",
        }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Production readiness: {report['status']}")
        print(report["message"])
        print(f"Blocking gates: {report['blocking_gate_count']}")
        print(f"Invalid controls: {report['invalid_control_count']}")
        for report_error in report["errors"]:
            print(f"ERROR: {report_error}", file=sys.stderr)
    return 1 if report["status"] == "invalid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
