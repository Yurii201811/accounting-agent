#!/usr/bin/env python3
"""Build, reproduce, inspect, and clean-install Accounting Agent artifacts."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DATE_EPOCH = "1752192000"
EXPECTED_DUPLICATE_WHEEL_GROUPS = frozenset(
    {
        frozenset(
            {
                "accounting_agent/fixtures/microsoft365_intake/acme_invoice_001.txt",
                "accounting_agent/fixtures/microsoft365_intake/acme_invoice_001_hash_copy.txt",
            }
        )
    }
)
EXPECTED_CLI_COMMANDS = frozenset(
    {
        "process-fixtures",
        "reconcile-bank-fixtures",
        "scan-intake-folder",
        "demo-supplier-invoice-autopilot",
        "fake-client-dry-run",
        "build-operations-cockpit",
        "build-public-preview",
        "platform-status",
        "v1-system-check",
    }
)


class PackageReleaseError(RuntimeError):
    """Raised when a distribution artifact fails a release contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_paths(directory: Path) -> dict[str, Path]:
    return {
        path.name: path
        for path in sorted(directory.iterdir())
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    }


def compare_builds(first: Path, second: Path) -> dict[str, str]:
    """Return hashes only when the two build directories are byte-identical."""

    first_artifacts = _artifact_paths(first)
    second_artifacts = _artifact_paths(second)
    if set(first_artifacts) != set(second_artifacts) or not first_artifacts:
        raise PackageReleaseError("Dual build artifact set is not reproducible")
    hashes: dict[str, str] = {}
    for name, first_path in first_artifacts.items():
        first_hash = _sha256(first_path)
        second_hash = _sha256(second_artifacts[name])
        if first_hash != second_hash:
            raise PackageReleaseError(f"Artifact is not reproducible: {name}")
        hashes[name] = first_hash
    return hashes


def _normalize_sdist(path: Path, *, source_date_epoch: str) -> None:
    """Rewrite an sdist with canonical tar metadata and gzip headers."""

    try:
        epoch = int(source_date_epoch)
    except ValueError as exc:
        raise PackageReleaseError("SOURCE_DATE_EPOCH must be an integer") from exc
    if epoch < 0:
        raise PackageReleaseError("SOURCE_DATE_EPOCH must be non-negative")

    entries: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(path, mode="r:gz") as source:
        seen: set[str] = set()
        for member in source.getmembers():
            member_path = Path(member.name)
            if member.name in seen or member_path.is_absolute() or ".." in member_path.parts:
                raise PackageReleaseError("sdist contains an unsafe or duplicate path")
            seen.add(member.name)
            payload: bytes | None = None
            if member.isfile():
                extracted = source.extractfile(member)
                if extracted is None:
                    raise PackageReleaseError("sdist file content could not be read")
                with extracted:
                    payload = extracted.read()
            normalized = copy.copy(member)
            normalized.mtime = epoch
            normalized.uid = 0
            normalized.gid = 0
            normalized.uname = ""
            normalized.gname = ""
            normalized.pax_headers = {}
            entries.append((normalized, payload))

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as raw:
            temporary_path = Path(raw.name)
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw,
                compresslevel=9,
                mtime=epoch,
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as destination:
                    for member, payload in sorted(entries, key=lambda item: item[0].name):
                        destination.addfile(
                            member,
                            None if payload is None else io.BytesIO(payload),
                        )
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _validate_wheel_duplicate_allowlist(wheel: Path) -> None:
    """Allow only the exact duplicate pair used by the synthetic dedupe test."""

    names_by_hash: dict[str, set[str]] = {}
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.file_size == 0:
                continue
            payload_hash = hashlib.sha256(archive.read(info)).hexdigest()
            names_by_hash.setdefault(payload_hash, set()).add(info.filename)
    duplicate_groups = frozenset(
        frozenset(names) for names in names_by_hash.values() if len(names) > 1
    )
    if duplicate_groups != EXPECTED_DUPLICATE_WHEEL_GROUPS:
        raise PackageReleaseError(
            "wheel contains an unexpected duplicate-file group or is missing the "
            "documented synthetic duplicate fixture"
        )


