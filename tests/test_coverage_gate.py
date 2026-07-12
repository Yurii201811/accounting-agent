from __future__ import annotations

import unittest

from scripts.coverage_gate import CRITICAL_MODULES, evaluate_coverage


def _summary(*, lines: int, statements: int, branches: int, covered_branches: int) -> dict:
    return {
        "covered_lines": lines,
        "num_statements": statements,
        "num_branches": branches,
        "covered_branches": covered_branches,
    }


class CoverageGateTests(unittest.TestCase):
    def test_bounded_read_connectors_are_safety_critical(self) -> None:
        self.assertIn("accounting_agent/adapters/read_only.py", CRITICAL_MODULES)

    def test_release_thresholds_pass_at_required_line_and_branch_percentages(self) -> None:
        report = {
            "totals": _summary(
                lines=85,
                statements=100,
                branches=100,
                covered_branches=80,
            ),
            "files": {
                module: {
                    "summary": _summary(
                        lines=95,
                        statements=100,
                        branches=100,
                        covered_branches=90,
                    )
                }
                for module in CRITICAL_MODULES
            },
        }

        self.assertEqual([], evaluate_coverage(report))

    def test_gate_reports_overall_critical_and_missing_module_failures(self) -> None:
        modules = list(CRITICAL_MODULES)
        report = {
            "totals": _summary(
                lines=84,
                statements=100,
                branches=100,
                covered_branches=79,
            ),
            "files": {
                module: {
                    "summary": _summary(
                        lines=95,
                        statements=100,
                        branches=100,
                        covered_branches=89,
                    )
                }
                for module in modules[:-1]
            },
        }

        errors = evaluate_coverage(report)

        self.assertTrue(any("overall line coverage" in error for error in errors))
        self.assertTrue(any("overall branch coverage" in error for error in errors))
        self.assertTrue(any("critical branch coverage" in error for error in errors))
        self.assertTrue(any(modules[-1] in error and "missing" in error for error in errors))

    def test_measured_baseline_is_a_floor_above_the_nominal_threshold(self) -> None:
        report = {
            "totals": _summary(
                lines=90,
                statements=100,
                branches=100,
                covered_branches=85,
            ),
            "files": {
                module: {
                    "summary": _summary(
                        lines=95,
                        statements=100,
                        branches=100,
                        covered_branches=90,
                    )
                }
                for module in CRITICAL_MODULES
            },
        }

        errors = evaluate_coverage(
            report,
            baseline={"overall_line_percent": 91.0, "overall_branch_percent": 86.0},
        )

        self.assertTrue(any("91.00%" in error for error in errors))
        self.assertTrue(any("86.00%" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
