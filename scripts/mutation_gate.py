#!/usr/bin/env python3
"""Fail closed when a curated authority-weakening mutant is not killed."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


KILLED_EXIT_CODE = 1
_KNOWN_STATUSES = {
    KILLED_EXIT_CODE: "killed",
    0: "survived",
    -6: "suspicious",
    33: "no_tests",
}


def _status(exit_code: int | None) -> str:
    if exit_code is None:
        return "missing"
    return _KNOWN_STATUSES.get(exit_code, "unexpected_exit")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_metadata_path(mutants_root: Path, relative_name: object) -> Path:
    if not isinstance(relative_name, str) or not relative_name.strip():
        raise ValueError("metadata_file must be a non-empty relative path")
    relative_path = Path(relative_name)
    resolved_root = mutants_root.resolve()
    resolved_path = (mutants_root / relative_path).resolve()
    if relative_path.is_absolute() or not resolved_path.is_relative_to(resolved_root):
        raise ValueError("metadata_file must stay beneath the mutants root")
    return resolved_path


def _metadata_exit_codes(path: Path) -> dict[str, int]:
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("exit_code_by_key"), dict
    ):
        raise ValueError(f"invalid mutmut metadata schema: {path.name}")
    result: dict[str, int] = {}
    for mutant_id, exit_code in payload["exit_code_by_key"].items():
        if not isinstance(mutant_id, str) or isinstance(exit_code, bool) or not isinstance(
            exit_code, int
        ):
            raise ValueError(f"invalid mutmut exit-code entry: {path.name}")
        result[mutant_id] = exit_code
    return result


def _all_result_counts(mutants_root: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for metadata_path in sorted(mutants_root.rglob("*.meta")):
        for exit_code in _metadata_exit_codes(metadata_path).values():
            counts[_status(exit_code)] += 1
    return dict(sorted(counts.items()))


def run_gate(target_manifest: Path, mutants_root: Path, output: Path) -> bool:
    manifest = _read_json(target_manifest)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("mutation target manifest must use schema_version 1")
    targets = manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("mutation target manifest must contain at least one target")

    target_ids = [
        target.get("mutant_id") if isinstance(target, dict) else None
        for target in targets
    ]
    if any(not isinstance(mutant_id, str) or not mutant_id for mutant_id in target_ids):
        raise ValueError("every mutation target must have a non-empty mutant_id")
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("mutation target IDs must be unique")

    metadata_cache: dict[Path, dict[str, int]] = {}
    results: list[dict[str, object]] = []
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("every mutation target must be an object")
        boundary = target.get("safety_boundary")
        if not isinstance(boundary, str) or not boundary.strip():
            raise ValueError("every mutation target must explain its safety_boundary")
        metadata_path = _validated_metadata_path(
            mutants_root,
            target.get("metadata_file"),
        )
        if not metadata_path.is_file():
            raise ValueError(f"mutmut metadata is missing: {metadata_path.name}")
        if metadata_path not in metadata_cache:
            metadata_cache[metadata_path] = _metadata_exit_codes(metadata_path)
        mutant_id = str(target["mutant_id"])
        exit_code = metadata_cache[metadata_path].get(mutant_id)
        results.append(
            {
                "mutant_id": mutant_id,
                "metadata_file": str(target["metadata_file"]),
                "safety_boundary": boundary,
                "status": _status(exit_code),
                "exit_code": exit_code,
            }
        )

    target_counts: Counter[str] = Counter(result["status"] for result in results)
    target_counts["total"] = len(results)
    target_counts["failed"] = sum(
        result["status"] != "killed" for result in results
    )
    passed = target_counts["failed"] == 0
    payload = {
        "schema_version": 1,
        "passed": passed,
        "policy": "Every curated authority-weakening mutant must be killed by tests.",
        "target_counts": dict(sorted(target_counts.items())),
        "all_mutant_counts": _all_result_counts(mutants_root),
        "targets": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return passed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate curated safety-critical mutmut results"
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=Path("qa/mutation-safety-targets.json"),
    )
    parser.add_argument("--mutants-root", type=Path, default=Path("mutants"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        passed = run_gate(args.targets, args.mutants_root, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Mutation gate failed: {exc}", file=sys.stderr)
        return 2
    if not passed:
        print(
            f"Mutation gate failed; inspect {args.output} for surviving safety targets.",
            file=sys.stderr,
        )
        return 1
    print(f"Mutation safety gate passed: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
