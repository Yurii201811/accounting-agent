from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from importlib import resources
from pathlib import Path

import accounting_agent.cli as cli


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_COMMANDS = {
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
EXPECTED_PACKAGED_FIXTURES = {
    "supplier_invoices": {
        "01_normal_25_vat.json",
        "02_possible_duplicate_invoice.json",
        "03_unknown_supplier.json",
        "04_changed_bank_details.json",
        "05_uncertain_vat_extraction.json",
    },
    "bank_reconciliation": {"bank_transactions.json", "open_items.json"},
    "microsoft365_intake": {
        "acme_invoice_001.txt",
        "acme_invoice_001_hash_copy.txt",
        "acme_invoice_001_metadata_duplicate.txt",
        "beta_receipt_002.txt",
    },
}


class CliContractTests(unittest.TestCase):
    def test_build_parser_exposes_exactly_the_nine_supported_commands(self) -> None:
        self.assertTrue(
            hasattr(cli, "build_parser"),
            "CLI must expose an internal build_parser() for contract discovery",
        )
        parser = cli.build_parser()
        subparser_action = next(
            action
            for action in parser._actions
            if getattr(action, "choices", None)
        )

        self.assertEqual(EXPECTED_COMMANDS, set(subparser_action.choices))

    def test_all_nine_commands_expose_actionable_help_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for command in sorted(EXPECTED_COMMANDS):
                with self.subTest(command=command):
                    result = _run_source_cli(root, command, "--help")
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("usage:", result.stdout.lower())
                    self.assertNotIn("Traceback", result.stderr)
            self.assertEqual([], list(root.iterdir()))

    def test_synthetic_fixtures_are_packaged_and_match_source_catalog(self) -> None:
        packaged_root = resources.files("accounting_agent").joinpath("fixtures")

        for category, expected_names in EXPECTED_PACKAGED_FIXTURES.items():
            with self.subTest(category=category):
                packaged_category = packaged_root.joinpath(category)
                self.assertTrue(packaged_category.is_dir())
                self.assertEqual(
                    expected_names,
                    {item.name for item in packaged_category.iterdir() if item.is_file()},
                )
                for name in expected_names:
                    self.assertEqual(
                        (ROOT / "fixtures" / category / name).read_bytes(),
                        packaged_category.joinpath(name).read_bytes(),
                    )

    def test_fixture_commands_use_packaged_defaults_outside_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            commands = (
                (
                    "process-fixtures",
                    "--db",
                    str(root / "supplier.sqlite"),
                    "--output",
                    str(root / "supplier-packets"),
                ),
                (
                    "reconcile-bank-fixtures",
                    "--output",
                    str(root / "bank-packets"),
                ),
                (
                    "scan-intake-folder",
                    "--db",
                    str(root / "intake.sqlite"),
                    "--storage",
                    str(root / "intake-storage"),
                ),
                (
                    "demo-supplier-invoice-autopilot",
                    "--output",
                    str(root / "demo"),
                ),
            )

            for command in commands:
                with self.subTest(command=command[0]):
                    result = _run_source_cli(root, *command)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_explicit_empty_fixture_inputs_fail_actionably_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty = root / "empty"
            empty.mkdir()
            cases = (
                (
                    (
                        "process-fixtures",
                        "--fixtures",
                        str(empty),
                        "--db",
                        str(root / "supplier.sqlite"),
                        "--output",
                        str(root / "supplier-packets"),
                    ),
                    "No supplier invoice .json fixtures found",
                    (root / "supplier.sqlite", root / "supplier-packets"),
                ),
                (
                    (
                        "reconcile-bank-fixtures",
                        "--fixtures",
                        str(empty),
                        "--output",
                        str(root / "bank-packets"),
                    ),
                    "Bank fixture folder is incomplete",
                    (root / "bank-packets",),
                ),
                (
                    (
                        "scan-intake-folder",
                        "--folder",
                        str(empty),
                        "--db",
                        str(root / "intake.sqlite"),
                        "--storage",
                        str(root / "intake-storage"),
                    ),
                    "No local intake files found",
                    (root / "intake.sqlite", root / "intake-storage"),
                ),
                (
                    (
                        "demo-supplier-invoice-autopilot",
                        "--fixtures",
                        str(empty),
                        "--output",
                        str(root / "demo"),
                    ),
                    "No supplier invoice .json fixtures found",
                    (root / "demo",),
                ),
            )

            for command, message, forbidden_paths in cases:
                with self.subTest(command=command[0]):
                    result = _run_source_cli(root, *command)
                    self.assertEqual(1, result.returncode)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    for path in forbidden_paths:
                        self.assertFalse(path.exists(), path)

    def test_missing_fixture_inputs_fail_actionably_without_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing = root / "missing"
            cases = (
                ("process-fixtures", "--fixtures", str(missing)),
                ("reconcile-bank-fixtures", "--fixtures", str(missing)),
                ("scan-intake-folder", "--folder", str(missing)),
                ("demo-supplier-invoice-autopilot", "--fixtures", str(missing)),
            )

            for command in cases:
                with self.subTest(command=command[0]):
                    result = _run_source_cli(root, *command)
                    self.assertEqual(1, result.returncode)
                    self.assertIn("does not exist", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)


class DistributionArtifactTests(unittest.TestCase):
    def test_wheel_contains_runtime_resources(self) -> None:
        wheel = _artifact_from_env("ACCOUNTING_AGENT_TEST_WHEEL", ".whl")
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())

        for category, fixture_names in EXPECTED_PACKAGED_FIXTURES.items():
            for name in fixture_names:
                self.assertIn(f"accounting_agent/fixtures/{category}/{name}", names)

    def test_sdist_contains_self_tests_helpers_docs_and_resources(self) -> None:
        sdist = _artifact_from_env("ACCOUNTING_AGENT_TEST_SDIST", ".tar.gz")
        with tarfile.open(sdist, "r:gz") as archive:
            names = {
                "/".join(Path(name).parts[1:])
                for name in archive.getnames()
                if len(Path(name).parts) > 1
            }

        required = {
            ".gitignore",
            ".github/dependabot.yml",
            ".github/workflows/qa.yml",
            "tests/__init__.py",
            "tests/permit_approval_helpers.py",
            "tests/test_cli_distribution.py",
            "fixtures/supplier_invoices/01_normal_25_vat.json",
            "accounting_agent/fixtures/supplier_invoices/01_normal_25_vat.json",
            "docs/accounting_agent_v1.md",
            "config/fortnox.env.example",
            "package-lock.json",
            "package.json",
            "playwright.config.ts",
            "qa/traceability.json",
            "qa/coverage-baseline.json",
            "scripts/qa.py",
            "scripts/coverage_gate.py",
            "scripts/fixture_policy.py",
            "spec/spec-process-cicd-qa.md",
            "tests/ui/VOICEOVER_CHECKLIST.md",
            "tests/ui/cockpit-interactions.spec.ts",
            "tokens.css",
            "uv.lock",
            "favicon.svg",
        }
        self.assertTrue(required <= names, sorted(required - names))

    def test_sdist_runs_its_included_python_self_tests(self) -> None:
        sdist = _artifact_from_env("ACCOUNTING_AGENT_TEST_SDIST", ".tar.gz")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with tarfile.open(sdist, "r:gz") as archive:
                archive.extractall(root, filter="data")
            source_root = next(path for path in root.iterdir() if path.is_dir())
            environment = os.environ.copy()
            environment.pop("ACCOUNTING_AGENT_TEST_SDIST", None)
            environment.pop("ACCOUNTING_AGENT_TEST_WHEEL", None)
            environment["PYTHONPATH"] = str(source_root)
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=source_root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_clean_installed_wheel_runs_all_nine_cli_commands(self) -> None:
        wheel = _artifact_from_env("ACCOUNTING_AGENT_TEST_WHEEL", ".whl")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            site = root / "site"
            install = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-deps",
                    "--target",
                    str(site),
                    str(wheel),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            uv = shutil.which("uv")
            if install.returncode != 0 and uv and "No module named pip" in install.stderr:
                install = subprocess.run(
                    [
                        uv,
                        "pip",
                        "install",
                        "--python",
                        sys.executable,
                        "--no-deps",
                        "--target",
                        str(site),
                        str(wheel),
                    ],
                    cwd=root,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            self.assertEqual(0, install.returncode, install.stderr)

            commands = _all_cli_commands(root)
            for command_name in sorted(EXPECTED_COMMANDS):
                with self.subTest(command=f"{command_name} --help"):
                    result = _run_installed_cli(root, site, command_name, "--help")
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertIn("usage:", result.stdout.lower())
                    self.assertNotIn("Traceback", result.stderr)
            for command in commands:
                with self.subTest(command=command[0]):
                    result = _run_installed_cli(root, site, *command)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)


