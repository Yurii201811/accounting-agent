#!/usr/bin/env python3
"""Run reproducible Accounting Agent QA gates and write a sanitized summary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
RELEASE_SOURCE_DATE_EPOCH = "1752192000"
RELEASE_PREVIEW_BUNDLE = ROOT / ".local" / "accounting-agent-v1-preview-release"
_MANUAL_ACCESSIBILITY_FIELDS = (
    "tester",
    "tested_at_utc",
    "macos_version",
    "browser",
    "voiceover_version",
    "revision",
    "preview_bundle_sha256",
)
_PUBLIC_PREVIEW_FILES = (
    "LICENSE.lucide.txt",
    "favicon.svg",
    "index.html",
    "preview-manifest.json",
    "tokens.css",
)
QUICK_STEP_NAMES = (
    "compile",
    "offline-tests",
    "v1-system-check",
)
FULL_STEP_NAMES = (
    "compile",
    "coverage-erase",
    "branch-coverage",
    "coverage-combine",
    "coverage-json",
    "coverage-xml",
    "coverage-html",
    "coverage-report",
    "coverage-gate",
    "v1-system-check",
    "ruff",
    "mypy",
    "targeted-mutation",
    "mutation-safety-gate",
    "bandit",
    "dependency-lock-export",
    "pip-audit",
    "gitleaks",
    "fixture-policy",
    "ui-e2e",
)
RELEASE_STEP_NAMES = FULL_STEP_NAMES + (
    "package-release",
    "preview-build",
    "preview-contract",
    "fixture-policy-preview",
    "deployment-smoke",
)
_STEP_NAMES_BY_MODE = {
    "quick": QUICK_STEP_NAMES,
    "full": FULL_STEP_NAMES,
    "release": RELEASE_STEP_NAMES,
}


@dataclass(frozen=True)
class Step:
    name: str
    command: tuple[str, ...]
    offline: bool = False


@dataclass(frozen=True)
class StepResult:
    name: str
    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    log_file: str | None = None


def build_step_plan(mode: str, *, python: str = sys.executable) -> tuple[Step, ...]:
    quick = (
        Step("compile", (python, "-m", "compileall", "-q", "accounting_agent", "tests")),
        Step(
            "offline-tests",
            (python, "-m", "unittest", "discover", "-s", "tests", "-t", "."),
            offline=True,
        ),
        Step(
            "v1-system-check",
            (python, "-m", "accounting_agent.cli", "v1-system-check", "--json"),
            offline=True,
        ),
    )
    if mode == "quick":
        return quick

    full = (
        quick[0],
        Step("coverage-erase", (python, "-m", "coverage", "erase")),
        Step(
            "branch-coverage",
            (
                python,
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "-m",
                "pytest",
                "-q",
                "--junitxml={artifact_dir}/junit/python.xml",
            ),
            offline=True,
        ),
        Step(
            "coverage-combine",
            (python, "-m", "coverage", "combine", "{artifact_dir}/coverage"),
        ),
        Step(
            "coverage-json",
            (
                python,
                "-m",
                "coverage",
                "json",
                "-o",
                "{artifact_dir}/coverage/coverage.json",
            ),
        ),
        Step(
            "coverage-xml",
            (
                python,
                "-m",
                "coverage",
                "xml",
                "-o",
                "{artifact_dir}/coverage/coverage.xml",
            ),
        ),
        Step(
            "coverage-html",
            (
                python,
                "-m",
                "coverage",
                "html",
                "-d",
                "{artifact_dir}/coverage/html",
            ),
        ),
        Step(
            "coverage-report",
            (python, "-m", "coverage", "report", "--show-missing", "--fail-under=85"),
        ),
        Step(
            "coverage-gate",
            (
                python,
                "scripts/coverage_gate.py",
                "{artifact_dir}/coverage/coverage.json",
                "--baseline",
                "qa/coverage-baseline.json",
            ),
        ),
        quick[2],
        Step("ruff", (python, "-m", "ruff", "check", ".")),
        Step("mypy", (python, "-m", "mypy", "accounting_agent")),
        Step("targeted-mutation", ("mutmut", "run", "--max-children", "4")),
        Step(
            "mutation-safety-gate",
            (
                python,
                "scripts/mutation_gate.py",
                "--output",
                "{artifact_dir}/mutation/summary.json",
            ),
        ),
        Step(
            "bandit",
            (
                python,
                "-m",
                "bandit",
                "-q",
                "-r",
                "accounting_agent",
                "-f",
                "json",
                "-o",
                "{artifact_dir}/security/bandit.json",
            ),
        ),
        Step(
            "dependency-lock-export",
            (
                "uv",
                "export",
                "--quiet",
                "--group",
                "qa",
                "--no-emit-project",
                "--locked",
                "--format",
                "requirements-txt",
                "--output-file",
                "{artifact_dir}/security/qa-requirements.lock",
            ),
        ),
        Step(
            "pip-audit",
            (
                python,
                "-m",
                "pip_audit",
                "--strict",
                "--require-hashes",
                "--disable-pip",
                "--requirement",
                "{artifact_dir}/security/qa-requirements.lock",
                "--format",
                "json",
                "--output",
                "{artifact_dir}/security/pip-audit.json",
            ),
        ),
        Step(
            "gitleaks",
            (
                "gitleaks",
                "dir",
                ".",
                "--redact",
                "--no-banner",
                "--report-format",
                "json",
                "--report-path",
                "{artifact_dir}/security/gitleaks.json",
            ),
        ),
        Step(
            "fixture-policy",
            (
                python,
                "scripts/fixture_policy.py",
                "--json",
                "--output",
                "{artifact_dir}/security/fixture-policy.json",
            ),
            offline=True,
        ),
        Step("ui-e2e", ("npm", "run", "test:ui:all")),
    )
    if mode == "full":
        return full
    if mode == "release":
        return full + (
            Step(
                "package-release",
                (
                    python,
                    "scripts/package_release_check.py",
                    "--output",
                    "{artifact_dir}/package",
                ),
                offline=True,
            ),
            Step(
                "preview-build",
                (
                    python,
                    "-m",
                    "accounting_agent.cli",
                    "build-public-preview",
                    "--output",
                    ".local/accounting-agent-v1-preview-release",
                ),
                offline=True,
            ),
            Step(
                "preview-contract",
                (python, "-m", "unittest", "tests.test_operations_cockpit"),
                offline=True,
            ),
            Step(
                "fixture-policy-preview",
                (
                    python,
                    "scripts/fixture_policy.py",
                    "--preview-root",
                    ".local/accounting-agent-v1-preview-release",
                    "--json",
                    "--output",
                    "{artifact_dir}/security/fixture-policy-preview.json",
                ),
                offline=True,
            ),
            Step(
                "deployment-smoke",
                (
                    python,
                    "scripts/deployment_smoke.py",
                    "--output",
                    "{artifact_dir}/preview/deployment-smoke.json",
                ),
            ),
        )
    raise ValueError(f"Unsupported QA mode: {mode}")


def _step_environment(step: Step, artifact_dir: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if step.name == "preview-build":
        env["SOURCE_DATE_EPOCH"] = RELEASE_SOURCE_DATE_EPOCH
    if step.name == "deployment-smoke":
        env["ACCOUNTING_AGENT_PREVIEW_BUNDLE"] = str(RELEASE_PREVIEW_BUNDLE)
    if artifact_dir is not None:
        coverage_dir = artifact_dir / "coverage"
        env["COVERAGE_FILE"] = str(coverage_dir / ".coverage")
        env["PLAYWRIGHT_OUTPUT_DIR"] = str(artifact_dir / "playwright" / "results")
        env["QA_RUN_DIR"] = str(artifact_dir / "playwright")
        env["PLAYWRIGHT_HTML_OUTPUT_DIR"] = str(
            artifact_dir / "playwright" / "html"
        )
        env["PLAYWRIGHT_JUNIT_OUTPUT_NAME"] = str(
            artifact_dir / "junit" / "playwright.xml"
        )
    if step.offline:
        guard_dir = ROOT / "tests" / "offline_guard"
        env["ACCOUNTING_AGENT_TEST_OFFLINE"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(guard_dir), env.get("PYTHONPATH", "")) if part
        )
        env["PYTHONHASHSEED"] = "0"
        env["COVERAGE_PROCESS_START"] = str(ROOT / "pyproject.toml")
    return env


def _sanitize_log(output: str) -> str:
    sanitized = output.replace(str(ROOT), "<repo>").replace(str(Path.home()), "<home>")
    return re.sub(
        r"(?i)\b(token|password|secret)(\s*[:=]\s*)(\S+)",
        r"\1\2[redacted]",
        sanitized,
    )


def run_step(step: Step, *, artifact_dir: Path | None = None) -> StepResult:
    started = time.monotonic()
    materialized_command = tuple(
        part.replace("{artifact_dir}", str(artifact_dir))
        if artifact_dir is not None
        else part
        for part in step.command
    )
    log_path: Path | None = None
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for child in ("coverage", "junit", "playwright", "security"):
            (artifact_dir / child).mkdir(parents=True, exist_ok=True)
        log_path = artifact_dir / "logs" / f"{step.name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            materialized_command,
            cwd=ROOT,
            env=_step_environment(step, artifact_dir),
            check=False,
            capture_output=True,
            text=True,
        )
        exit_code = completed.returncode
        output = _sanitize_log(completed.stdout + completed.stderr)
    except FileNotFoundError as exc:
        print(f"QA step {step.name!r} could not start: {exc}", file=sys.stderr)
        exit_code = 127
        output = _sanitize_log(str(exc) + "\n")
    if log_path is not None:
        log_path.write_text(output, encoding="utf-8")
    if exit_code != 0 and output:
        excerpt = "\n".join(output.splitlines()[-30:])
        print(excerpt, file=sys.stderr)
    return StepResult(
        name=step.name,
        command=step.command,
        exit_code=exit_code,
        duration_seconds=round(time.monotonic() - started, 3),
        log_file=f"logs/{step.name}.log" if log_path is not None else None,
    )


def write_summary(
    path: Path,
    *,
    mode: str,
    revision: str,
    revision_start: str | None = None,
    results: Sequence[StepResult],
    manual_accessibility_evidence: Path | None = None,
    preview_bundle_sha256: str | None = None,
    source_state_stable: bool = True,
    working_tree_dirty: bool = False,
) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        expected_step_names = _STEP_NAMES_BY_MODE[mode]
    except KeyError as error:
        raise ValueError(f"Unsupported QA mode: {mode}") from error
    actual_step_names = tuple(result.name for result in results)
    plan_complete = bool(expected_step_names) and actual_step_names == expected_step_names
    automated_passed = plan_complete and all(
        result.exit_code == 0 for result in results
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "mode": mode,
        "revision": revision,
        "revision_start": revision if revision_start is None else revision_start,
        "source_state_stable": source_state_stable,
        "working_tree_dirty": working_tree_dirty,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_complete": plan_complete,
        "passed": automated_passed,
        "steps": [asdict(result) for result in results],
    }
    if mode == "release":
        if preview_bundle_sha256 is None:
            preview_bundle_sha256 = _public_preview_bundle_sha256(
                RELEASE_PREVIEW_BUNDLE
            )
        manual_accessibility = _manual_accessibility_status(
            path.parent,
            revision,
            expected_bundle_sha256=preview_bundle_sha256,
            evidence_source=manual_accessibility_evidence,
        )
        payload["preview_bundle_sha256"] = preview_bundle_sha256
        payload["manual_accessibility"] = manual_accessibility
        payload["release_ready"] = (
            automated_passed
            and manual_accessibility == "passed"
            and source_state_stable
            and not working_tree_dirty
        )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def _public_preview_bundle_sha256(bundle: Path) -> str | None:
    if not bundle.is_dir() or bundle.is_symlink():
        return None
    actual_paths = tuple(
        sorted(path.relative_to(bundle).as_posix() for path in bundle.rglob("*"))
    )
    if actual_paths != _PUBLIC_PREVIEW_FILES:
        return None

    digest = hashlib.sha256()
    for name in _PUBLIC_PREVIEW_FILES:
        path = bundle / name
        if path.is_symlink() or not path.is_file():
            return None
        payload = path.read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _manual_accessibility_status(
    artifact_dir: Path,
    revision: str,
    *,
    expected_bundle_sha256: str | None,
    evidence_source: Path | None = None,
) -> str:
    evidence_path = artifact_dir / "accessibility" / "manual-voiceover.md"
    source_path = evidence_path if evidence_source is None else evidence_source
    if evidence_path.parent.is_symlink() or evidence_path.is_symlink():
        return "failed"
    if evidence_source is None and not source_path.exists():
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            "# Manual VoiceOver evidence\n\n"
            "status: pending\n"
            f"revision: {revision}\n"
            "tester:\n"
            "tested_at_utc:\n"
            "macos_version:\n"
            "browser:\n"
            "voiceover_version:\n"
            f"preview_bundle_sha256: {expected_bundle_sha256 or ''}\n\n"
            "Complete the repository VoiceOver checklist against this exact revision "
            "and preview bundle before changing status to passed.\n",
            encoding="utf-8",
        )
        return "pending"

    if source_path.is_symlink() or not source_path.is_file():
        return "failed"

    metadata: dict[str, str] = {}
    recognized = {"status", *_MANUAL_ACCESSIBILITY_FIELDS}
    try:
        lines = source_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return "failed"
    for line in lines:
        key, separator, value = line.partition(":")
        normalized_key = key.strip().lower()
        if not separator or normalized_key not in recognized:
            continue
        if normalized_key in metadata:
            return "failed"
        metadata[normalized_key] = value.strip()

    status = metadata.get("status")
    if status not in {"passed", "failed", "pending"}:
        return "failed"
    if status != "passed":
        _copy_manual_accessibility_metadata(evidence_path, metadata)
        return status
    if metadata.get("revision") != revision:
        return "failed"
    if any(not metadata.get(field) for field in _MANUAL_ACCESSIBILITY_FIELDS):
        return "failed"
    if not _is_utc_timestamp(metadata["tested_at_utc"]):
        return "failed"
    recorded_bundle_sha256 = metadata["preview_bundle_sha256"]
    if (
        re.fullmatch(r"[0-9a-f]{64}", recorded_bundle_sha256) is None
        or recorded_bundle_sha256 != expected_bundle_sha256
    ):
        return "failed"
    _copy_manual_accessibility_metadata(evidence_path, metadata)
    return "passed"


def _copy_manual_accessibility_metadata(
    destination: Path,
    metadata: dict[str, str],
) -> None:
    if destination.is_symlink() or destination.parent.is_symlink():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    ordered_fields = ("status", *_MANUAL_ACCESSIBILITY_FIELDS)
    destination.write_text(
        "# Manual VoiceOver evidence\n\n"
        + "\n".join(f"{field}: {metadata.get(field, '')}" for field in ordered_fields)
        + "\n",
        encoding="utf-8",
    )


def _is_utc_timestamp(value: str) -> bool:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _absolute_without_symlink_resolution(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    return Path(os.path.abspath(candidate))


def _qa_runs_root() -> Path:
    return ROOT / ".local" / "qa" / "runs"


def _reject_symlink_components(path: Path, *, root: Path) -> None:
    for component in (ROOT / ".local", ROOT / ".local" / "qa", root):
        if component.is_symlink():
            raise ValueError("QA evidence path must not contain symlinks")
        if component.exists() and not component.is_dir():
            raise ValueError("QA evidence path parent must be a directory")
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("QA evidence path must not contain symlinks")


def _validated_summary_path(path: Path) -> Path:
    normalized = _absolute_without_symlink_resolution(path)
    runs_root = _qa_runs_root()
    try:
        relative = normalized.relative_to(runs_root)
    except ValueError as error:
        raise ValueError("QA summary must stay inside the QA runs directory") from error
    if (
        len(relative.parts) != 2
        or relative.parts[1] != "summary.json"
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", relative.parts[0])
        is None
    ):
        raise ValueError("QA summary must use .local/qa/runs/<run-id>/summary.json")
    _reject_symlink_components(normalized, root=runs_root)
    run_dir = normalized.parent
    if run_dir.exists():
        if not run_dir.is_dir():
            raise ValueError("QA run path must be a directory")
        if any(descendant.is_symlink() for descendant in run_dir.rglob("*")):
            raise ValueError("QA evidence path must not contain symlinks")
    if normalized.exists() and not normalized.is_file():
        raise ValueError("QA summary path must be a regular file")
    return normalized


def _validated_manual_evidence_path(path: Path) -> Path:
    normalized = _absolute_without_symlink_resolution(path)
    runs_root = _qa_runs_root()
    try:
        relative = normalized.relative_to(runs_root)
    except ValueError as error:
        raise ValueError(
            "Manual accessibility evidence must stay inside the QA runs directory"
        ) from error
    if (
        len(relative.parts) != 3
        or relative.parts[1:] != ("accessibility", "manual-voiceover.md")
    ):
        raise ValueError(
            "Manual accessibility evidence must use "
            ".local/qa/runs/<run-id>/accessibility/manual-voiceover.md"
        )
    _reject_symlink_components(normalized, root=runs_root)
    if not normalized.is_file() or normalized.is_symlink():
        raise ValueError("Manual accessibility evidence must be a regular file")
    return normalized


def _revision() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _working_tree_dirty() -> bool:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=normal"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(completed.stdout.strip())


def _qa_exit_code(
    *,
    mode: str,
    automated_passed: bool,
    release_ready: bool | None,
) -> int:
    if not automated_passed:
        return 1
    if mode == "release" and release_ready is not True:
        return 2
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Accounting Agent QA runner")
    parser.add_argument("mode", choices=("quick", "full", "release"))
    parser.add_argument("--summary", type=Path)
    parser.add_argument(
        "--manual-accessibility-evidence",
        type=Path,
        help=(
            "Prior revision- and bundle-bound VoiceOver evidence under "
            ".local/qa/runs/<run-id>/accessibility/manual-voiceover.md"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    requested_summary = (
        args.summary
        or ROOT / ".local" / "qa" / "runs" / run_id / "summary.json"
    )
    try:
        summary_path = _validated_summary_path(requested_summary)
        manual_accessibility_evidence = (
            _validated_manual_evidence_path(args.manual_accessibility_evidence)
            if args.manual_accessibility_evidence is not None
            else None
        )
    except ValueError as error:
        print(f"QA evidence path rejected: {error}", file=sys.stderr)
        return 1

    artifact_dir = summary_path.parent
    revision_start = _revision()
    dirty_start = _working_tree_dirty()
    results: list[StepResult] = []
    for step in build_step_plan(args.mode):
        print(f"\n[qa] {step.name}", flush=True)
        result = run_step(step, artifact_dir=artifact_dir)
        results.append(result)
        if args.mode == "quick" and result.exit_code != 0:
            break

    revision_end = _revision()
    dirty_end = _working_tree_dirty()
    source_state_stable = (
        revision_start == revision_end and not dirty_start and not dirty_end
    )
    summary_payload = write_summary(
        summary_path,
        mode=args.mode,
        revision=revision_end,
        revision_start=revision_start,
        results=results,
        manual_accessibility_evidence=manual_accessibility_evidence,
        source_state_stable=source_state_stable,
        working_tree_dirty=dirty_start or dirty_end,
    )
    print(f"\n[qa] summary: {summary_path}")
    return _qa_exit_code(
        mode=args.mode,
        automated_passed=bool(summary_payload["passed"]),
        release_ready=(
            bool(summary_payload["release_ready"])
            if "release_ready" in summary_payload
            else None
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
