from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
QA_SCRIPT = ROOT / "scripts" / "qa.py"


def _load_qa_module():
    spec = importlib.util.spec_from_file_location("accounting_agent_qa_runner", QA_SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load scripts/qa.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class QARunnerTests(unittest.TestCase):
    BUNDLE_SHA256 = "a" * 64

    @staticmethod
    def _passing_results(qa, mode: str):
        return tuple(
            qa.StepResult(
                name=step.name,
                command=step.command,
                exit_code=0,
                duration_seconds=0.01,
            )
            for step in qa.build_step_plan(mode, python=sys.executable)
        )

    def test_mode_plans_cover_required_release_gates(self) -> None:
        qa = _load_qa_module()

        quick = {step.name for step in qa.build_step_plan("quick", python=sys.executable)}
        full = {step.name for step in qa.build_step_plan("full", python=sys.executable)}
        release_plan = qa.build_step_plan("release", python=sys.executable)
        release_names = tuple(step.name for step in release_plan)
        release = set(release_names)

        self.assertEqual(
            qa.QUICK_STEP_NAMES,
            tuple(
                step.name
                for step in qa.build_step_plan("quick", python=sys.executable)
            ),
        )
        self.assertEqual(
            qa.FULL_STEP_NAMES,
            tuple(
                step.name
                for step in qa.build_step_plan("full", python=sys.executable)
            ),
        )
        self.assertEqual(qa.RELEASE_STEP_NAMES, release_names)
        self.assertEqual(
            {"compile", "offline-tests", "v1-system-check"},
            quick,
        )
        self.assertLessEqual(
            {
                "branch-coverage",
                "coverage-json",
                "coverage-gate",
                "dependency-lock-export",
                "fixture-policy",
                "ruff",
                "mypy",
                "targeted-mutation",
                "mutation-safety-gate",
                "bandit",
                "pip-audit",
                "gitleaks",
                "ui-e2e",
            },
            full,
        )
        self.assertLessEqual(
            {
                "package-release",
                "preview-build",
                "preview-contract",
                "fixture-policy-preview",
            },
            release,
        )
        self.assertLess(
            release_names.index("preview-build"),
            release_names.index("fixture-policy-preview"),
        )
        self.assertLess(
            release_names.index("preview-build"),
            release_names.index("deployment-smoke"),
        )
        preview_step = next(step for step in release_plan if step.name == "preview-build")
        self.assertEqual(
            "1752192000",
            qa._step_environment(preview_step)["SOURCE_DATE_EPOCH"],
        )
        deployment_step = next(
            step for step in release_plan if step.name == "deployment-smoke"
        )
        self.assertEqual(
            str(qa.RELEASE_PREVIEW_BUNDLE),
            qa._step_environment(deployment_step)[
                "ACCOUNTING_AGENT_PREVIEW_BUNDLE"
            ],
        )
        branch_step = next(step for step in release_plan if step.name == "branch-coverage")
        system_step = next(step for step in release_plan if step.name == "v1-system-check")
        self.assertIn("COVERAGE_PROCESS_START", qa._step_environment(branch_step))
        self.assertNotIn("COVERAGE_PROCESS_START", qa._step_environment(system_step))
        self.assertEqual("evidence-privacy", release_names[-1])

    def test_playwright_config_honors_canonical_evidence_paths(self) -> None:
        config = (ROOT / "playwright.config.ts").read_text(encoding="utf-8")

        self.assertIn("process.env.PLAYWRIGHT_OUTPUT_DIR", config)
        self.assertIn("process.env.PLAYWRIGHT_HTML_OUTPUT_DIR", config)
        self.assertIn("process.env.PLAYWRIGHT_JUNIT_OUTPUT_NAME", config)

    def test_gitleaks_scans_source_with_default_rules_and_skips_generated_artifacts(
        self,
    ) -> None:
        qa = _load_qa_module()
        config = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
        gitleaks_step = next(
            step for step in qa.build_step_plan("full", python=sys.executable)
            if step.name == "gitleaks"
        )

        self.assertIn("useDefault = true", config)
        self.assertNotIn("disabledRules", config)
        for generated_path in (".local", ".venv", "__pycache__", "mutants"):
            self.assertIn(generated_path, config)
        self.assertEqual(1, config.count("[allowlist]"))
        self.assertNotIn("[[allowlists]]", config)
        self.assertIn("^idempotency-1$", config)
        self.assertIn('regexTarget = "secret"', config)
        self.assertNotIn("condition =", config)
        self.assertNotIn("commits =", config)
        self.assertEqual(".gitleaks.toml", gitleaks_step.command[-7])

    def test_summary_is_machine_readable_and_never_serializes_environment(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.json"
            results = list(self._passing_results(qa, "quick"))
            results[0] = qa.StepResult(
                name=results[0].name,
                command=(
                    str(qa.ROOT / ".venv" / "bin" / "python3"),
                    socket.gethostname(),
                ),
                exit_code=0,
                duration_seconds=0.01,
            )
            qa.write_summary(
                output,
                mode="quick",
                revision="abc123",
                results=results,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(payload["passed"])
        self.assertEqual("abc123", payload["revision"])
        self.assertEqual("compile", payload["steps"][0]["name"])
        serialized = json.dumps(payload).lower()
        self.assertNotIn("environment", serialized)
        self.assertNotIn("token", serialized)
        self.assertNotIn("password", serialized)
        self.assertNotIn(str(qa.ROOT), serialized)
        self.assertNotIn(str(Path.home()), serialized)
        self.assertEqual("<repo>/.venv/bin/python3", payload["steps"][0]["command"][0])
        self.assertEqual("<host>", payload["steps"][0]["command"][1])

    def test_release_summary_marks_missing_manual_voiceover_as_pending(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.json"
            qa.write_summary(
                output,
                mode="release",
                revision="release-candidate",
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(payload["passed"])
        self.assertEqual("pending", payload["manual_accessibility"])
        self.assertFalse(payload["release_ready"])

    def test_release_summary_accepts_complete_revision_bound_voiceover_evidence(
        self,
    ) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.json"
            evidence = output.parent / "accessibility" / "manual-voiceover.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                "\n".join(
                    (
                        "# Manual VoiceOver evidence",
                        "",
                        "status: passed",
                        "tester: Synthetic QA reviewer",
                        "tested_at_utc: 2026-07-11T09:00:00Z",
                        "macos_version: 15.5",
                        "browser: Safari 18",
                        "voiceover_version: 15",
                        "revision: release-candidate",
                        f"preview_bundle_sha256: {self.BUNDLE_SHA256}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            qa.write_summary(
                output,
                mode="release",
                revision="release-candidate",
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual("passed", payload["manual_accessibility"])
        self.assertTrue(payload["release_ready"])

    def test_dirty_worktree_cannot_be_reported_as_release_ready(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.json"
            evidence = output.parent / "accessibility" / "manual-voiceover.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                "\n".join(
                    (
                        "status: passed",
                        "tester: Synthetic QA reviewer",
                        "tested_at_utc: 2026-07-11T09:00:00Z",
                        "macos_version: 15.5",
                        "browser: Safari 18",
                        "voiceover_version: 15",
                        "revision: release-candidate",
                        f"preview_bundle_sha256: {self.BUNDLE_SHA256}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            qa.write_summary(
                output,
                mode="release",
                revision="release-candidate",
                preview_bundle_sha256=self.BUNDLE_SHA256,
                working_tree_dirty=True,
                results=self._passing_results(qa, "release"),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(payload["working_tree_dirty"])
        self.assertFalse(payload["release_ready"])

    def test_release_summary_rejects_mismatched_voiceover_bundle_hash(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.json"
            evidence = output.parent / "accessibility" / "manual-voiceover.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                "\n".join(
                    (
                        "status: passed",
                        "tester: Synthetic QA reviewer",
                        "tested_at_utc: 2026-07-11T09:00:00Z",
                        "macos_version: 15.5",
                        "browser: Safari 18",
                        "voiceover_version: 15",
                        "revision: release-candidate",
                        f"preview_bundle_sha256: {'b' * 64}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            qa.write_summary(
                output,
                mode="release",
                revision="release-candidate",
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual("failed", payload["manual_accessibility"])
        self.assertFalse(payload["release_ready"])

    def test_release_summary_reuses_prior_regular_voiceover_attestation(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "new-run" / "summary.json"
            evidence = root / "prior-run" / "manual-voiceover.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                "\n".join(
                    (
                        "status: passed",
                        "tester: Synthetic QA reviewer",
                        "tested_at_utc: 2026-07-11T09:00:00Z",
                        "macos_version: 15.5",
                        "browser: Safari 18",
                        "voiceover_version: 15",
                        "revision: release-candidate",
                        f"preview_bundle_sha256: {self.BUNDLE_SHA256}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            payload = qa.write_summary(
                output,
                mode="release",
                revision="release-candidate",
                manual_accessibility_evidence=evidence,
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )

            copied = output.parent / "accessibility" / "manual-voiceover.md"
            self.assertTrue(copied.is_file())
            self.assertFalse(copied.is_symlink())

        self.assertEqual("passed", payload["manual_accessibility"])
        self.assertTrue(payload["release_ready"])

    def test_voiceover_attestation_rejects_symlink_and_invalid_utc_timestamp(
        self,
    ) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_evidence = root / "real.md"
            real_evidence.write_text(
                "\n".join(
                    (
                        "status: passed",
                        "tester: Synthetic QA reviewer",
                        "tested_at_utc: not-a-date",
                        "macos_version: 15.5",
                        "browser: Safari 18",
                        "voiceover_version: 15",
                        "revision: release-candidate",
                        f"preview_bundle_sha256: {self.BUNDLE_SHA256}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            symlink = root / "evidence-link.md"
            symlink.symlink_to(real_evidence)

            invalid_time = qa.write_summary(
                root / "invalid-time" / "summary.json",
                mode="release",
                revision="release-candidate",
                manual_accessibility_evidence=real_evidence,
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )
            real_evidence.write_text(
                real_evidence.read_text(encoding="utf-8").replace(
                    "tested_at_utc: not-a-date",
                    "tested_at_utc: 2026-07-11T09:00:00",
                ),
                encoding="utf-8",
            )
            timezone_less = qa.write_summary(
                root / "timezone-less" / "summary.json",
                mode="release",
                revision="release-candidate",
                manual_accessibility_evidence=real_evidence,
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )
            symlinked = qa.write_summary(
                root / "symlinked" / "summary.json",
                mode="release",
                revision="release-candidate",
                manual_accessibility_evidence=symlink,
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )

        self.assertEqual("failed", invalid_time["manual_accessibility"])
        self.assertEqual("failed", timezone_less["manual_accessibility"])
        self.assertEqual("failed", symlinked["manual_accessibility"])

    def test_unstable_source_state_cannot_be_release_ready(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.json"
            evidence = output.parent / "accessibility" / "manual-voiceover.md"
            evidence.parent.mkdir(parents=True)
            evidence.write_text(
                "\n".join(
                    (
                        "status: passed",
                        "tester: Synthetic QA reviewer",
                        "tested_at_utc: 2026-07-11T09:00:00Z",
                        "macos_version: 15.5",
                        "browser: Safari 18",
                        "voiceover_version: 15",
                        "revision: end-revision",
                        f"preview_bundle_sha256: {self.BUNDLE_SHA256}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            payload = qa.write_summary(
                output,
                mode="release",
                revision="end-revision",
                revision_start="start-revision",
                source_state_stable=False,
                preview_bundle_sha256=self.BUNDLE_SHA256,
                results=self._passing_results(qa, "release"),
            )

        self.assertEqual("start-revision", payload["revision_start"])
        self.assertFalse(payload["source_state_stable"])
        self.assertFalse(payload["release_ready"])

    def test_incomplete_step_plan_never_passes(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "summary.json"
            payload = qa.write_summary(
                output,
                mode="full",
                revision="candidate",
                results=(),
            )

        self.assertFalse(payload["plan_complete"])
        self.assertFalse(payload["passed"])

    def test_cli_summary_path_is_confined_and_rejects_symlinks(self) -> None:
        qa = _load_qa_module()
        runs_root = ROOT / ".local" / "qa" / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.TemporaryDirectory(dir=runs_root, prefix="path-safe-") as run_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            safe = Path(run_dir) / "summary.json"
            self.assertEqual(safe, qa._validated_summary_path(safe))

            outside = Path(outside_dir) / "summary.json"
            with self.assertRaisesRegex(ValueError, "QA runs directory"):
                qa._validated_summary_path(outside)

            outside.write_text("outside", encoding="utf-8")
            safe.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                qa._validated_summary_path(safe)

    def test_cli_path_rejection_uses_configuration_failure_exit_code(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            outside = Path(temp_dir) / "summary.json"

            exit_code = qa.main(["quick", "--summary", str(outside)])

        self.assertEqual(1, exit_code)

    def test_cli_accepts_prior_manual_accessibility_evidence_option(self) -> None:
        qa = _load_qa_module()

        args = qa._parser().parse_args(
            [
                "release",
                "--manual-accessibility-evidence",
                ".local/qa/runs/prior/accessibility/manual-voiceover.md",
            ]
        )

        self.assertEqual("release", args.mode)
        self.assertEqual(
            Path(".local/qa/runs/prior/accessibility/manual-voiceover.md"),
            args.manual_accessibility_evidence,
        )

    def test_main_records_start_and_end_source_state(self) -> None:
        qa = _load_qa_module()
        runs_root = ROOT / ".local" / "qa" / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=runs_root,
            prefix="source-state-",
        ) as run_dir:
            summary = Path(run_dir) / "summary.json"
            expected_quick_plan = qa.build_step_plan("quick")
            with (
                mock.patch.object(
                    qa,
                    "build_step_plan",
                    side_effect=((), expected_quick_plan),
                ),
                mock.patch.object(
                    qa,
                    "_revision",
                    side_effect=("start-revision", "end-revision"),
                ),
                mock.patch.object(
                    qa,
                    "_working_tree_dirty",
                    side_effect=(False, False),
                ),
            ):
                exit_code = qa.main(["quick", "--summary", str(summary)])
            payload = json.loads(summary.read_text(encoding="utf-8"))

        self.assertEqual(1, exit_code)
        self.assertEqual("start-revision", payload["revision_start"])
        self.assertEqual("end-revision", payload["revision"])
        self.assertFalse(payload["source_state_stable"])
        self.assertFalse(payload["plan_complete"])

    def test_main_writes_fail_closed_provisional_summary_before_privacy_gate(self) -> None:
        qa = _load_qa_module()
        runs_root = ROOT / ".local" / "qa" / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        events: list[str] = []

        def record_summary(*args, **kwargs):
            del args
            results = kwargs["results"]
            events.append(f"summary:{results[-1].exit_code}")
            return {"passed": results[-1].exit_code == 0}

        def record_step(step, **kwargs):
            del kwargs
            events.append(f"run:{step.name}")
            return qa.StepResult(step.name, step.command, 0, 0.01)

        with tempfile.TemporaryDirectory(
            dir=runs_root,
            prefix="privacy-order-",
        ) as run_dir:
            summary = Path(run_dir) / "summary.json"
            privacy_step = qa.Step("evidence-privacy", (sys.executable, "privacy"))
            with (
                mock.patch.object(qa, "build_step_plan", return_value=(privacy_step,)),
                mock.patch.object(qa, "run_step", side_effect=record_step),
                mock.patch.object(qa, "write_summary", side_effect=record_summary),
                mock.patch.object(
                    qa,
                    "_revision",
                    side_effect=("start", "before-privacy", "end"),
                ),
                mock.patch.object(
                    qa,
                    "_working_tree_dirty",
                    side_effect=(False, False, False),
                ),
            ):
                exit_code = qa.main(["full", "--summary", str(summary)])

        self.assertEqual(0, exit_code)
        self.assertEqual(
            ["summary:1", "run:evidence-privacy", "summary:0"],
            events,
        )

    def test_release_exit_code_blocks_pending_manual_gate(self) -> None:
        qa = _load_qa_module()

        self.assertEqual(
            2,
            qa._qa_exit_code(
                mode="release",
                automated_passed=True,
                release_ready=False,
            ),
        )
        self.assertEqual(
            0,
            qa._qa_exit_code(
                mode="release",
                automated_passed=True,
                release_ready=True,
            ),
        )
        self.assertEqual(
            1,
            qa._qa_exit_code(
                mode="full",
                automated_passed=False,
                release_ready=None,
            ),
        )

    def test_preview_bundle_digest_requires_exact_five_file_contract(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir)
            for name in qa._PUBLIC_PREVIEW_FILES:
                (bundle / name).write_text(name, encoding="utf-8")

            first_digest = qa._public_preview_bundle_sha256(bundle)
            self.assertIsNotNone(first_digest)
            self.assertEqual(64, len(first_digest))

            (bundle / "index.html").write_text("changed", encoding="utf-8")
            second_digest = qa._public_preview_bundle_sha256(bundle)
            self.assertNotEqual(first_digest, second_digest)

            (bundle / "unexpected.txt").write_text("blocked", encoding="utf-8")
            self.assertIsNone(qa._public_preview_bundle_sha256(bundle))

    def test_artifact_placeholders_resolve_beneath_the_requested_run_directory(self) -> None:
        qa = _load_qa_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            step = qa.Step(
                "artifact-probe",
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path(r'{artifact_dir}/probe.txt').write_text('ok')",
                ),
            )
            result = qa.run_step(step, artifact_dir=run_dir)

            self.assertEqual(0, result.exit_code)
            self.assertEqual("ok", (run_dir / "probe.txt").read_text(encoding="utf-8"))
            self.assertTrue((run_dir / "logs" / "artifact-probe.log").is_file())

    def test_offline_guard_blocks_network_in_python_subprocesses(self) -> None:
        guard_dir = ROOT / "tests" / "offline_guard"
        env = os.environ.copy()
        env["ACCOUNTING_AGENT_TEST_OFFLINE"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(guard_dir), env.get("PYTHONPATH", "")) if part
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import socket\n"
                    "try:\n"
                    " socket.create_connection(('example.com', 443), timeout=0.01)\n"
                    "except RuntimeError as exc:\n"
                    " print(str(exc))\n"
                    " raise SystemExit(77)\n"
                ),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(77, result.returncode)
        self.assertIn("network disabled", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
