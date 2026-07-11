from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import accounting_agent
from accounting_agent.cli import build_parser
from accounting_agent.operations_cockpit import build_public_preview


ROOT = Path(__file__).resolve().parents[1]
TRACEABILITY_PATH = ROOT / "qa" / "traceability.json"
V1_PUBLIC_API_PATH = ROOT / "qa" / "public-api-v1.json"


class QATraceabilityTests(unittest.TestCase):
    def test_original_v1_public_api_remains_an_immutable_compatibility_subset(self) -> None:
        baseline = json.loads(V1_PUBLIC_API_PATH.read_text(encoding="utf-8"))
        exports = baseline["exports"]

        self.assertEqual(1, baseline["schema_version"])
        self.assertEqual("1.0.0", baseline["release"])
        self.assertEqual(142, len(exports))
        self.assertEqual(len(exports), len(set(exports)))
        self.assertLessEqual(set(exports), set(accounting_agent.__all__))
        for export_name in exports:
            with self.subTest(export=export_name):
                self.assertIsNotNone(getattr(accounting_agent, export_name))

    def test_traceability_catalog_covers_every_public_surface(self) -> None:
        catalog = json.loads(TRACEABILITY_PATH.read_text(encoding="utf-8"))
        story_ids = {story["id"] for story in catalog["user_stories"]}

        export_groups = catalog["public_python_api_groups"]
        mapped_exports = {
            export_name for group in export_groups for export_name in group["members"]
        }
        self.assertEqual(set(accounting_agent.__all__), mapped_exports)
        for export_name in accounting_agent.__all__:
            with self.subTest(export=export_name):
                exported = getattr(accounting_agent, export_name)
                self.assertIsNotNone(exported)
                self.assertFalse(
                    getattr(exported, "__module__", "").startswith("tests."),
                    f"Public export must resolve to application code: {export_name}",
                )

        parser = build_parser()
        subparser_action = next(
            action for action in parser._actions if getattr(action, "choices", None)
        )
        self.assertEqual(
            set(subparser_action.choices),
            {command["name"] for command in catalog["cli_commands"]},
        )

        # Public preview output is deliberately confined beneath the declared
        # repository root, so keep this traceability build inside that boundary.
        with tempfile.TemporaryDirectory(dir=ROOT) as temp_dir:
            output = Path(temp_dir) / "preview"
            result = build_public_preview(repo_root=ROOT, output_dir=output)
            html = result.output_path.read_text(encoding="utf-8")
        rendered_sections = {
            section_id for section_id in catalog["cockpit_sections"] if f'id="{section_id}"' in html
        }
        self.assertEqual(set(catalog["cockpit_sections"]), rendered_sections)

        for surface in (*export_groups, *catalog["cli_commands"]):
            self.assertTrue(surface["story_ids"])
            self.assertLessEqual(set(surface["story_ids"]), story_ids)
            self.assertIn(
                surface["safety_class"],
                {
                    "deterministic",
                    "review_only",
                    "safety_critical",
                    "forbidden_external",
                },
            )

    def test_every_story_has_acceptance_criteria_and_test_evidence(self) -> None:
        catalog = json.loads(TRACEABILITY_PATH.read_text(encoding="utf-8"))
        for story in catalog["user_stories"]:
            with self.subTest(story=story["id"]):
                self.assertTrue(story["persona"])
                self.assertTrue(story["acceptance_criteria"])
                self.assertTrue(story["test_evidence"])
                for evidence_path in story["test_evidence"]:
                    self.assertTrue(
                        (ROOT / evidence_path).is_file(),
                        f"Traceability evidence does not exist: {evidence_path}",
                    )


if __name__ == "__main__":
    unittest.main()