def _copy_source_snapshot(destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git",
        ".local",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "*.egg-info",
        ".coverage*",
        "build",
        "dist",
        "node_modules",
        "playwright-report",
        "test-results",
    )
    shutil.copytree(ROOT, destination, ignore=ignored)


def _run(command: tuple[str, ...], *, cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip()
        tail = "\n".join(output.splitlines()[-50:])
        raise PackageReleaseError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{tail}"
        )


def _installed_cli_matrix(workspace: Path) -> tuple[tuple[str, ...], ...]:
    return (
        (
            "process-fixtures",
            "--db",
            str(workspace / "supplier.sqlite"),
            "--output",
            str(workspace / "supplier-packets"),
        ),
        (
            "reconcile-bank-fixtures",
            "--output",
            str(workspace / "bank-packets"),
        ),
        (
            "scan-intake-folder",
            "--db",
            str(workspace / "intake.sqlite"),
            "--storage",
            str(workspace / "intake-storage"),
        ),
        (
            "demo-supplier-invoice-autopilot",
            "--output",
            str(workspace / "demo"),
        ),
        (
            "fake-client-dry-run",
            "--output",
            str(workspace / "fake-client"),
            "--report",
            str(workspace / "fake-client-report.md"),
        ),
        (
            "build-operations-cockpit",
            "--output",
            str(workspace / "cockpit.html"),
        ),
        (
            "build-public-preview",
            "--output",
            str(workspace / "preview"),
        ),
        ("platform-status", "--json"),
        ("v1-system-check", "--json"),
    )


