from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from scripts.evidence_privacy import (
    EvidencePrivacyError,
    _write_report,
    sanitize_evidence_tree,
)


class EvidencePrivacyTests(unittest.TestCase):
    def test_sanitizes_summary_junit_lock_and_hostname(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            (root / "junit").mkdir(parents=True)
            (root / "security").mkdir()
            (root / "coverage").mkdir()
            repo_root = Path("/Users/private-accountant/Documents/Accounting Agent")
            home = Path("/Users/private-accountant")
            hostname = "Private-Mac.local"
            (root / "summary.json").write_text(
                json.dumps(
                    {
                        "command": [str(repo_root / ".venv/bin/python3")],
                        "home": str(home),
                    }
                ),
                encoding="utf-8",
            )
            (root / "junit" / "python.xml").write_text(
                (
                    f'<testsuite hostname="{hostname}">'
                    f'<skipped message="{repo_root}/tests/test_package.py"/>'
                    "</testsuite>"
                ),
                encoding="utf-8",
            )
            (root / "security" / "qa-requirements.lock").write_text(
                f"# output-file {root}/security/qa-requirements.lock\n",
                encoding="utf-8",
            )
            raw_coverage = root / "coverage" / ".coverage.Private-Mac_local.pid123"
            raw_coverage.write_bytes(str(repo_root).encode("utf-8"))

            report = sanitize_evidence_tree(
                root,
                repo_root=repo_root,
                home=home,
                hostname=hostname,
            )
            parsed_junit = ElementTree.parse(root / "junit" / "python.xml")

            evidence = "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(root.rglob("*"))
                if path.is_file()
            )
        self.assertTrue(report["passed"])
        self.assertGreaterEqual(report["files_sanitized"], 3)
        self.assertEqual(1, report["raw_coverage_files_removed"])
        self.assertFalse(raw_coverage.exists())
        self.assertNotIn(str(repo_root), evidence)
        self.assertNotIn(str(home), evidence)
        self.assertNotIn(hostname, evidence)
        self.assertEqual("[host]", parsed_junit.getroot().attrib["hostname"])
        self.assertIn("[repo]/.venv/bin/python3", evidence)
        self.assertIn("[host]", evidence)

    def test_rejects_symlinked_evidence_without_following_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            root.mkdir()
            outside = Path(temp_dir) / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            (root / "leak.txt").symlink_to(outside)

            with self.assertRaisesRegex(EvidencePrivacyError, "symlink"):
                sanitize_evidence_tree(root)

            self.assertEqual("private", outside.read_text(encoding="utf-8"))

    def test_sanitizes_unrecognized_local_home_paths_in_text_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            root.mkdir()
            report = root / "third-party.json"
            report.write_text(
                '{"path":"/Users/another-person/project/file.py",'
                '"windows":"C:\\\\Users\\\\someone\\\\project"}',
                encoding="utf-8",
            )

            result = sanitize_evidence_tree(root)

            sanitized = report.read_text(encoding="utf-8")
        self.assertTrue(result["passed"])
        self.assertNotIn("/Users/another-person", sanitized)
        self.assertNotIn("C:\\Users\\someone", sanitized)
        self.assertIn("[home]/project/file.py", sanitized)

    def test_reports_identity_embedded_in_an_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            package = root / "package" / "artifact.whl"
            package.parent.mkdir(parents=True)
            home = Path("/Users/private-accountant")
            with zipfile.ZipFile(package, mode="w") as archive:
                archive.writestr("docs/build.txt", f"built from {home}/project")

            result = sanitize_evidence_tree(root, home=home)

        self.assertFalse(result["passed"])
        archive_member_finding = next(
            finding for finding in result["findings"] if "member" in finding
        )
        self.assertEqual("package/artifact.whl", archive_member_finding["file"])
        self.assertEqual("docs/build.txt", archive_member_finding["member"])

    def test_report_path_cannot_escape_with_parent_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            root.mkdir()
            outside = root / ".." / "outside.json"

            with self.assertRaisesRegex(EvidencePrivacyError, "inside"):
                _write_report(root, outside, {"passed": True})

            self.assertFalse((Path(temp_dir) / "outside.json").exists())

    def test_invalid_structured_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "run"
            root.mkdir()
            (root / "broken.json").write_text("{", encoding="utf-8")

            result = sanitize_evidence_tree(root)

        self.assertFalse(result["passed"])
        self.assertEqual(
            [{"file": "broken.json", "kind": "invalid-structured-evidence"}],
            result["findings"],
        )


if __name__ == "__main__":
    unittest.main()
