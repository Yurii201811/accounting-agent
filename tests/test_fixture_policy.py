from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.fixture_policy import main, scan_repository, scan_resources


class FixturePolicyUnitTests(unittest.TestCase):
    def test_accepts_explicit_and_legacy_synthetic_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            explicit = root / "explicit.json"
            explicit.write_text(json.dumps({"synthetic": True, "case": "ok"}), encoding="utf-8")
            legacy = root / "legacy.json"
            legacy.write_text(
                json.dumps({"scenario": "unknown_supplier", "mock_extraction": {"amount": "10.00"}}),
                encoding="utf-8",
            )
            tagged = root / "bank.json"
            tagged.write_text(
                json.dumps({"transactions": [{"source": "fixture:exact_match"}]}),
                encoding="utf-8",
            )

            report = scan_resources([explicit, legacy, tagged], kind="fixture")

        self.assertTrue(report.ok, report.findings)
        self.assertEqual(report.files_scanned, 3)

    def test_rejects_fixture_without_synthetic_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "invoice.json"
            fixture.write_text(json.dumps({"supplier": "Example AB"}), encoding="utf-8")

            report = scan_resources([fixture], kind="fixture")

        self.assertEqual([finding.code for finding in report.findings], ["synthetic_metadata_missing"])

    def test_educational_assets_require_an_exact_allowlist_entry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            educational = root / "educational-example.md"
            educational.write_text("Invented bookkeeping exercise.\n", encoding="utf-8")

            blocked = scan_resources([educational], kind="fixture")
            allowed = scan_resources(
                [educational],
                kind="fixture",
                educational_allowlist={educational.resolve()},
            )

        self.assertEqual([finding.code for finding in blocked.findings], ["synthetic_metadata_missing"])
        self.assertTrue(allowed.ok, allowed.findings)

    def test_rejects_symlinks_unexpected_extensions_and_oversized_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target.txt"
            target.write_text("Synthetic fixture.\n", encoding="utf-8")
            linked = root / "linked.txt"
            linked.symlink_to(target)
            pdf = root / "course.pdf"
            pdf.write_bytes(b"synthetic")
            oversized = root / "large.txt"
            oversized.write_text("Synthetic fixture.\n" + ("x" * 128), encoding="utf-8")

            report = scan_resources([linked, pdf, oversized], kind="fixture", max_bytes=32)

        self.assertEqual(
            {finding.code for finding in report.findings},
            {"symlink_forbidden", "unexpected_extension", "file_too_large"},
        )

    def test_rejects_local_paths_course_markers_and_obvious_credentials(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            local_path = root / "local.txt"
            local_path.write_text("Synthetic fixture from /Users/example/Downloads/invoice.txt\n", encoding="utf-8")
            private_course = root / "course.txt"
            private_course.write_text("Synthetic fixture copied from kursstart.se\n", encoding="utf-8")
            secret = root / "secret.json"
            secret.write_text(
                json.dumps({"synthetic": True, "client_secret": "not-a-demo-value-123456789"}),
                encoding="utf-8",
            )

            report = scan_resources([local_path, private_course, secret], kind="fixture")

        self.assertEqual(
            {finding.code for finding in report.findings},
            {"local_path_marker", "private_course_marker", "credential_material"},
        )

    def test_preview_assets_do_not_require_fixture_metadata_but_receive_privacy_checks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "index.html"
            html.write_text("<!doctype html><title>Synthetic preview</title>", encoding="utf-8")
            css = root / "tokens.css"
            css.write_text(":root { --color: #fff; }", encoding="utf-8")
            unsafe = root / "README.txt"
            unsafe.write_text("Open file:///Users/example/private.json", encoding="utf-8")

            clean = scan_resources([html, css], kind="preview")
            blocked = scan_resources([unsafe], kind="preview")

        self.assertTrue(clean.ok, clean.findings)
        self.assertEqual([finding.code for finding in blocked.findings], ["local_path_marker"])


class FixturePolicyRepositoryTests(unittest.TestCase):
    def test_repository_scan_covers_fixture_and_preview_source_roots(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "fixtures").mkdir()
            (root / "fixtures" / "fixture.txt").write_text("Synthetic fixture.\n", encoding="utf-8")
            (root / "accounting_agent" / "fixtures").mkdir(parents=True)
            (root / "accounting_agent" / "fixtures" / "fixture.json").write_text(
                json.dumps({"synthetic": True}),
                encoding="utf-8",
            )
            (root / "accounting_agent" / "static").mkdir()
            (root / "accounting_agent" / "static" / "tokens.css").write_text(
                ":root { --color: #fff; }",
                encoding="utf-8",
            )
            (root / "tokens.css").write_text(":root { --color: #fff; }", encoding="utf-8")

            report = scan_repository(root)

        self.assertTrue(report.ok, report.findings)
        self.assertEqual(report.files_scanned, 4)

    def test_cli_returns_one_and_actionable_output_for_a_policy_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "fixtures").mkdir()
            (root / "fixtures" / "bad.json").write_text("{}", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["--repo-root", os.fspath(root)])

        self.assertEqual(exit_code, 1)
        self.assertIn("synthetic_metadata_missing", stdout.getvalue())
        self.assertIn("fixture policy failed", stdout.getvalue().lower())
        self.assertNotIn("Traceback", stdout.getvalue() + stderr.getvalue())

    def test_cli_writes_machine_readable_release_evidence(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "fixtures").mkdir()
            (root / "fixtures" / "safe.txt").write_text(
                "Synthetic fixture.\n",
                encoding="utf-8",
            )
            output = root / "evidence" / "fixture-policy.json"

            exit_code = main(
                [
                    "--repo-root",
                    os.fspath(root),
                    "--json",
                    "--output",
                    os.fspath(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertEqual(1, payload["files_scanned"])


if __name__ == "__main__":
    unittest.main()
