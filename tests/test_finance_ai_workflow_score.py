from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "use-ai-in-finance-sweden" / "scripts" / "score_workflow.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("finance_ai_workflow_score", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


score_workflow = _load_module()


def _base_workflow(**overrides):
    raw = {
        "name": "Synthetic monthly variance analysis",
        "frequency_per_month": 1,
        "minutes_per_run": 240,
        "standardization": 4,
        "verification": "deterministic",
        "data_sensitivity": "internal",
        "decision_consequence": "moderate",
        "reversibility": "reversible",
    }
    raw.update(overrides)
    return score_workflow.Workflow.from_mapping(raw)


class FinanceAIWorkflowScoreTests(unittest.TestCase):
    def test_reversible_deterministic_work_is_a_reviewable_candidate(self) -> None:
        result = score_workflow.assess(_base_workflow())

        self.assertEqual(result["execution_lane"], "assist-or-automate-locally")
        self.assertEqual(result["state"], "planning-only")
        self.assertGreater(result["annual_manual_hours"], 0)

    def test_payment_or_bank_change_requires_human_execution(self) -> None:
        result = score_workflow.assess(
            _base_workflow(
                payment_or_bank_change=True,
                decision_consequence="critical",
                reversibility="irreversible",
            )
        )

        self.assertEqual(result["execution_lane"], "human-execution-only")
        self.assertEqual(result["pilot_priority"], "decompose-first")
        self.assertTrue(any("segregation of duties" in item for item in result["required_controls"]))

    def test_credentials_force_synthetic_metadata_only(self) -> None:
        result = score_workflow.assess(_base_workflow(contains_credentials=True))

        self.assertEqual(result["execution_lane"], "synthetic-metadata-only")

    def test_sampled_verification_requires_review(self) -> None:
        result = score_workflow.assess(_base_workflow(verification="sampled"))

        self.assertEqual(result["execution_lane"], "draft-with-review")

    def test_special_category_data_requires_controlled_pilot(self) -> None:
        result = score_workflow.assess(
            _base_workflow(
                data_sensitivity="special-category",
                decision_consequence="low",
            )
        )

        self.assertEqual(result["execution_lane"], "controlled-pilot")

    def test_unknown_fields_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            score_workflow.Workflow.from_mapping(
                {
                    **_base_workflow().__dict__,
                    "invented_permission": True,
                }
            )


if __name__ == "__main__":
    unittest.main()
