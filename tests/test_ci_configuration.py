from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EXPECTED_WORKFLOWS = {"qa.yml", "codeql.yml", "nightly.yml"}
ACTION_REFERENCE = re.compile(
    r"^\s*-?\s*uses:\s*([^@\s]+)@([^\s#]+)(?:\s+#\s*(.+))?$",
    re.MULTILINE,
)
JOB_HEADER = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$", re.MULTILINE)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _job_blocks(workflow: str) -> dict[str, str]:
    jobs_offset = workflow.index("\njobs:\n") + len("\njobs:\n")
    body = workflow[jobs_offset:]
    matches = list(JOB_HEADER.finditer(body))
    return {
        match.group(1): body[match.start() : matches[index + 1].start()]
        if index + 1 < len(matches)
        else body[match.start() :]
        for index, match in enumerate(matches)
    }


class WorkflowConfigurationTests(unittest.TestCase):
    def test_expected_workflows_and_formal_specification_exist(self) -> None:
        self.assertEqual(
            EXPECTED_WORKFLOWS,
            {path.name for path in WORKFLOWS.glob("*.yml")},
        )
        specification = _read("spec/spec-process-cicd-qa.md")
        self.assertIn("version: 1.0", specification)
        self.assertIn("## Requirements Matrix", specification)
        self.assertIn("## Quality Gates", specification)
        self.assertIn("## Change Management", specification)

    def test_all_action_dependencies_are_immutable_and_auditable(self) -> None:
        for workflow_path in sorted(WORKFLOWS.glob("*.yml")):
            workflow = workflow_path.read_text(encoding="utf-8")
            references = ACTION_REFERENCE.findall(workflow)
            self.assertTrue(references, workflow_path.name)
            for action, revision, provenance in references:
                self.assertRegex(revision, r"^[0-9a-f]{40}$", action)
                self.assertRegex(provenance, r"^v\d+(?:\.\d+){0,2}$", action)
            self.assertEqual(
                workflow.count("actions/checkout@"),
                workflow.count("persist-credentials: false"),
                workflow_path.name,
            )

    def test_workflows_use_least_privilege_concurrency_and_timeouts(self) -> None:
        for workflow_path in sorted(WORKFLOWS.glob("*.yml")):
            workflow = workflow_path.read_text(encoding="utf-8")
            pre_jobs = workflow.split("\njobs:\n", 1)[0]
            self.assertIn("permissions:\n  contents: read", pre_jobs)
            self.assertIn("concurrency:", pre_jobs)
            self.assertIn("cancel-in-progress: true", pre_jobs)
            self.assertNotIn("pull_request_target", workflow)
            self.assertNotIn("secrets.", workflow)
            self.assertNotRegex(workflow.lower(), r"\b(deploy|vercel|production)\b")
            self.assertNotIn("windows", workflow.lower())
            blocks = _job_blocks(workflow)
            self.assertTrue(blocks, workflow_path.name)
            for job, block in blocks.items():
                self.assertIn("timeout-minutes:", block, f"{workflow_path.name}:{job}")

    def test_main_qa_covers_runtime_platform_safety_package_and_ui_contracts(self) -> None:
        workflow = _read(".github/workflows/qa.yml")
        jobs = _job_blocks(workflow)
        self.assertEqual(
            {
                "source-quality",
                "python",
                "platform",
                "safety-contracts",
                "package",
                "ui",
                "required",
            },
            set(jobs),
        )
        self.assertIn('python-version: ["3.11", "3.12", "3.13", "3.14"]', jobs["python"])
        self.assertIn("os: [ubuntu-latest, macos-14]", jobs["platform"])
        self.assertIn("tests/offline_guard", jobs["python"])
        self.assertIn("tests/offline_guard", jobs["safety-contracts"])
        self.assertIn("scripts/coverage_gate.py", jobs["python"])
        self.assertIn("scripts/package_release_check.py", jobs["package"])
        self.assertIn("scripts/fixture_policy.py", jobs["source-quality"])
        self.assertIn("npm run test:ui:all", jobs["ui"])
        self.assertIn("playwright install --with-deps", jobs["ui"])
        self.assertIn("needs:", jobs["required"])
        self.assertGreaterEqual(workflow.count("actions/upload-artifact@"), 4)
        self.assertEqual(
            workflow.count("actions/upload-artifact@"),
            workflow.count("retention-days: 14"),
        )

    def test_security_workflow_scans_code_dependencies_and_secrets(self) -> None:
        workflow = _read(".github/workflows/codeql.yml")
        jobs = _job_blocks(workflow)
        self.assertEqual({"codeql", "dependency-audit", "secret-scan"}, set(jobs))
        self.assertIn("security-events: write", jobs["codeql"])
        self.assertNotIn("security-events: write", jobs["dependency-audit"])
        self.assertNotIn("security-events: write", jobs["secret-scan"])
        self.assertIn("actions: read", jobs["codeql"])
        self.assertNotIn("actions:", jobs["dependency-audit"])
        self.assertNotIn("actions:", jobs["secret-scan"])
        self.assertEqual(1, workflow.count("actions: read"))
        self.assertNotIn("pull-requests:", jobs["codeql"])
        self.assertNotIn("pull-requests:", jobs["dependency-audit"])
        self.assertIn("pull-requests: read", jobs["secret-scan"])
        self.assertEqual(1, workflow.count("pull-requests: read"))
        self.assertIn("github/codeql-action/init@", jobs["codeql"])
        self.assertIn("github/codeql-action/analyze@", jobs["codeql"])
        self.assertIn("pip_audit", jobs["dependency-audit"])
        self.assertIn("uv export", jobs["dependency-audit"])
        self.assertIn("--require-hashes", jobs["dependency-audit"])
        self.assertIn("bandit", jobs["dependency-audit"])
        self.assertIn("gitleaks/gitleaks-action@", jobs["secret-scan"])

    def test_scheduled_workflow_runs_stress_and_mutation_gates(self) -> None:
        workflow = _read(".github/workflows/nightly.yml")
        jobs = _job_blocks(workflow)
        self.assertEqual({"stress", "mutation"}, set(jobs))
        self.assertIn("schedule:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("test_multiprocess_integrity_v1", jobs["stress"])
        self.assertIn("test_sqlite_resilience_v1", jobs["stress"])
        self.assertIn("scripts/qa.py full", jobs["stress"])
        self.assertIn("needs: stress", jobs["mutation"])
        self.assertIn("mutmut run", jobs["mutation"])
        self.assertIn("mutmut results", jobs["mutation"])

    def test_dependabot_tracks_all_ci_lockfiles_without_noise(self) -> None:
        configuration = _read(".github/dependabot.yml")
        self.assertEqual(3, configuration.count("package-ecosystem:"))
        for ecosystem in ("github-actions", "pip", "npm"):
            self.assertIn(f'package-ecosystem: "{ecosystem}"', configuration)
        self.assertEqual(3, configuration.count('interval: "weekly"'))
        self.assertEqual(3, configuration.count('timezone: "Europe/Stockholm"'))
        self.assertEqual(3, configuration.count("open-pull-requests-limit: 5"))


if __name__ == "__main__":
    unittest.main()