def _run_source_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT), environment.get("PYTHONPATH", "")) if part
    )
    return subprocess.run(
        [sys.executable, "-m", "accounting_agent.cli", *args],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_installed_cli(
    cwd: Path,
    site: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(site)
    environment["PYTHONNOUSERSITE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "accounting_agent.cli", *args],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _all_cli_commands(root: Path) -> tuple[tuple[str, ...], ...]:
    return (
        (
            "process-fixtures",
            "--db",
            str(root / "supplier.sqlite"),
            "--output",
            str(root / "supplier-packets"),
        ),
        (
            "reconcile-bank-fixtures",
            "--output",
            str(root / "bank-packets"),
        ),
        (
            "scan-intake-folder",
            "--db",
            str(root / "intake.sqlite"),
            "--storage",
            str(root / "intake-storage"),
        ),
        ("demo-supplier-invoice-autopilot", "--output", str(root / "demo")),
        (
            "fake-client-dry-run",
            "--output",
            str(root / "fake-client"),
            "--report",
            str(root / "fake-client-report.md"),
        ),
        ("build-operations-cockpit", "--output", str(root / "cockpit.html")),
        ("build-public-preview", "--output", str(root / "preview")),
        ("platform-status", "--json"),
        ("v1-system-check", "--json"),
    )


def _artifact_from_env(variable: str, suffix: str) -> Path:
    raw = os.environ.get(variable)
    if not raw:
        raise unittest.SkipTest(f"{variable} is set by the release QA artifact gate")
    path = Path(raw).resolve()
    if not path.is_file() or not path.name.endswith(suffix):
        raise AssertionError(f"{variable} must point to a {suffix} artifact: {path}")
    return path


if __name__ == "__main__":
    unittest.main()
