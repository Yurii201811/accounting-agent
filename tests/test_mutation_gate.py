from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mutation_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("accounting_agent_mutation_gate", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load scripts/mutation_gate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MutationGateTests(unittest.TestCase):
    def _write_fixture(
        self,
        root: Path,
        *,
        exit_codes: dict[str, int],
        target_ids: tuple[str, ...],
    ) -> tuple[Path, Path]:
        metadata = root / "mutants" / "accounting_agent" / "policy.py.meta"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(
            json.dumps(
                {
                    "durations_by_key": {},
                    "estimated_durations_by_key": {},
                    "exit_code_by_key": exit_codes,
                    "type_check_error_by_key": {},
                }
            ),
            encoding="utf-8",
        )
        manifest = root / "targets.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "targets": [
                        {
                            "mutant_id": mutant_id,
                            "metadata_file": "accounting_agent/policy.py.meta",
                            "safety_boundary": f"Synthetic boundary {index}",
                        }
                        for index, mutant_id in enumerate(target_ids, start=1)
                    ],
                }
            ),
            encoding="utf-8",
        )
        return manifest, root / "mutants"

    def test_gate_passes_only_when_every_curated_safety_mutant_is_killed(self) -> None:
        gate = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_ids = (
                "accounting_agent.policy.x_guard__mutmut_1",
                "accounting_agent.policy.x_guard__mutmut_2",
            )
            manifest, mutants_root = self._write_fixture(
                root,
                exit_codes={target_id: 1 for target_id in target_ids},
                target_ids=target_ids,
            )
            output = root / "summary.json"

            result = gate.run_gate(manifest, mutants_root, output)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertTrue(result)
        self.assertTrue(payload["passed"])
        self.assertEqual(2, payload["target_counts"]["killed"])
        self.assertEqual(0, payload["target_counts"]["failed"])

    def test_survived_suspicious_untested_and_missing_targets_fail_closed(self) -> None:
        gate = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_ids = tuple(
                f"accounting_agent.policy.x_guard__mutmut_{index}"
                for index in range(1, 5)
            )
            manifest, mutants_root = self._write_fixture(
                root,
                exit_codes={
                    target_ids[0]: 0,
                    target_ids[1]: -6,
                    target_ids[2]: 33,
                },
                target_ids=target_ids,
            )
            output = root / "summary.json"

            result = gate.run_gate(manifest, mutants_root, output)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(result)
        self.assertFalse(payload["passed"])
        self.assertEqual(4, payload["target_counts"]["failed"])
        self.assertEqual(
            {"missing", "no_tests", "suspicious", "survived"},
            {target["status"] for target in payload["targets"]},
        )

    def test_manifest_rejects_duplicate_ids_and_metadata_escape(self) -> None:
        gate = _load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, mutants_root = self._write_fixture(
                root,
                exit_codes={"duplicate": 1},
                target_ids=("duplicate", "duplicate"),
            )
            with self.assertRaisesRegex(ValueError, "unique"):
                gate.run_gate(manifest, mutants_root, root / "summary.json")

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["targets"] = [
                {
                    "mutant_id": "escape",
                    "metadata_file": "../outside.meta",
                    "safety_boundary": "Escape attempt",
                }
            ]
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "beneath"):
                gate.run_gate(manifest, mutants_root, root / "summary.json")


if __name__ == "__main__":
    unittest.main()
