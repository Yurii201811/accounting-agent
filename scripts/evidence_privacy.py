#!/usr/bin/env python3
"""Sanitize QA evidence and fail closed on residual machine-local identity."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
_TEXT_SUFFIXES = frozenset(
    {".css", ".html", ".js", ".json", ".lock", ".log", ".md", ".svg", ".txt", ".xml"}
)
_MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_ARCHIVE_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_EVIDENCE_FILE_BYTES = 256 * 1024 * 1024
_MAC_LINUX_HOME = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:file://)?/(?:Users|home)/[^/\\\s\"'<>]+"
)
_WINDOWS_HOME = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:file:///)?[a-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>]+"
)
_LOCAL_HOSTNAME = re.compile(
    r"(?i)\b[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}\.)+local\b"
)


class EvidencePrivacyError(RuntimeError):
    """Raised when the evidence tree cannot be inspected without escaping it."""


def _absolute_without_resolving(path: Path) -> Path:
    candidate = path if path.is_absolute() else Path.cwd() / path
    return Path(os.path.abspath(candidate))


def _relative_output_path(root: Path, output: Path) -> Path:
    root_absolute = _absolute_without_resolving(root)
    output_absolute = _absolute_without_resolving(output)
    try:
        relative = output_absolute.relative_to(root_absolute)
    except ValueError as error:
        raise EvidencePrivacyError("Privacy report must stay inside the evidence tree") from error
    if output_absolute.is_symlink():
        raise EvidencePrivacyError("Privacy report must not be a symlink")
    current = root_absolute
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise EvidencePrivacyError("Privacy report path must not contain symlinks")
    return relative


def _evidence_files(root: Path) -> tuple[Path, ...]:
    if root.is_symlink() or not root.is_dir():
        raise EvidencePrivacyError("Evidence root must be a regular directory, not a symlink")
    paths = tuple(sorted(root.rglob("*")))
    for path in paths:
        if path.is_symlink():
            raise EvidencePrivacyError(
                f"Evidence tree contains symlink: {path.relative_to(root).as_posix()}"
            )
    return tuple(path for path in paths if path.is_file())


def _replacement_pairs(
    root: Path,
    *,
    repo_root: Path,
    home: Path,
    hostname: str,
) -> tuple[tuple[str, str], ...]:
    raw = (
        (str(_absolute_without_resolving(root)), "<run>"),
        (str(repo_root), "<repo>"),
        (str(home), "<home>"),
        (hostname, "<host>"),
    )
    unique = {value: placeholder for value, placeholder in raw if value}
    return tuple(sorted(unique.items(), key=lambda item: len(item[0]), reverse=True))


def _sanitize_text(
    text: str,
    replacements: Iterable[tuple[str, str]],
) -> tuple[str, int]:
    sanitized = text
    replacement_count = 0
    for value, placeholder in replacements:
        count = sanitized.count(value)
        if count:
            sanitized = sanitized.replace(value, placeholder)
            replacement_count += count
    for pattern, placeholder in (
        (_WINDOWS_HOME, "<home>"),
        (_MAC_LINUX_HOME, "<home>"),
        (_LOCAL_HOSTNAME, "<host>"),
    ):
        sanitized, count = pattern.subn(placeholder, sanitized)
        replacement_count += count
    return sanitized, replacement_count


def _identity_findings(
    payload: bytes,
    *,
    replacements: Iterable[tuple[str, str]],
    file_name: str,
    member_name: str | None = None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for value, placeholder in replacements:
        if value.encode("utf-8") not in payload:
            continue
        finding = {
            "file": file_name,
            "kind": f"residual-{placeholder.strip('<>')}-identity",
        }
        if member_name is not None:
            finding["member"] = member_name
        findings.append(finding)
    return findings


def _archive_findings(
    path: Path,
    *,
    root: Path,
    replacements: tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    relative_name = path.relative_to(root).as_posix()
    findings: list[dict[str, str]] = []
    total_bytes = 0
    if path.suffix in {".whl", ".zip"}:
        try:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member.is_dir():
                        continue
                    if member_path.is_absolute() or ".." in member_path.parts:
                        findings.append(
                            {"file": relative_name, "kind": "unsafe-archive-path"}
                        )
                        continue
                    total_bytes += member.file_size
                    if (
                        member.file_size > _MAX_ARCHIVE_MEMBER_BYTES
                        or total_bytes > _MAX_ARCHIVE_TOTAL_BYTES
                    ):
                        findings.append(
                            {"file": relative_name, "kind": "archive-scan-bound-exceeded"}
                        )
                        break
                    findings.extend(
                        _identity_findings(
                            archive.read(member),
                            replacements=replacements,
                            file_name=relative_name,
                            member_name=member.filename,
                        )
                    )
        except (OSError, zipfile.BadZipFile):
            findings.append({"file": relative_name, "kind": "invalid-archive"})
        return findings

    if path.name.endswith(".tar.gz"):
        try:
            with tarfile.open(path, mode="r:gz") as archive:
                for member in archive.getmembers():
                    member_path = Path(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        findings.append(
                            {"file": relative_name, "kind": "unsafe-archive-path"}
                        )
                        continue
                    if member.issym() or member.islnk():
                        findings.append(
                            {"file": relative_name, "kind": "archive-link"}
                        )
                        continue
                    if not member.isfile():
                        continue
                    total_bytes += member.size
                    if (
                        member.size > _MAX_ARCHIVE_MEMBER_BYTES
                        or total_bytes > _MAX_ARCHIVE_TOTAL_BYTES
                    ):
                        findings.append(
                            {"file": relative_name, "kind": "archive-scan-bound-exceeded"}
                        )
                        break
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        findings.append(
                            {"file": relative_name, "kind": "unreadable-archive-member"}
                        )
                        continue
                    with extracted:
                        payload = extracted.read(_MAX_ARCHIVE_MEMBER_BYTES + 1)
                    findings.extend(
                        _identity_findings(
                            payload,
                            replacements=replacements,
                            file_name=relative_name,
                            member_name=member.name,
                        )
                    )
        except (OSError, tarfile.TarError):
            findings.append({"file": relative_name, "kind": "invalid-archive"})
    return findings


def sanitize_evidence_tree(
    root: Path,
    *,
    repo_root: Path = ROOT,
    home: Path | None = None,
    hostname: str | None = None,
) -> dict[str, object]:
    """Scrub text reports, inspect binaries/archives, and return a safe report."""

    root = _absolute_without_resolving(root)
    files = _evidence_files(root)
    raw_coverage_files = tuple(
        path
        for path in files
        if path.relative_to(root).parts[0] == "coverage"
        and path.name.startswith(".coverage")
    )
    for path in raw_coverage_files:
        path.unlink()
    files = tuple(path for path in files if path not in raw_coverage_files)
    replacements = _replacement_pairs(
        root,
        repo_root=repo_root,
        home=Path.home() if home is None else home,
        hostname=socket.gethostname() if hostname is None else hostname,
    )
    findings: list[dict[str, str]] = []
    files_sanitized = 0
    replacement_count = 0
    for path in files:
        relative_name = path.relative_to(root).as_posix()
        if path.stat().st_size > _MAX_EVIDENCE_FILE_BYTES:
            findings.append(
                {"file": relative_name, "kind": "file-scan-bound-exceeded"}
            )
            continue
        sanitized_name, name_replacements = _sanitize_text(relative_name, replacements)
        if name_replacements and sanitized_name != relative_name:
            findings.append({"file": relative_name, "kind": "private-path-component"})
        if path.suffix in _TEXT_SUFFIXES:
            try:
                original = path.read_text(encoding="utf-8")
            except UnicodeError:
                findings.extend(
                    _identity_findings(
                        path.read_bytes(),
                        replacements=replacements,
                        file_name=relative_name,
                    )
                )
                continue
            sanitized, count = _sanitize_text(original, replacements)
            if count:
                path.write_text(sanitized, encoding="utf-8")
                files_sanitized += 1
                replacement_count += count
            residual = sanitized.encode("utf-8")
            findings.extend(
                _identity_findings(
                    residual,
                    replacements=replacements,
                    file_name=relative_name,
                )
            )
            if _MAC_LINUX_HOME.search(sanitized) or _WINDOWS_HOME.search(sanitized):
                findings.append({"file": relative_name, "kind": "residual-local-path"})
            if _LOCAL_HOSTNAME.search(sanitized):
                findings.append({"file": relative_name, "kind": "residual-local-host"})
            continue

        if path.suffix in {".whl", ".zip"} or path.name.endswith(".tar.gz"):
            findings.extend(
                _archive_findings(path, root=root, replacements=replacements)
            )
        findings.extend(
            _identity_findings(
                path.read_bytes(),
                replacements=replacements,
                file_name=relative_name,
            )
        )

    unique_findings = [dict(items) for items in {tuple(item.items()) for item in findings}]
    unique_findings.sort(key=lambda item: (item["file"], item["kind"], item.get("member", "")))
    return {
        "schema_version": 1,
        "passed": not unique_findings,
        "files_scanned": len(files),
        "files_sanitized": files_sanitized,
        "raw_coverage_files_removed": len(raw_coverage_files),
        "replacement_count": replacement_count,
        "findings": unique_findings,
    }


def _write_report(root: Path, output: Path, report: dict[str, object]) -> None:
    relative = _relative_output_path(root, output)
    destination = _absolute_without_resolving(root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sanitize and audit QA evidence privacy")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = sanitize_evidence_tree(args.root)
        _write_report(args.root, args.output, report)
    except (EvidencePrivacyError, OSError) as error:
        print(f"Evidence privacy gate failed: {error}")
        return 1
    print(
        "Evidence privacy gate: "
        f"{report['files_scanned']} files scanned, "
        f"{report['files_sanitized']} sanitized, "
        f"{len(report['findings'])} findings"
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
