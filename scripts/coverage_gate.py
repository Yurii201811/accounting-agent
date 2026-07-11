#!/usr/bin/env python3
"""Enforce the Accounting Agent v1 release coverage contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


OVERALL_LINE_PERCENT = 85.0
OVERALL_BRANCH_PERCENT = 80.0
CRITICAL_BRANCH_PERCENT = 90.0

CRITICAL_MODULES = (
    "accounting_agent/policy.py",
    "accounting_agent/permits.py",
    "accounting_agent/approvals.py",
    "accounting_agent/evidence.py",
    "accounting_agent/autonomy.py",
    "accounting_agent/connector_contract.py",
    "accounting_agent/model_runtime.py",
    "accounting_agent/restricted_fortnox_mcp.py",
    "accounting_agent/adapters/fortnox.py",
)


def _percent(summary: dict[str, Any], covered_key: str, total_key: str) -> float:
    total = int(summary.get(total_key, 0))
    covered = int(summary.get(covered_key, 0))
    if total <= 0:
        return 100.0
    return (covered / total) * 100.0


def evaluate_coverage(
    report: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
) -> list[str]:
    """Return human-readable release-gate failures for a coverage.py JSON report."""

    baseline = baseline or {}
    totals = dict(report.get("totals") or {})
    files = dict(report.get("files") or {})
    errors: list[str] = []

    line_floor = max(
        OVERALL_LINE_PERCENT,
        float(baseline.get("overall_line_percent", 0.0)),
    )
    branch_floor = max(
        OVERALL_BRANCH_PERCENT,
        float(baseline.get("overall_branch_percent", 0.0)),
    )
    line_percent = _percent(totals, "covered_lines", "num_statements")
    branch_percent = _percent(totals, "covered_branches", "num_branches")
    if line_percent + 1e-9 < line_floor:
        errors.append(
            f"overall line coverage {line_percent:.2f}% is below {line_floor:.2f}%"
        )
    if branch_percent + 1e-9 < branch_floor:
        errors.append(
            f"overall branch coverage {branch_percent:.2f}% is below {branch_floor:.2f}%"
        )

    baseline_modules = dict(baseline.get("critical_branch_percent") or {})
    for module in CRITICAL_MODULES:
        file_report = files.get(module)
        if not isinstance(file_report, dict):
            errors.append(f"critical module missing from coverage report: {module}")
            continue
        module_floor = max(
            CRITICAL_BRANCH_PERCENT,
            float(baseline_modules.get(module, 0.0)),
        )
        module_percent = _percent(
            dict(file_report.get("summary") or {}),
            "covered_branches",
            "num_branches",
        )
        if module_percent + 1e-9 < module_floor:
            errors.append(
                "critical branch coverage "
                f"{module} {module_percent:.2f}% is below {module_floor:.2f}%"
            )
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="coverage.py JSON report")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="optional measured baseline JSON; higher values remain floors",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    baseline = (
        json.loads(args.baseline.read_text(encoding="utf-8"))
        if args.baseline
        else None
    )
    errors = evaluate_coverage(report, baseline=baseline)
    if errors:
        for error in errors:
            print(f"coverage gate: {error}", file=sys.stderr)
        return 1
    print("coverage gate: release thresholds satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
