from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "production_readiness.py"
CATALOG = ROOT / "qa" / "production-gates.json"

REQUIRED_CONTROL_DOCUMENTS = {
    "docs/security/threat-model.md",
    "docs/security/incident-response.md",
    "docs/compliance/data-map.md",
    "docs/compliance/dpia.md",
    "docs/compliance/ropa.md",
    "docs/compliance/dpa-control-matrix.md",
    "docs/compliance/subprocessor-policy.md",
    "docs/compliance/ai-system-inventory.md",
    "docs/compliance/swedish-accounting-archive-review.md",
}

REQUIRED_FIRST_BYTE_GATES = {
    "privacy-governance-review",
    "swedish-accounting-archive-review",
    "tenant-isolation-assurance",
    "encryption-key-management-assurance",
    "archive-retention-worm-assurance",
    "audit-anchoring-assurance",
    "backup-restore-exercise",
    "manual-accessibility-acceptance",
    "incident-tabletop-notification-test",
    "independent-penetration-test",
}


def _run_readiness(*arguments: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(SCRIPT), *arguments),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


class ProductionReadinessControlTests(unittest.TestCase):
    def test_gate_catalog_is_fail_closed_and_complete(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

        self.assertEqual(1, catalog["schema_version"])
        self.assertEqual("first-real-client-byte", catalog["gate_set"])
        self.assertEqual("pending", catalog["default_outcome"])
        self.assertRegex(
            catalog["threat_model_binding"]["repository"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertRegex(catalog["threat_model_binding"]["version"], r"^[0-9a-f]{40}$")
        self.assertEqual(
            REQUIRED_CONTROL_DOCUMENTS,
            set(catalog["required_control_documents"]),
        )
        self.assertEqual(
            REQUIRED_FIRST_BYTE_GATES,
            {gate["id"] for gate in catalog["gates"]},
        )
        for gate in catalog["gates"]:
            with self.subTest(gate=gate["id"]):
                self.assertIs(gate["required"], True)
                self.assertEqual("pending", gate["initial_status"])
                self.assertIs(gate["automated_verification"], False)
                self.assertIn(
                    gate["verification_mode"],
                    {
                        "external_professional_review",
                        "independent_assurance",
                        "manual_acceptance",
                        "operational_exercise",
                    },
                )
                self.assertTrue(gate["owner_role"].strip())
                self.assertGreater(len(gate["acceptance_criteria"]), 0)
                self.assertTrue(
                    gate["evidence_location"].startswith(".local/production-readiness/evidence/")
                )

    def test_templates_are_explicitly_unapproved_and_source_bound(self) -> None:
        for relative_path in REQUIRED_CONTROL_DOCUMENTS:
            document = (ROOT / relative_path).read_text(encoding="utf-8")
            normalized_document = " ".join(document.casefold().split())
            with self.subTest(document=relative_path):
                self.assertIn("Status: PRELIMINARY — NOT APPROVED", document)
                self.assertIn("does not authorize real-client data", normalized_document)
                self.assertIn("## Approval record", document)
                self.assertIn("Decision: PENDING", document)

        self.assertIn(
            "https://www.imy.se/",
            (ROOT / "docs/compliance/dpia.md").read_text(encoding="utf-8"),
        )
        archive_review = (ROOT / "docs/compliance/swedish-accounting-archive-review.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://www.bfn.se/", archive_review)
        self.assertIn("https://www.riksdagen.se/", archive_review)

    def test_threat_model_is_repository_scoped_and_has_cache_metadata(self) -> None:
        threat_model = (ROOT / "docs/security/threat-model.md").read_text(encoding="utf-8")
        for heading in (
            "# Overview",
            "# Threat Model, Trust Boundaries, and Assumptions",
            "# Attack Surface, Mitigations, and Attacker Stories",
            "# Severity Calibration",
        ):
            self.assertIn(heading, threat_model)
        self.assertIn("current public core", threat_model.casefold())
        self.assertIn("future commercial cloud", threat_model.casefold())
        self.assertRegex(threat_model, r"(?m)^Repository: sha256:[0-9a-f]{64}$")
        self.assertRegex(threat_model, r"(?m)^Version: [0-9a-f]{40}$")
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        repository = re.search(r"(?m)^Repository: (sha256:[0-9a-f]{64})$", threat_model)
        version = re.search(r"(?m)^Version: ([0-9a-f]{40})$", threat_model)
        self.assertIsNotNone(repository)
        self.assertIsNotNone(version)
        assert repository is not None and version is not None
        self.assertEqual(catalog["threat_model_binding"]["repository"], repository.group(1))
        self.assertEqual(catalog["threat_model_binding"]["version"], version.group(1))
        if (ROOT / ".git").exists():
            revision_check = subprocess.run(
                ("git", "cat-file", "-e", f"{version.group(1)}^{{commit}}"),
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, revision_check.returncode, revision_check.stderr)
        self.assertIn("## Regeneration policy", threat_model)

    def test_readiness_report_stays_pending_without_external_verification(self) -> None:
        result = _run_readiness("--json")

        self.assertEqual(2, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("pending", report["status"])
        self.assertIs(report["ready"], False)
        self.assertEqual(0, report["invalid_control_count"])
        self.assertEqual(len(REQUIRED_FIRST_BYTE_GATES), report["blocking_gate_count"])
        self.assertEqual(
            REQUIRED_FIRST_BYTE_GATES,
            {gate["id"] for gate in report["gates"] if gate["status"] == "pending"},
        )

    def test_runtime_surface_change_invalidates_the_threat_model(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=ROOT / "accounting_agent",
            prefix=".qa-runtime-drift-",
        ) as directory:
            (Path(directory) / "new_runtime.py").write_text(
                "# synthetic unreviewed runtime surface\n",
                encoding="utf-8",
            )
            result = _run_readiness("--json")

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertIn("threat model is stale", " ".join(report["errors"]).casefold())

    def test_catalog_cannot_self_attest_a_gate_as_verified(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        catalog["gates"][0]["initial_status"] = "verified"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertIn("must remain pending", " ".join(report["errors"]))

    def test_catalog_rejects_unexpected_approval_fields(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        catalog["ready"] = True
        catalog["status"] = "approved"
        catalog["gates"][0]["approved"] = True
        catalog["gates"][0]["current_status"] = "verified"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertIn("unexpected", " ".join(report["errors"]).casefold())

    def test_catalog_rejects_duplicate_json_keys(self) -> None:
        catalog_text = CATALOG.read_text(encoding="utf-8").replace(
            '"schema_version": 1,',
            '"schema_version": 1,\n  "schema_version": 1,',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(catalog_text, encoding="utf-8")
            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertIn("duplicate", " ".join(report["errors"]).casefold())

    def test_catalog_symlink_and_escape_are_rejected(self) -> None:
        catalog_text = CATALOG.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            target = root / "qa" / "catalog-target.json"
            target.write_text(catalog_text, encoding="utf-8")
            symlink = root / "qa" / "production-gates.json"
            symlink.symlink_to(target.name)
            symlink_result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(symlink),
                "--json",
            )
            escape_result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(CATALOG),
                "--json",
            )

        self.assertEqual(1, symlink_result.returncode)
        self.assertIn("symlink", symlink_result.stdout.casefold())
        self.assertEqual(1, escape_result.returncode)
        self.assertIn("escapes", escape_result.stdout.casefold())

    def test_catalog_cannot_drop_a_required_gate(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        removed_gate = catalog["gates"].pop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertIn(removed_gate["id"], " ".join(report["errors"]))

    def test_missing_control_document_is_invalid_not_ready(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        self.assertNotIn("Traceback", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertGreater(report["invalid_control_count"], 0)

    def test_control_document_symlink_is_rejected(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        marker_document = """\
Status: PRELIMINARY — NOT APPROVED
This document does not authorize real-client data.
## Approval record
Decision: PENDING
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            for relative_path in REQUIRED_CONTROL_DOCUMENTS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(marker_document, encoding="utf-8")
            symlink_path = root / "docs/security/threat-model.md"
            target_path = root / "docs/security/threat-model-target.md"
            target_path.write_text(marker_document, encoding="utf-8")
            symlink_path.unlink()
            symlink_path.symlink_to(target_path.name)

            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertIn("symlink", json.dumps(report).casefold())

    def test_control_document_nested_symlink_is_rejected(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        marker_document = """\
Status: PRELIMINARY — NOT APPROVED
This document does not authorize real-client data.
## Approval record
Decision: PENDING
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            for relative_path in REQUIRED_CONTROL_DOCUMENTS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(marker_document, encoding="utf-8")
            external_directory = root / "external-security"
            external_directory.mkdir()
            (external_directory / "threat-model.md").write_text(
                marker_document,
                encoding="utf-8",
            )
            security_directory = root / "docs/security"
            for path in security_directory.iterdir():
                path.unlink()
            security_directory.rmdir()
            security_directory.symlink_to(external_directory, target_is_directory=True)

            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("symlink", result.stdout.casefold())

    def test_control_document_cannot_hide_an_approved_decision_behind_pending_text(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        marker_document = """\
Status: PRELIMINARY — NOT APPROVED
This document does not authorize real-client data.
## Approval record
- Decision: PENDING
"""
        contradictory_document = """\
Status: PRELIMINARY — NOT APPROVED
This document does not authorize real-client data.
## Approval record
- Decision: PENDING
> Decision: APPROVED
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "qa").mkdir()
            candidate = root / "qa" / "production-gates.json"
            candidate.write_text(json.dumps(catalog), encoding="utf-8")
            for relative_path in REQUIRED_CONTROL_DOCUMENTS:
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(marker_document, encoding="utf-8")
            (root / "docs/security/incident-response.md").write_text(
                contradictory_document,
                encoding="utf-8",
            )
            result = _run_readiness(
                "--root",
                str(root),
                "--catalog",
                str(candidate),
                "--json",
            )

        self.assertEqual(1, result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("invalid", report["status"])
        self.assertIn("decision", json.dumps(report).casefold())

    def test_cli_has_no_approval_or_self_attestation_path(self) -> None:
        result = _run_readiness("--help")

        self.assertEqual(0, result.returncode, result.stderr)
        help_text = result.stdout.casefold()
        self.assertNotIn("--approve", help_text)
        self.assertNotIn("--attest", help_text)
        self.assertNotIn("--verify-gate", help_text)

    def test_source_distribution_manifest_names_readiness_artifacts(self) -> None:
        manifest_lines = set((ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines())
        self.assertIn("include qa/production-gates.json", manifest_lines)
        self.assertIn("include scripts/production_readiness.py", manifest_lines)


if __name__ == "__main__":
    unittest.main()