def _clean_artifact_environment(environment: dict[str, str]) -> dict[str, str]:
    clean = environment.copy()
    for variable in (
        "ACCOUNTING_AGENT_TEST_SDIST",
        "ACCOUNTING_AGENT_TEST_WHEEL",
        "PYTHONHOME",
        "VIRTUAL_ENV",
    ):
        clean.pop(variable, None)
    clean["ACCOUNTING_AGENT_TEST_OFFLINE"] = "1"
    clean["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    clean["PIP_NO_INDEX"] = "1"
    clean["PYTHONHASHSEED"] = "0"
    clean["PYTHONNOUSERSITE"] = "1"
    clean["PYTHONPATH"] = str(ROOT / "tests" / "offline_guard")
    clean["TZ"] = "UTC"
    clean["UV_OFFLINE"] = "1"
    return clean


def _run_clean_installed_sdist_cli_matrix(
    sdist: Path,
    *,
    environment: dict[str, str],
) -> None:
    """Install the sdist into an isolated venv and exercise every CLI surface."""

    sdist = sdist.resolve()
    if not sdist.is_file() or not sdist.name.endswith(".tar.gz"):
        raise PackageReleaseError(f"Source distribution is missing or invalid: {sdist}")
    uv = shutil.which("uv")
    if uv is None:
        raise PackageReleaseError("uv is required for the offline clean-sdist gate")
    try:
        setuptools_requirement = f"setuptools=={version('setuptools')}"
    except PackageNotFoundError as exc:
        raise PackageReleaseError(
            "The release environment must provide the locked setuptools build backend"
        ) from exc

    clean_environment = _clean_artifact_environment(environment)
    with tempfile.TemporaryDirectory(prefix="accounting-agent-sdist-install-") as directory:
        root = Path(directory)
        virtual_environment = root / "venv"
        workspace = root / "workspace"
        workspace.mkdir()
        venv_python = (
            virtual_environment / "Scripts" / "python.exe"
            if os.name == "nt"
            else virtual_environment / "bin" / "python"
        )
        _run(
            (
                uv,
                "venv",
                "--offline",
                "--python",
                sys.executable,
                str(virtual_environment),
            ),
            cwd=root,
            env=clean_environment,
        )
        _run(
            (
                uv,
                "pip",
                "install",
                "--offline",
                "--python",
                str(venv_python),
                "--no-deps",
                setuptools_requirement,
            ),
            cwd=workspace,
            env=clean_environment,
        )
        _run(
            (
                uv,
                "pip",
                "install",
                "--offline",
                "--python",
                str(venv_python),
                "--no-build-isolation",
                "--no-deps",
                str(sdist),
            ),
            cwd=workspace,
            env=clean_environment,
        )

        for command_name in sorted(EXPECTED_CLI_COMMANDS):
            _run(
                (
                    str(venv_python),
                    "-m",
                    "accounting_agent.cli",
                    command_name,
                    "--help",
                ),
                cwd=workspace,
                env=clean_environment,
            )
        matrix = _installed_cli_matrix(workspace)
        if {command[0] for command in matrix} != EXPECTED_CLI_COMMANDS:
            raise PackageReleaseError("Installed sdist CLI matrix does not cover nine commands")
        for command in matrix:
            _run(
                (str(venv_python), "-m", "accounting_agent.cli", *command),
                cwd=workspace,
                env=clean_environment,
            )


def run_release_check(*, output: Path, source_date_epoch: str) -> dict[str, object]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for existing in output.iterdir():
        if existing.is_file() and (
            existing.suffix == ".whl"
            or existing.name.endswith(".tar.gz")
            or existing.name == "package-summary.json"
        ):
            existing.unlink()

    environment = os.environ.copy()
    environment["SOURCE_DATE_EPOCH"] = source_date_epoch
    environment["PYTHONHASHSEED"] = "0"
    environment["TZ"] = "UTC"
    with tempfile.TemporaryDirectory(prefix="accounting-agent-release-") as directory:
        temporary = Path(directory)
        build_dirs: list[Path] = []
        for index in (1, 2):
            source = temporary / f"source-{index}"
            artifacts = temporary / f"artifacts-{index}"
            _copy_source_snapshot(source)
            artifacts.mkdir()
            _run(
                (
                    sys.executable,
                    "-m",
                    "build",
                    "--no-isolation",
                    "--outdir",
                    str(artifacts),
                    ".",
                ),
                cwd=source,
                env=environment,
            )
            for artifact in _artifact_paths(artifacts).values():
                if artifact.name.endswith(".tar.gz"):
                    _normalize_sdist(
                        artifact,
                        source_date_epoch=source_date_epoch,
                    )
            build_dirs.append(artifacts)

        hashes = compare_builds(*build_dirs)
        first_artifacts = _artifact_paths(build_dirs[0])
        for artifact in first_artifacts.values():
            shutil.copy2(artifact, output / artifact.name)

    wheel = next(path for path in output.iterdir() if path.suffix == ".whl")
    sdist = next(path for path in output.iterdir() if path.name.endswith(".tar.gz"))
    _run(
        (sys.executable, "-m", "twine", "check", str(wheel), str(sdist)),
        cwd=ROOT,
        env=environment,
    )
    _validate_wheel_duplicate_allowlist(wheel)
    _run(
        ("check-wheel-contents", "--ignore", "W002", str(wheel)),
        cwd=ROOT,
        env=environment,
    )
    artifact_test_environment = environment.copy()
    artifact_test_environment["ACCOUNTING_AGENT_TEST_WHEEL"] = str(wheel)
    artifact_test_environment["ACCOUNTING_AGENT_TEST_SDIST"] = str(sdist)
    _run(
        (
            sys.executable,
            "-m",
            "unittest",
            "tests.test_cli_distribution.DistributionArtifactTests",
            "-v",
        ),
        cwd=ROOT,
        env=artifact_test_environment,
    )
    _run_clean_installed_sdist_cli_matrix(sdist, environment=environment)

    summary: dict[str, object] = {
        "schema_version": 1,
        "source_date_epoch": source_date_epoch,
        "reproducible": True,
        "artifacts": {
            name: {"sha256": digest, "bytes": (output / name).stat().st_size}
            for name, digest in sorted(hashes.items())
        },
        "twine_check": "passed",
        "wheel_content_check": "passed",
        "wheel_duplicate_allowlist_check": "passed",
        "clean_install_cli_matrix": "passed",
        "sdist_clean_install_cli_matrix": "passed",
        "sdist_self_tests": "passed",
    }
    (output / "package-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".local" / "qa" / "package",
    )
    parser.add_argument(
        "--source-date-epoch",
        default=DEFAULT_SOURCE_DATE_EPOCH,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        summary = run_release_check(
            output=args.output,
            source_date_epoch=args.source_date_epoch,
        )
    except (
        OSError,
        PackageReleaseError,
        StopIteration,
        subprocess.SubprocessError,
        tarfile.TarError,
    ) as exc:
        print(f"package release: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
