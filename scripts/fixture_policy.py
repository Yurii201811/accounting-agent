#!/usr/bin/env python3
"""Fail-closed privacy policy for synthetic fixtures and preview resources."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence

ResourceKind = Literal["fixture", "preview"]
DEFAULT_MAX_BYTES = 1_048_576

_ALLOWED_EXTENSIONS: dict[ResourceKind, frozenset[str]] = {
    "fixture": frozenset({".csv", ".json", ".md", ".txt"}),
    "preview": frozenset({".css", ".html", ".json", ".svg", ".txt"}),
}

_LOCAL_PATH_RE = re.compile(
    r"(?:file://)?/Users/|(?:^|[\\/])Downloads[\\/]|"
    r"[A-Za-z]:\\Users\\|(?:file://)?/home/[^/\s]+/|(?:^|[\"'\s])\.local[\\/]",
    re.IGNORECASE | re.MULTILINE,
)
_PRIVATE_COURSE_RE = re.compile(
    r"kursstart\.se|e42(?:7o|8o)-bokforing[23]|t-konton-mall-bok1",
    re.IGNORECASE,
)
_SOURCE_LOCAL_PATH_RE = re.compile(
    r"(?:file://)?/(?:Users|home)/[^/\s]+/|"
    r"(?:^|[\\/])Downloads[\\/]|[A-Za-z]:\\Users\\",
    re.IGNORECASE | re.MULTILINE,
)
_PROVENANCE_SOURCE_EXTENSIONS = frozenset({".md", ".py", ".toml", ".yaml", ".yml"})
_PROVENANCE_SCAN_EXEMPTIONS = frozenset(
    {
        "accounting_agent/operations_cockpit.py",
        "scripts/evidence_privacy.py",
        "scripts/fixture_policy.py",
    }
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{24,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b"),
    re.compile(
        r"\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|password|credential)\b"
        r"\s*[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=:@-]{12,}",
        re.IGNORECASE,
    ),
)
_TEXT_SYNTHETIC_RE = re.compile(r"\b(?:synthetic|fixture|mocked?)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    path: str
    detail: str


@dataclass(frozen=True, slots=True)
class ScanReport:
    files_scanned: int
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


def _iter_resource_paths(inputs: Iterable[Path]) -> list[Path]:
    resources: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = os.path.abspath(os.fspath(path))
        if key not in seen:
            seen.add(key)
            resources.append(path)

    for candidate in inputs:
        candidate = Path(candidate)
        if candidate.is_symlink() or candidate.is_file() or not candidate.exists():
            add(candidate)
            continue
        for directory, directory_names, file_names in os.walk(candidate, followlinks=False):
            directory_path = Path(directory)
            for name in list(directory_names):
                path = directory_path / name
                if path.is_symlink():
                    add(path)
                    directory_names.remove(name)
            for name in file_names:
                add(directory_path / name)
    return sorted(resources, key=lambda path: os.fspath(path))


def _display_path(path: Path, display_root: Path | None) -> str:
    if display_root is not None:
        try:
            return path.absolute().relative_to(display_root.absolute()).as_posix()
        except ValueError:
            pass
    return path.name


def _has_synthetic_json_metadata(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    if document.get("synthetic") is True:
        return True
    if isinstance(document.get("scenario"), str) and isinstance(document.get("mock_extraction"), dict):
        return True

    record_lists = [
        value
        for value in document.values()
        if isinstance(value, list) and value and all(isinstance(record, dict) for record in value)
    ]
    return bool(record_lists) and all(
        all(isinstance(record.get("source"), str) and record["source"].startswith("fixture:") for record in records)
        for records in record_lists
    )


def _content_findings(path: Path, display_path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    if _LOCAL_PATH_RE.search(text):
        findings.append(
            Finding("local_path_marker", display_path, "Remove local filesystem paths from release resources.")
        )
    if _PRIVATE_COURSE_RE.search(text):
        findings.append(
            Finding("private_course_marker", display_path, "Private course material is not an allowed fixture source.")
        )
    if any(pattern.search(text) for pattern in _CREDENTIAL_PATTERNS):
        findings.append(
            Finding("credential_material", display_path, "Replace credential-like material with a non-secret placeholder.")
        )
    return findings


def scan_resources(
    paths: Iterable[Path],
    *,
    kind: ResourceKind,
    max_bytes: int = DEFAULT_MAX_BYTES,
    educational_allowlist: set[Path] | frozenset[Path] | None = None,
    display_root: Path | None = None,
) -> ScanReport:
    """Scan explicit fixture or preview paths without following symlinks."""

    if kind not in _ALLOWED_EXTENSIONS:
        raise ValueError(f"unknown resource kind: {kind}")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    allowlist = {path.resolve() for path in (educational_allowlist or set())}
    findings: list[Finding] = []
    resources = _iter_resource_paths(paths)

    for path in resources:
        display_path = _display_path(path, display_root)
        if path.is_symlink():
            findings.append(Finding("symlink_forbidden", display_path, "Copy a verified regular file instead."))
            continue
        if not path.exists() or not path.is_file():
            findings.append(Finding("resource_missing", display_path, "Expected resource is missing or not a regular file."))
            continue
        if path.suffix.lower() not in _ALLOWED_EXTENSIONS[kind]:
            findings.append(
                Finding("unexpected_extension", display_path, f"Allowed {kind} extensions: {sorted(_ALLOWED_EXTENSIONS[kind])}.")
            )
            continue
        size = path.stat().st_size
        if size > max_bytes:
            findings.append(
                Finding("file_too_large", display_path, f"File is {size} bytes; the limit is {max_bytes} bytes.")
            )
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("non_utf8_resource", display_path, "Release resources must be UTF-8 text."))
            continue

        findings.extend(_content_findings(path, display_path, text))

        if kind != "fixture" or path.resolve() in allowlist:
            continue
        if path.suffix.lower() == ".json":
            try:
                document = json.loads(text)
            except json.JSONDecodeError:
                findings.append(Finding("invalid_json", display_path, "Fixture JSON must parse without recovery."))
                continue
            if not _has_synthetic_json_metadata(document):
                findings.append(
                    Finding(
                        "synthetic_metadata_missing",
                        display_path,
                        "Add synthetic=true or the recognized deterministic fixture metadata.",
                    )
                )
        elif not _TEXT_SYNTHETIC_RE.search(text):
            findings.append(
                Finding(
                    "synthetic_metadata_missing",
                    display_path,
                    "Add an explicit synthetic/fixture marker or an exact educational allowlist entry.",
                )
            )

    return ScanReport(
        files_scanned=len(resources),
        findings=tuple(sorted(findings, key=lambda finding: (finding.path, finding.code))),
    )


def _scan_provenance_sources(repo_root: Path, *, max_bytes: int) -> ScanReport:
    """Scan publishable docs and Python source for private provenance markers."""

    inputs = [
        path
        for path in (repo_root / "accounting_agent", repo_root / "docs", repo_root / "scripts")
        if path.exists() or path.is_symlink()
    ]
    inputs.extend(sorted(repo_root.glob("*.md")))
    pyproject = repo_root / "pyproject.toml"
    if pyproject.exists() or pyproject.is_symlink():
        inputs.append(pyproject)

    findings: list[Finding] = []
    files_scanned = 0
    for path in _iter_resource_paths(inputs):
        display_path = _display_path(path, repo_root)
        if display_path in _PROVENANCE_SCAN_EXEMPTIONS:
            continue
        if path.is_symlink():
            findings.append(
                Finding("symlink_forbidden", display_path, "Publishable source must be a regular file.")
            )
            continue
        if not path.is_file() or path.suffix.lower() not in _PROVENANCE_SOURCE_EXTENSIONS:
            continue
        files_scanned += 1
        if path.stat().st_size > max_bytes:
            findings.append(
                Finding(
                    "file_too_large",
                    display_path,
                    f"File exceeds the provenance scan limit of {max_bytes} bytes.",
                )
            )
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(
                Finding("non_utf8_resource", display_path, "Publishable source must be UTF-8 text.")
            )
            continue
        if _SOURCE_LOCAL_PATH_RE.search(text):
            findings.append(
                Finding(
                    "local_path_marker",
                    display_path,
                    "Remove user-home and download paths from publishable source.",
                )
            )
        if _PRIVATE_COURSE_RE.search(text):
            findings.append(
                Finding(
                    "private_course_marker",
                    display_path,
                    "Private course provenance is forbidden in publishable source.",
                )
            )

    return ScanReport(
        files_scanned=files_scanned,
        findings=tuple(sorted(findings, key=lambda finding: (finding.path, finding.code))),
    )


def scan_repository(
    repo_root: Path,
    *,
    preview_root: Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    educational_allowlist: set[Path] | frozenset[Path] | None = None,
) -> ScanReport:
    """Scan the repository fixture trees, preview source assets, and an optional built preview."""

    repo_root = Path(repo_root).absolute()
    fixture_inputs = [
        path
        for path in (repo_root / "fixtures", repo_root / "accounting_agent" / "fixtures")
        if path.exists() or path.is_symlink()
    ]
    preview_inputs = [
        path
        for path in (
            repo_root / "accounting_agent" / "static",
            repo_root / "tokens.css",
            repo_root / "favicon.svg",
        )
        if path.exists() or path.is_symlink()
    ]
    fixture_report = scan_resources(
        fixture_inputs,
        kind="fixture",
        max_bytes=max_bytes,
        educational_allowlist=educational_allowlist,
        display_root=repo_root,
    )
    preview_report = scan_resources(
        preview_inputs,
        kind="preview",
        max_bytes=max_bytes,
        display_root=repo_root,
    )
    reports = [fixture_report, preview_report]
    reports.append(_scan_provenance_sources(repo_root, max_bytes=max_bytes))
    if preview_root is not None:
        reports.append(
            scan_resources(
                [Path(preview_root)],
                kind="preview",
                max_bytes=max_bytes,
                display_root=Path(preview_root),
            )
        )

    files_scanned = sum(report.files_scanned for report in reports)
    findings = [finding for report in reports for finding in report.findings]
    if files_scanned == 0:
        findings.append(Finding("no_resources", ".", "No fixture or preview resources were found."))
    return ScanReport(
        files_scanned=files_scanned,
        findings=tuple(sorted(findings, key=lambda finding: (finding.path, finding.code))),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (defaults to the parent of scripts/).",
    )
    parser.add_argument("--preview-root", type=Path, help="Optional generated public-preview directory.")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--allow-educational",
        action="append",
        default=[],
        metavar="RELATIVE_PATH",
        help="Exact repository-relative educational asset allowed to omit synthetic metadata.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the machine-readable report to this release-evidence path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.absolute()
    allowlist = {
        (repo_root / relative_path).resolve()
        for relative_path in args.allow_educational
        if not Path(relative_path).is_absolute()
    }
    report = scan_repository(
        repo_root,
        preview_root=args.preview_root,
        max_bytes=args.max_bytes,
        educational_allowlist=allowlist,
    )
    payload = {
        "ok": report.ok,
        "files_scanned": report.files_scanned,
        "findings": [
            {"code": finding.code, "path": finding.path, "detail": finding.detail}
            for finding in report.findings
        ],
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif report.ok:
        print(f"Fixture policy passed: {report.files_scanned} resources scanned.")
    else:
        print(f"Fixture policy failed: {len(report.findings)} finding(s) in {report.files_scanned} resources.")
        for finding in report.findings:
            print(f"- {finding.path}: {finding.code}: {finding.detail}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
