from __future__ import annotations

import gzip
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.package_release_check import (
    EXPECTED_CLI_COMMANDS,
    PackageReleaseError,
    _normalize_sdist,
    _run_clean_installed_sdist_cli_matrix,
    _validate_wheel_duplicate_allowlist,
    compare_builds,
)


class PackageReleaseCheckTests(unittest.TestCase):
    def test_sdist_uses_clean_venv_and_runs_complete_offline_cli_matrix(self) -> None:
        calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

        def capture(
            command: tuple[str, ...],
            *,
            cwd: Path,
            env: dict[str, str],
        ) -> None:
            calls.append((command, cwd, env))

        with tempfile.TemporaryDirectory() as directory:
            sdist = Path(directory) / "accounting_agent-1.0.0.tar.gz"
            sdist.write_bytes(b"synthetic sdist placeholder")
            with (
                patch("scripts.package_release_check._run", side_effect=capture),
                patch("scripts.package_release_check.shutil.which", return_value="/usr/bin/uv"),
            ):
                _run_clean_installed_sdist_cli_matrix(
                    sdist,
                    environment={
                        "PATH": "/usr/bin",
                        "PYTHONPATH": "/contaminated/source-checkout",
                        "VIRTUAL_ENV": "/contaminated/active-venv",
                    },
                )

        self.assertEqual(21, len(calls))
        self.assertEqual(("/usr/bin/uv", "venv"), calls[0][0][:2])
        self.assertIn("--offline", calls[0][0])
        self.assertEqual(("/usr/bin/uv", "pip", "install"), calls[1][0][:3])
        self.assertIn("setuptools", " ".join(calls[1][0]))
        self.assertEqual(("/usr/bin/uv", "pip", "install"), calls[2][0][:3])
        self.assertIn("--offline", calls[2][0])
        self.assertIn("--no-build-isolation", calls[2][0])
        self.assertIn("--no-deps", calls[2][0])
        self.assertEqual(sdist.resolve(), Path(calls[2][0][-1]))

        cli_calls = [
            call
            for call in calls
            if len(call[0]) >= 4 and call[0][1:3] == ("-m", "accounting_agent.cli")
        ]
        self.assertEqual(18, len(cli_calls))
        help_commands = {command[3] for command, _, _ in cli_calls if command[-1] == "--help"}
        execution_commands = {command[3] for command, _, _ in cli_calls if command[-1] != "--help"}
        self.assertEqual(EXPECTED_CLI_COMMANDS, help_commands)
        self.assertEqual(EXPECTED_CLI_COMMANDS, execution_commands)
        for _, _, environment in cli_calls:
            self.assertEqual("1", environment["PYTHONNOUSERSITE"])
            self.assertEqual("1", environment["ACCOUNTING_AGENT_TEST_OFFLINE"])
            self.assertEqual("1", environment["UV_OFFLINE"])
            self.assertEqual("1", environment["PIP_NO_INDEX"])
            self.assertNotIn("/contaminated/source-checkout", environment["PYTHONPATH"])
            self.assertNotIn("VIRTUAL_ENV", environment)

    def test_identical_dual_builds_return_stable_artifact_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            for name, payload in (
                ("accounting_agent-1.0.0-py3-none-any.whl", b"wheel"),
                ("accounting_agent-1.0.0.tar.gz", b"sdist"),
            ):
                (first / name).write_bytes(payload)
                (second / name).write_bytes(payload)

            hashes = compare_builds(first, second)

        self.assertEqual(2, len(hashes))
        self.assertEqual(64, len(next(iter(hashes.values()))))

    def test_changed_or_missing_artifact_fails_reproducibility_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            name = "accounting_agent-1.0.0-py3-none-any.whl"
            (first / name).write_bytes(b"first")
            (second / name).write_bytes(b"second")

            with self.assertRaisesRegex(PackageReleaseError, "not reproducible"):
                compare_builds(first, second)

    def test_sdist_normalization_removes_order_and_timestamp_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.tar.gz"
            second = root / "second.tar.gz"
            entries = (
                ("accounting_agent-1.0.0/README.md", b"synthetic readme\n"),
                ("accounting_agent-1.0.0/pyproject.toml", b"[project]\n"),
            )
            for path, order, timestamp in (
                (first, entries, 1_700_000_000),
                (second, tuple(reversed(entries)), 1_800_000_000),
            ):
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode="w") as archive:
                    for name, payload in order:
                        member = tarfile.TarInfo(name)
                        member.size = len(payload)
                        member.mtime = timestamp
                        member.uid = 501
                        member.gid = 20
                        member.uname = "synthetic-user"
                        archive.addfile(member, io.BytesIO(payload))
                with path.open("wb") as raw:
                    with gzip.GzipFile(
                        filename="",
                        mode="wb",
                        fileobj=raw,
                        mtime=timestamp,
                    ) as compressed:
                        compressed.write(buffer.getvalue())

            _normalize_sdist(first, source_date_epoch="1752192000")
            _normalize_sdist(second, source_date_epoch="1752192000")

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_wheel_duplicate_allowlist_is_exact_and_fail_closed(self) -> None:
        expected = (
            "accounting_agent/fixtures/microsoft365_intake/acme_invoice_001.txt",
            "accounting_agent/fixtures/microsoft365_intake/acme_invoice_001_hash_copy.txt",
        )
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "synthetic.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                for name in expected:
                    archive.writestr(name, b"synthetic duplicate fixture")
                archive.writestr("accounting_agent/__init__.py", b"unique")

            _validate_wheel_duplicate_allowlist(wheel)

            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr(
                    "accounting_agent/unexpected_copy.py",
                    b"synthetic duplicate fixture",
                )
            with self.assertRaisesRegex(PackageReleaseError, "unexpected duplicate"):
                _validate_wheel_duplicate_allowlist(wheel)


if __name__ == "__main__":
    unittest.main()
