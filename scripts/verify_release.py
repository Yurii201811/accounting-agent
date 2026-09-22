#!/usr/bin/env python3
"""One-command local release gate; runs only synthetic checks."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / ".local/release-verification.json")
    args = parser.parse_args()
    results = {}
    commands = {
        "unit_and_integration_tests": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        "system_controls": [sys.executable, "-m", "accounting_agent.cli", "v1-system-check", "--json"],
        "javascript_syntax": ["node", "--check", "accounting_agent/static/system.js"],
    }
    for name, command in commands.items():
        print(f"Checking {name}…", flush=True)
        if shutil.which(command[0]) is None:
            results[name] = {"passed": False, "output": f"Required tool is missing: {command[0]}"}
            continue
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        output = (completed.stdout + completed.stderr).strip()
        passed = completed.returncode == 0
        if name == "system_controls" and passed:
            controls = json.loads(completed.stdout)
            passed = controls.get("passed") is True and all(controls.get(key) == 0 for key in
                      ("erp_writes", "external_calls", "hosted_model_calls"))
        results[name] = {"passed": passed, "output": output}
        print("PASS" if passed else "FAIL", flush=True)
    report = {"environment": "synthetic_local", "passed": all(r["passed"] for r in results.values()),
              "production_ready": False, "checks": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Report: {args.report}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
