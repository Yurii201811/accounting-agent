"""Deterministic policy decisions for proposed accounting actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from .risk_review import RiskFinding


POLICY_VERSION = "accounting-policy-v1"


class PermissionMode(str, Enum):
    AUTO_ALLOWED = "auto_allowed"
    DRAFT_ONLY = "draft_only"
    APPROVAL_REQUIRED = "approval_required"
    ESCALATION_REQUIRED = "escalation_required"
    FORBIDDEN = "forbidden"


class ActionType(str, Enum):
    READ_ANALYSIS = "read_analysis"
    DRAFT_SUPPLIER_INVOICE = "draft_supplier_invoice"
    DRAFT_VOUCHER = "draft_voucher"
    DRAFT_BANK_RECONCILIATION = "draft_bank_reconciliation"
    ATTACH_SOURCE_DOCUMENT = "attach_source_document"
    CREATE_SUPPLIER = "create_supplier"
    UPDATE_SUPPLIER = "update_supplier"
    UPDATE_SUPPLIER_BANK_DETAILS = "update_supplier_bank_details"
    RECONCILE_BANK_TRANSACTION = "reconcile_bank_transaction"
    POST_VOUCHER = "post_voucher"
    SEND_INVOICE = "send_invoice"
    APPROVE_SUPPLIER_INVOICE = "approve_supplier_invoice"
    START_PAYMENT = "start_payment"
    FILE_TAX_RETURN = "file_tax_return"
    SEND_EMAIL = "send_email"
    FILE_DOCUMENT = "file_document"
    DELETE_RECORD = "delete_record"
    CHANGE_SETTINGS = "change_settings"


MODE_SEVERITY = {
    PermissionMode.AUTO_ALLOWED: 0,
    PermissionMode.DRAFT_ONLY: 1,
    PermissionMode.APPROVAL_REQUIRED: 2,
    PermissionMode.ESCALATION_REQUIRED: 3,
    PermissionMode.FORBIDDEN: 4,
}

REVIEW_ORDER = (
    "accountant_review",
    "senior_accountant_review",
    "client_responsible_review",
    "tax_review",
    "security_review",
)

DEFAULT_ACTION_MODES = {
    ActionType.READ_ANALYSIS: PermissionMode.AUTO_ALLOWED,
    ActionType.DRAFT_SUPPLIER_INVOICE: PermissionMode.DRAFT_ONLY,
    ActionType.DRAFT_VOUCHER: PermissionMode.DRAFT_ONLY,
    ActionType.DRAFT_BANK_RECONCILIATION: PermissionMode.DRAFT_ONLY,
    ActionType.ATTACH_SOURCE_DOCUMENT: PermissionMode.DRAFT_ONLY,
    ActionType.CREATE_SUPPLIER: PermissionMode.APPROVAL_REQUIRED,
    ActionType.UPDATE_SUPPLIER: PermissionMode.APPROVAL_REQUIRED,
    ActionType.UPDATE_SUPPLIER_BANK_DETAILS: PermissionMode.ESCALATION_REQUIRED,
    ActionType.RECONCILE_BANK_TRANSACTION: PermissionMode.FORBIDDEN,
    ActionType.POST_VOUCHER: PermissionMode.FORBIDDEN,
    ActionType.SEND_INVOICE: PermissionMode.FORBIDDEN,
    ActionType.APPROVE_SUPPLIER_INVOICE: PermissionMode.FORBIDDEN,
    ActionType.START_PAYMENT: PermissionMode.FORBIDDEN,
    ActionType.FILE_TAX_RETURN: PermissionMode.ESCALATION_REQUIRED,
    ActionType.SEND_EMAIL: PermissionMode.APPROVAL_REQUIRED,
    ActionType.FILE_DOCUMENT: PermissionMode.APPROVAL_REQUIRED,
    ActionType.DELETE_RECORD: PermissionMode.FORBIDDEN,
    ActionType.CHANGE_SETTINGS: PermissionMode.FORBIDDEN,
}

EXTERNAL_WRITE_ACTIONS = frozenset(
    action
    for action, mode in DEFAULT_ACTION_MODES.items()
    if mode is not PermissionMode.AUTO_ALLOWED
)


@dataclass(frozen=True)
class AmountThresholds:
    """Amount thresholds in minor currency units, for example ore for SEK."""

    draft_without_review_minor: int = 10_000_00
    escalation_required_minor: int = 100_000_00


@dataclass(frozen=True)
class PolicyConfig:
    policy_version: str = POLICY_VERSION
    default_amount_thresholds: AmountThresholds = field(default_factory=AmountThresholds)
    client_amount_thresholds: Mapping[str, AmountThresholds] = field(default_factory=dict)
    minimum_vat_confidence: float = 0.90
    minimum_ocr_confidence: float = 0.85
    duplicate_review_threshold: float = 0.50

    def amount_thresholds_for(self, client_id: str) -> AmountThresholds:
        return self.client_amount_thresholds.get(client_id, self.default_amount_thresholds)


@dataclass(frozen=True)
class PolicyContext:
    action_type: ActionType
    client_id: str
    amount_minor: int = 0
    supplier_known: bool = True
    customer_known: bool = True
    bank_details_changed: bool = False
    duplicate_risk: float = 0.0
    vat_confidence: float = 1.0
    ocr_confidence: float = 1.0
    period_locked: bool = False
    new_supplier: bool = False
    destructive_action: bool = False
    external_communication: bool = False
    tax_filing_payment: bool = False
    risk_findings: tuple[RiskFinding, ...] = ()
    risk_evidence_complete: bool = False


@dataclass(frozen=True)
class PolicyDecision:
    action_type: ActionType
    client_id: str
    permission_mode: PermissionMode
    policy_version: str
    amount_thresholds: AmountThresholds
    required_reviews: tuple[str, ...]
    reasons: tuple[str, ...]
    is_external_write: bool


def evaluate_policy(
    context: PolicyContext,
    config: PolicyConfig | None = None,
) -> PolicyDecision:
    """Return a deterministic permission decision for an accounting action."""

    config = config or PolicyConfig()
    action_type = ActionType(context.action_type)
    thresholds = config.amount_thresholds_for(context.client_id)
    _validate_context(context)

    mode = DEFAULT_ACTION_MODES.get(action_type, PermissionMode.APPROVAL_REQUIRED)
    reasons: list[str] = [f"default:{action_type.value}"]
    required_reviews: set[str] = set()
    is_external_write = action_type in EXTERNAL_WRITE_ACTIONS

    if mode is PermissionMode.APPROVAL_REQUIRED:
        required_reviews.add("accountant_review")
    elif mode is PermissionMode.ESCALATION_REQUIRED:
        required_reviews.update({"accountant_review", "senior_accountant_review"})

    if not context.client_id.strip():
        mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
        reasons.append("client_id_missing")
        required_reviews.add("accountant_review")

    if (
        is_external_write
        and context.client_id.strip().casefold() == "unmapped"
        and mode is not PermissionMode.FORBIDDEN
    ):
        mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
        reasons.append("client_mapping_unmapped")
        required_reviews.add("accountant_review")

    if is_external_write and not context.risk_evidence_complete and mode is not PermissionMode.FORBIDDEN:
        mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
        reasons.append("risk_evidence_incomplete")
        required_reviews.add("accountant_review")

    if context.destructive_action or action_type in {
        ActionType.DELETE_RECORD,
        ActionType.CHANGE_SETTINGS,
    }:
        mode = PermissionMode.FORBIDDEN
        reasons.append("destructive_or_settings_action")
        required_reviews.clear()

    if context.period_locked and is_external_write:
        mode = PermissionMode.FORBIDDEN
        reasons.append("period_locked")
        required_reviews.clear()

    if mode is not PermissionMode.FORBIDDEN:
        if context.tax_filing_payment or action_type in {
            ActionType.START_PAYMENT,
            ActionType.FILE_TAX_RETURN,
        }:
            mode = _stricter(mode, PermissionMode.ESCALATION_REQUIRED)
            reasons.append("tax_filing_or_payment")
            required_reviews.update(
                {"accountant_review", "senior_accountant_review", "client_responsible_review"}
            )

        if context.bank_details_changed or action_type is ActionType.UPDATE_SUPPLIER_BANK_DETAILS:
            mode = _stricter(mode, PermissionMode.ESCALATION_REQUIRED)
            reasons.append("bank_details_changed")
            required_reviews.update(
                {"accountant_review", "senior_accountant_review", "security_review"}
            )

        if context.amount_minor >= thresholds.escalation_required_minor:
            mode = _stricter(mode, PermissionMode.ESCALATION_REQUIRED)
            reasons.append("amount_exceeds_escalation_threshold")
            required_reviews.update({"accountant_review", "senior_accountant_review"})
        elif (
            context.amount_minor > thresholds.draft_without_review_minor
            and is_external_write
        ):
            mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
            reasons.append("amount_exceeds_draft_threshold")
            required_reviews.add("accountant_review")

        if context.new_supplier or not context.supplier_known:
            mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
            reasons.append("supplier_not_previously_known")
            required_reviews.add("accountant_review")

        if not context.customer_known:
            mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
            reasons.append("customer_not_previously_known")
            required_reviews.add("accountant_review")

        if context.duplicate_risk >= config.duplicate_review_threshold:
            mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
            reasons.append("duplicate_risk")
            required_reviews.add("accountant_review")

        if context.vat_confidence < config.minimum_vat_confidence:
            mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
            reasons.append("vat_confidence_below_threshold")
            required_reviews.add("accountant_review")

        if context.ocr_confidence < config.minimum_ocr_confidence:
            mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
            reasons.append("ocr_confidence_below_threshold")
            required_reviews.add("accountant_review")

        if context.external_communication or action_type in {
            ActionType.SEND_EMAIL,
            ActionType.SEND_INVOICE,
        }:
            mode = _stricter(mode, PermissionMode.APPROVAL_REQUIRED)
            reasons.append("external_communication")
            required_reviews.add("accountant_review")

        for finding in context.risk_findings:
            impact_mode = PermissionMode(finding.policy_impact.minimum_permission_mode)
            mode = _stricter(mode, impact_mode)
            reasons.append(finding.policy_impact.reason or f"risk:{finding.signal.value}")
            required_reviews.update(finding.policy_impact.required_reviews)
            if impact_mode is PermissionMode.FORBIDDEN:
                required_reviews.clear()

    return PolicyDecision(
        action_type=action_type,
        client_id=context.client_id,
        permission_mode=mode,
        policy_version=config.policy_version,
        amount_thresholds=thresholds,
        required_reviews=_ordered_reviews(required_reviews),
        reasons=tuple(reasons),
        is_external_write=is_external_write,
    )


def _stricter(left: PermissionMode, right: PermissionMode) -> PermissionMode:
    if MODE_SEVERITY[right] > MODE_SEVERITY[left]:
        return right
    return left


def _ordered_reviews(required_reviews: set[str]) -> tuple[str, ...]:
    return tuple(review for review in REVIEW_ORDER if review in required_reviews)


def _validate_context(context: PolicyContext) -> None:
    if context.amount_minor < 0:
        raise ValueError("amount_minor must not be negative")
    _validate_confidence("duplicate_risk", context.duplicate_risk)
    _validate_confidence("vat_confidence", context.vat_confidence)
    _validate_confidence("ocr_confidence", context.ocr_confidence)


def _validate_confidence(name: str, value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")
