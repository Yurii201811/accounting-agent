#!/usr/bin/env python3
"""Score synthetic finance-workflow metadata for pilot selection.

This utility never needs transaction data, documents, credentials, names, account
numbers, or other client information. It produces a conservative planning signal;
it is not an accounting, tax, legal, security, or authorization decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VERIFICATION_WEIGHTS = {
    "deterministic": 1.0,
    "sampled": 0.7,
    "judgment": 0.35,
}
SENSITIVITY_RISK = {
    "public": 0,
    "internal": 1,
    "confidential": 3,
    "personal": 4,
    "special-category": 6,
}
CONSEQUENCE_RISK = {
    "low": 0,
    "moderate": 2,
    "high": 4,
    "critical": 6,
}
REVERSIBILITY_RISK = {
    "reversible": 0,
    "reviewable": 2,
    "irreversible": 5,
}


@dataclass(frozen=True)
class Workflow:
    name: str
    frequency_per_month: float
    minutes_per_run: float
    standardization: int
    verification: str
    data_sensitivity: str
    decision_consequence: str
    reversibility: str
    external_system_write: bool = False
    external_communication: bool = False
    final_posting_or_approval: bool = False
    payment_or_bank_change: bool = False
    tax_or_filing: bool = False
    delete_or_settings_change: bool = False
    contains_credentials: bool = False
    changed_supplier_bank_details: bool = False
    possible_duplicate: bool = False
    unknown_supplier: bool = False
    uncertain_vat: bool = False

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "Workflow":
        required = {
            "name",
            "frequency_per_month",
            "minutes_per_run",
            "standardization",
            "verification",
            "data_sensitivity",
            "decision_consequence",
            "reversibility",
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"unknown fields: {', '.join(unknown)}")

        workflow = cls(**raw)
        workflow.validate()
        return workflow

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if not _is_number(self.frequency_per_month) or self.frequency_per_month < 0:
            raise ValueError("frequency_per_month must be a non-negative number")
        if not _is_number(self.minutes_per_run) or self.minutes_per_run < 0:
            raise ValueError("minutes_per_run must be a non-negative number")
        if isinstance(self.standardization, bool) or not isinstance(self.standardization, int):
            raise ValueError("standardization must be an integer from 1 to 5")
        if not 1 <= self.standardization <= 5:
            raise ValueError("standardization must be an integer from 1 to 5")
        _validate_choice("verification", self.verification, VERIFICATION_WEIGHTS)
        _validate_choice("data_sensitivity", self.data_sensitivity, SENSITIVITY_RISK)
        _validate_choice("decision_consequence", self.decision_consequence, CONSEQUENCE_RISK)
        _validate_choice("reversibility", self.reversibility, REVERSIBILITY_RISK)
        for field_name in _boolean_fields():
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be true or false")


def assess(workflow: Workflow) -> dict[str, Any]:
    annual_hours = workflow.frequency_per_month * workflow.minutes_per_run * 12 / 60
    weighted_opportunity_hours = (
        annual_hours
        * workflow.standardization
        / 5
        * VERIFICATION_WEIGHTS[workflow.verification]
    )

    risk_score = (
        SENSITIVITY_RISK[workflow.data_sensitivity]
        + CONSEQUENCE_RISK[workflow.decision_consequence]
        + REVERSIBILITY_RISK[workflow.reversibility]
    )
    if workflow.external_system_write:
        risk_score += 3
    if workflow.external_communication:
        risk_score += 3
    if workflow.final_posting_or_approval:
        risk_score += 7
    if workflow.payment_or_bank_change:
        risk_score += 8
    if workflow.tax_or_filing:
        risk_score += 7
    if workflow.delete_or_settings_change:
        risk_score += 8
    if workflow.changed_supplier_bank_details:
        risk_score += 8
    for flag in (
        workflow.possible_duplicate,
        workflow.unknown_supplier,
        workflow.uncertain_vat,
    ):
        if flag:
            risk_score += 4

    hard_stop = workflow.contains_credentials
    consequential_action = any(
        (
            workflow.external_system_write,
            workflow.external_communication,
            workflow.final_posting_or_approval,
            workflow.payment_or_bank_change,
            workflow.tax_or_filing,
            workflow.delete_or_settings_change,
            workflow.changed_supplier_bank_details,
        )
    )
    high_risk_exception = any(
        (
            workflow.changed_supplier_bank_details,
            workflow.possible_duplicate,
            workflow.unknown_supplier,
            workflow.uncertain_vat,
        )
    )

    if hard_stop:
        lane = "synthetic-metadata-only"
        rationale = "Credentials or secrets must not enter the model or assessment input."
    elif consequential_action:
        lane = "human-execution-only"
        rationale = "An agent may inspect or prepare a draft, but a named human must execute the action."
    elif (
        workflow.data_sensitivity == "special-category"
        or high_risk_exception
        or risk_score >= 10
    ):
        lane = "controlled-pilot"
        rationale = "Use only in an approved environment with explicit review and exception handling."
    elif workflow.verification in {"sampled", "judgment"} or risk_score >= 4:
        lane = "draft-with-review"
        rationale = "Use the agent for analysis or drafting and require documented human review."
    else:
        lane = "assist-or-automate-locally"
        rationale = "The workflow is reversible and readily verifiable; retain checks and an owner."

    if hard_stop or consequential_action:
        pilot_priority = "decompose-first"
    elif weighted_opportunity_hours >= 40 and workflow.standardization >= 4:
        pilot_priority = "high"
    elif weighted_opportunity_hours >= 12 and workflow.standardization >= 3:
        pilot_priority = "medium"
    else:
        pilot_priority = "low"

    controls = [
        "Use only approved tools, accounts, and data locations.",
        "Record source, period, assumptions, output state, owner, and reviewer.",
        "Reconcile key totals and retain a before/after diff or equivalent evidence.",
    ]
    if workflow.data_sensitivity in {"personal", "special-category"}:
        controls.append(
            "Confirm purpose, legal basis, data minimization, access, processor terms, and DPIA need."
        )
    if workflow.data_sensitivity in {"confidential", "personal", "special-category"}:
        controls.append("Use an organization-approved environment; do not use an unapproved personal account.")
    if consequential_action:
        controls.append("Separate preparation from approval and execution; log the human decision.")
    if workflow.payment_or_bank_change or workflow.changed_supplier_bank_details:
        controls.append("Verify bank details out-of-band and require segregation of duties.")
    if workflow.possible_duplicate:
        controls.append("Block the item and resolve duplicate evidence before any downstream action.")
    if workflow.unknown_supplier:
        controls.append("Block the item until supplier identity and ownership are verified.")
    if workflow.uncertain_vat:
        controls.append("Escalate VAT treatment to a qualified reviewer using current authoritative sources.")
    if workflow.tax_or_filing:
        controls.append("Keep filing and tax decisions with an authorized human; verify current rules and period.")

    return {
        "schema_version": "1.0",
        "name": workflow.name,
        "state": "planning-only",
        "annual_manual_hours": round(annual_hours, 2),
        "weighted_opportunity_hours": round(weighted_opportunity_hours, 2),
        "risk_score": risk_score,
        "execution_lane": lane,
        "pilot_priority": pilot_priority,
        "rationale": rationale,
        "required_controls": controls,
        "warning": (
            "Planning aid only. Reassess against current Swedish law, company policy, "
            "contracts, approved tooling, and the exact workflow before use."
        ),
    }


def render_markdown(result: dict[str, Any]) -> str:
    controls = "\n".join(f"- {item}" for item in result["required_controls"])
    return (
        f"# {result['name']}\n\n"
        f"- State: `{result['state']}`\n"
        f"- Execution lane: `{result['execution_lane']}`\n"
        f"- Pilot priority: `{result['pilot_priority']}`\n"
        f"- Annual manual hours: {result['annual_manual_hours']:.2f}\n"
        f"- Weighted opportunity hours: {result['weighted_opportunity_hours']:.2f}\n"
        f"- Risk score: {result['risk_score']}\n\n"
        f"{result['rationale']}\n\n"
        f"## Required controls\n\n{controls}\n\n"
        f"> {result['warning']}\n"
    )


def _validate_choice(field_name: str, value: Any, choices: dict[str, Any]) -> None:
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{field_name} must be one of: {allowed}")


def _boolean_fields() -> tuple[str, ...]:
    non_boolean = {
        "name",
        "frequency_per_month",
        "minutes_per_run",
        "standardization",
        "verification",
        "data_sensitivity",
        "decision_consequence",
        "reversibility",
    }
    return tuple(name for name in Workflow.__dataclass_fields__ if name not in non_boolean)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score non-sensitive finance-workflow metadata for AI pilot selection."
    )
    parser.add_argument("input", type=Path, help="JSON workflow metadata file")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        raw = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("input must contain one JSON object")
        result = assess(Workflow.from_mapping(raw))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "markdown":
        print(render_markdown(result), end="")
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
