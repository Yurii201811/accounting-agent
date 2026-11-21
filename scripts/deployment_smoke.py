#!/usr/bin/env python3
"""Verify that a deployed synthetic preview exactly matches its local bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FILES = frozenset(
    {
        "index.html",
        "tokens.css",
        "favicon.svg",
        "LICENSE.lucide.txt",
        "preview-manifest.json",
    }
)
MAXIMUM_FILE_BYTES = 5 * 1024 * 1024


class DeploymentSmokeError(RuntimeError):
    """Raised when preview transport or artifact equality cannot be proven."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_target(target: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(target)
        port = parsed.port
    except ValueError as exc:
        raise DeploymentSmokeError(
            "Deployment smoke target must use a plain public Vercel origin"
        ) from exc
    if parsed.scheme.casefold() != "https":
        raise DeploymentSmokeError("Deployment smoke target must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password:
        raise DeploymentSmokeError("Deployment smoke target must have a plain public origin")
    hostname = parsed.hostname.casefold()
    if (
        not hostname.endswith(".vercel.app")
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise DeploymentSmokeError(
            "Deployment smoke target must use a plain public Vercel origin"
        )
    return target.rstrip("/")


def _verify_local_bundle(bundle: Path) -> dict[str, Any]:
    if not bundle.is_dir() or bundle.is_symlink():
        raise DeploymentSmokeError(f"Preview bundle is not a regular directory: {bundle}")
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual != EXPECTED_FILES:
        raise DeploymentSmokeError(
            "Preview bundle must contain exactly five public files; "
            f"found {sorted(actual)}"
        )
    if any(path.is_symlink() for path in bundle.rglob("*")):
        raise DeploymentSmokeError("Preview bundle must not contain symlinks")
    try:
        manifest = json.loads(
            (bundle / "preview-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise DeploymentSmokeError("Preview manifest is missing or invalid") from exc
    if manifest.get("synthetic_data_only") is not True:
        raise DeploymentSmokeError("Preview manifest does not prove synthetic-only data")
    declared = dict(manifest.get("files") or {})
    for name in EXPECTED_FILES - {"preview-manifest.json"}:
        metadata = declared.get(name)
        payload = (bundle / name).read_bytes()
        if not isinstance(metadata, dict) or metadata.get("sha256") != _sha256(payload):
            raise DeploymentSmokeError(f"Local manifest hash mismatch for {name}")
    return manifest


def _fetch(url: str, maximum_bytes: int) -> bytes:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirects(),
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Accounting-Agent-v1-release-smoke/1.0"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise DeploymentSmokeError(f"Preview returned HTTP {response.status}")
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > maximum_bytes:
                raise DeploymentSmokeError("Preview response exceeds the bounded size")
            payload = response.read(maximum_bytes + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise DeploymentSmokeError(f"Preview request failed: {type(exc).__name__}") from exc
    if len(payload) > maximum_bytes:
        raise DeploymentSmokeError("Preview response exceeds the bounded size")
    return payload


def run_deployment_smoke(
    *,
    target: str,
    bundle: str | Path,
    fetch: Callable[[str, int], bytes] = _fetch,
) -> dict[str, Any]:
    """Compare every deployed public file byte-for-byte with the local artifact."""

    base_url = _validate_target(target)
    bundle_path = Path(bundle).resolve()
    _verify_local_bundle(bundle_path)
    mismatches: list[str] = []
    file_hashes: dict[str, dict[str, str | bool]] = {}
    for name in sorted(EXPECTED_FILES):
        local_payload = (bundle_path / name).read_bytes()
        remote_url = f"{base_url}/{urllib.parse.quote(name, safe='')}"
        remote_payload = fetch(remote_url, MAXIMUM_FILE_BYTES)
        local_sha256 = _sha256(local_payload)
        remote_sha256 = _sha256(remote_payload)
        match = remote_sha256 == local_sha256
        file_hashes[name] = {
            "local_sha256": local_sha256,
            "remote_sha256": remote_sha256,
            "match": match,
        }
        if not match:
            mismatches.append(name)
    if mismatches:
        raise DeploymentSmokeError(
            "Deployed preview hash mismatch: " + ", ".join(mismatches)
        )
    return {
        "schema_version": 1,
        "target": base_url,
        "files_verified": len(EXPECTED_FILES),
        "file_hashes": file_hashes,
        "hash_mismatches": mismatches,
        "synthetic_data_only": True,
        "external_authority": False,
    }


def write_deployment_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    target = os.environ.get("ACCOUNTING_AGENT_PREVIEW_URL", "").strip()
    if not target:
        print(
            "ACCOUNTING_AGENT_PREVIEW_URL is required for the release deployment smoke",
            file=sys.stderr,
        )
        return 2
    bundle = Path(
        os.environ.get(
            "ACCOUNTING_AGENT_PREVIEW_BUNDLE",
            str(ROOT / ".local" / "accounting-agent-v1-preview-release"),
        )
    )
    try:
        summary = run_deployment_smoke(target=target, bundle=bundle)
    except DeploymentSmokeError as exc:
        print(f"deployment smoke: {exc}", file=sys.stderr)
        return 1
    if args.output is not None:
        write_deployment_summary(args.output, summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
