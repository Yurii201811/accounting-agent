from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts.fixture_policy import scan_repository


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class OpenSourceBaselineTests(unittest.TestCase):
    def test_apache_license_notice_and_spdx_metadata_are_declared(self) -> None:
        license_text = _read("LICENSE")
        notice = _read("NOTICE")
        configuration = tomllib.loads(_read("pyproject.toml"))
        metadata = configuration["project"]

        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)
        self.assertIn("Accounting Agent contributors", notice)
        self.assertEqual("Apache-2.0", metadata["license"])
        self.assertEqual(["LICENSE", "NOTICE"], metadata["license-files"])
        self.assertIn("setuptools>=77", configuration["build-system"]["requires"])

    def test_governance_and_contribution_contracts_are_durable(self) -> None:
        contributing = _read("CONTRIBUTING.md")
        conduct = _read("CODE_OF_CONDUCT.md")
        governance = _read("GOVERNANCE.md")
        security = _read("SECURITY.md")
        dco = _read("DCO.md")

        self.assertIn("Signed-off-by:", contributing)
        self.assertIn("Developer Certificate of Origin", contributing)
        self.assertIn("enforcement", conduct.casefold())
        self.assertIn("maintainer", governance.casefold())
        self.assertIn("GitHub private vulnerability reporting", security)
        self.assertIn("Security Advisories", security)
        self.assertNotIn("security@", security.casefold())
        self.assertIn("Developer Certificate of Origin Version 1.1", dco)
        self.assertIn("Signed-off-by:", dco)

    def test_github_community_files_exist_without_a_fourth_workflow(self) -> None:
        self.assertIn("* @Yurii201811", _read(".github/CODEOWNERS"))
        for relative_path in (
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml",
            ".github/pull_request_template.md",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)
        self.assertEqual(
            {"codeql.yml", "nightly.yml", "qa.yml"},
            {path.name for path in (ROOT / ".github" / "workflows").glob("*.yml")},
        )

    def test_program_and_release_contracts_keep_publication_fail_closed(self) -> None:
        program = _read("docs/production_program.md")
        release = _read("docs/release-process.md")
        changelog = _read("CHANGELOG.md")

        for phrase in (
            "open-source core",
            "private cloud",
            "Safety ceiling",
            "Program phases",
            "Release gates",
            "External prerequisites",
            "not production-ready",
        ):
            self.assertIn(phrase.casefold(), program.casefold())
        for gate in (
            "remote CI",
            "manual VoiceOver",
            "legal review",
            "accounting review",
            "history and privacy review",
        ):
            self.assertIn(gate.casefold(), release.casefold())
        self.assertIn("publication", release.casefold())
        self.assertIn("## Unreleased", changelog)

    def test_private_data_provenance_policy_is_explicit(self) -> None:
        policy = _read("docs/provenance-and-private-data.md")
        for phrase in (
            "synthetic data",
            "real client data",
            "private course material",
            "redistribution rights",
            "source control",
            "fail closed",
        ):
            self.assertIn(phrase.casefold(), policy.casefold())

    def test_source_distribution_manifest_includes_governance_files(self) -> None:
        manifest_lines = set(_read("MANIFEST.in").splitlines())
        for relative_path in (
            "LICENSE",
            "NOTICE",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "DCO.md",
            "GOVERNANCE.md",
            "SECURITY.md",
        ):
            self.assertIn(f"include {relative_path}", manifest_lines)
        self.assertIn("graft .github", manifest_lines)

    def test_repository_privacy_scan_covers_docs_and_python_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "accounting_agent").mkdir()
            (root / "fixtures").mkdir()
            (root / "fixtures" / "synthetic.json").write_text(
                '{"synthetic": true}\n', encoding="utf-8"
            )
            (root / "docs" / "private-course.md").write_text(
                "Copied from " + "kursstart" + ".se", encoding="utf-8"
            )
            (root / "accounting_agent" / "download.py").write_text(
                'SOURCE = "/'
                + "Users/example/"
                + "Down"
                + 'loads/client.csv"\n',
                encoding="utf-8",
            )

            report = scan_repository(root)

        codes = {finding.code for finding in report.findings}
        self.assertIn("private_course_marker", codes)
        self.assertIn("local_path_marker", codes)

    def test_current_docs_and_source_pass_the_provenance_scan(self) -> None:
        report = scan_repository(ROOT)
        self.assertTrue(report.ok, report.findings)

    def test_detector_assignments_do_not_exempt_the_rest_of_the_file(self) -> None:
        course_marker = "kursstart" + ".se"
        home_marker = "/" + "Users" + "/example/private.txt"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "accounting_agent").mkdir()
            (root / "scripts").mkdir()
            (root / "fixtures").mkdir()
            (root / "fixtures" / "synthetic.json").write_text(
                '{"synthetic": true}\n', encoding="utf-8"
            )
            (root / "accounting_agent" / "operations_cockpit.py").write_text(
                "forbidden_markers = "
                f"({course_marker!r},)\nUNRELATED_SOURCE = {course_marker!r}\n",
                encoding="utf-8",
            )
            (root / "scripts" / "evidence_privacy.py").write_text(
                "import re\n_MAC_LINUX_HOME = "
                f"re.compile({home_marker!r})\nUNRELATED_SOURCE = {home_marker!r}\n",
                encoding="utf-8",
            )
            (root / "scripts" / "fixture_policy.py").write_text(
                "import re\n_PRIVATE_COURSE_RE = "
                f"re.compile({course_marker!r})\nUNRELATED_SOURCE = {course_marker!r}\n",
                encoding="utf-8",
            )

            report = scan_repository(root)

        self.assertEqual(
            {
                "accounting_agent/operations_cockpit.py",
                "scripts/evidence_privacy.py",
                "scripts/fixture_policy.py",
            },
            {
                finding.path
                for finding in report.findings
                if finding.code in {"local_path_marker", "private_course_marker"}
            },
        )

    def test_provenance_scan_covers_all_manifest_publishable_text_roots(self) -> None:
        course_marker = "kursstart" + ".se"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixtures").mkdir()
            (root / "fixtures" / "synthetic.json").write_text(
                '{"synthetic": true}\n', encoding="utf-8"
            )
            manifest = """\
include NOTICE
include favicon.svg
include package.json
include playwright.config.ts
include tokens.css
include uv.lock
graft .github
recursive-include config *.example
recursive-include qa *.json
recursive-include reports *.html
recursive-include spec *.md
recursive-include tests *.md *.py *.ts
"""
            (root / "MANIFEST.in").write_text(manifest, encoding="utf-8")
            publishable_paths = {
                ".github/CODEOWNERS",
                ".github/ISSUE_TEMPLATE/bug.yml",
                "config/provider.env.example",
                "qa/policy.json",
                "reports/index.html",
                "spec/contract.md",
                "tests/README.md",
                "tests/test_policy.py",
                "tests/policy.spec.ts",
                "NOTICE",
                "favicon.svg",
                "package.json",
                "playwright.config.ts",
                "tokens.css",
                "uv.lock",
            }
            for relative_path in publishable_paths:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"Published from {course_marker}\n", encoding="utf-8")

            report = scan_repository(root)

        self.assertEqual(
            publishable_paths,
            {
                finding.path
                for finding in report.findings
                if finding.code == "private_course_marker"
            },
        )

    def test_source_path_scan_ignores_web_urls_and_blocks_local_paths(self) -> None:
        posix_home = "/" + "home" + "/accountant/private.txt"
        file_home = "file:" + "///" + "Users/accountant/private.txt"
        windows_home = "C:" + "\\Users\\accountant\\private.txt"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "fixtures").mkdir()
            (root / "fixtures" / "synthetic.json").write_text(
                '{"synthetic": true}\n', encoding="utf-8"
            )
            (root / "docs" / "links.md").write_text(
                "https://example.test/home/docs/guide\n"
                "https://example.test/Users/reference/guide\n",
                encoding="utf-8",
            )
            (root / "docs" / "local.md").write_text(
                f"{posix_home}\n{file_home}\n{windows_home}\n",
                encoding="utf-8",
            )

            report = scan_repository(root)

        local_path_findings = {
            finding.path for finding in report.findings if finding.code == "local_path_marker"
        }
        self.assertNotIn("docs/links.md", local_path_findings)
        self.assertIn("docs/local.md", local_path_findings)


if __name__ == "__main__":
    unittest.main()
