# Policy and execution permits

This repository uses a deterministic policy gate before any agent can perform an external write. Agents may inspect, extract, reason, and propose actions, but Fortnox writes, email sending, supplier changes, filing, and other external mutations must pass through this layer first. Voucher posting, invoice sending, supplier-invoice approval, payments, deleting, and settings changes are forbidden.

The email adapter is a local stub. The Fortnox adapter supports mocked/dry-run reads and draft payload creation, but it still defaults to no live writes and does not allow unrestricted Fortnox mutation.

## Permission modes

The policy engine returns one of five modes:

- `auto_allowed`: low-risk reads and analysis only.
- `draft_only`: a low-risk draft action may be prepared, such as a draft supplier invoice, after a matching execution permit is issued.
- `approval_required`: an accountant review is required before an execution permit can be issued.
- `escalation_required`: higher-risk review is required, such as senior accountant, client responsible, tax, or security review.
- `forbidden`: the action must not execute.

## Policy inputs

Every proposed action is evaluated with `PolicyContext` from `accounting_agent.policy`.

Required inputs:

- `action_type`
- `client_id`

Risk inputs:

- `amount_minor`
- `supplier_known`
- `customer_known`
- `bank_details_changed`
- `duplicate_risk`
- `vat_confidence`
- `ocr_confidence`
- `period_locked`
- `new_supplier`
- `destructive_action`
- `external_communication`
- `tax_filing_payment`
- `risk_evidence_complete`

For external-write actions, `risk_evidence_complete=False` fails closed to
`approval_required`. A low-risk `draft_only` decision is only possible when the
caller explicitly supplies the known risk facts and marks the evidence complete.
External writes for `client_id="unmapped"` also fail closed to
`approval_required`.

Amounts use minor currency units, for example ore for SEK. Default thresholds are:

- draft without review up to `10_000_00`
- escalation from `100_000_00`

Client-specific thresholds can be supplied through `PolicyConfig.client_amount_thresholds`.

## Deterministic checks

The policy version is `accounting-policy-v1`. Decisions are deterministic for the same context and config.

The default rules are:

- Reads and analysis are `auto_allowed`.
- Low-risk draft supplier invoices, draft vouchers, and draft attachments are `draft_only`.
- Supplier creation, supplier updates, sending email, and filing documents require approval.
- Tax returns require escalation.
- Voucher posting, invoice sending, supplier-invoice approval, payments, deletes, settings changes, explicit destructive actions, and writes into a locked period are forbidden.
- Changed bank details require escalation.
- Unknown or new suppliers require approval.
- Amounts above the draft threshold require approval; amounts above the escalation threshold require escalation.
- VAT confidence below `0.90`, OCR confidence below `0.85`, or duplicate risk at or above `0.50` requires approval.
- External communication requires approval.
- Structured Openclaw risk findings in `PolicyContext.risk_findings` can raise the mode to approval, escalation, or forbidden according to each finding's `policy_impact`.

## Execution permits

Adapters do not accept policy decisions directly. They require an `ExecutionPermit` from `accounting_agent.permits`.

A permit contains:

- `permit_id`
- `case_id`
- `client_id`
- `allowed_action`
- `payload_hash`
- `policy_version`
- `required_reviews`
- `permission_mode`
- `expires_at`
- `idempotency_key`
- `issued_at`
- `approved_reviews`

The payload hash is a canonical SHA-256 hash of the exact payload. If the payload changes after permit issuance, the adapter rejects the write.

For `approval_required` and `escalation_required` decisions, the permit issuer refuses to issue a permit until all required reviews are provided. `forbidden` decisions never receive permits.

Permits can be stored in memory for tests or in the SQLite-compatible `SQLitePermitStore`.

The permit issuer recomputes the current policy decision from the supplied
context before issuing a permit. A caller cannot lower the decision mode by
passing a hand-built `PolicyDecision`.

The permit validator rejects missing permit ids, missing client/case ids,
missing or non-matching idempotency keys, non-external-write actions,
`auto_allowed`/`forbidden` permit modes, expired permits, changed payloads, and
reviewed modes that do not carry the required review types. The idempotency key
must match the permit's case, action, payload hash, and policy version.

## Agent flow

1. Build the proposed payload, but do not write externally.
2. Build a `PolicyContext` with all known risk signals.
3. Call `evaluate_policy(context)`.
4. If the mode is `forbidden`, stop and report the reason.
5. If reviews are required, collect those reviews outside the agent before continuing.
6. Issue a permit with `PermitIssuer.issue(...)` using the exact payload that will be written.
7. Call the adapter with `action_type`, `case_id`, `payload`, and `permit`.
8. The adapter validates the case, action, payload hash, policy version, expiry, and approved reviews before reaching its write implementation.

Example:

```python
from accounting_agent import (
    ActionType,
    FortnoxWriteAdapter,
    PermitIssuer,
    PolicyContext,
    evaluate_policy,
)

payload = {"supplier_id": "supplier_1", "amount_minor": 150000}
context = PolicyContext(
    action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
    client_id="client_123",
    amount_minor=150000,
    supplier_known=True,
    customer_known=True,
    bank_details_changed=False,
    duplicate_risk=0.0,
    vat_confidence=0.99,
    ocr_confidence=0.98,
    period_locked=False,
    new_supplier=False,
    destructive_action=False,
    external_communication=False,
    tax_filing_payment=False,
    risk_evidence_complete=True,
)

decision = evaluate_policy(context)
permit = PermitIssuer().issue(
    decision=decision,
    context=context,
    case_id="case_123",
    payload=payload,
)

result = FortnoxWriteAdapter().execute(
    action_type=ActionType.DRAFT_SUPPLIER_INVOICE,
    case_id="case_123",
    payload=payload,
    permit=permit,
)
```

The legacy `FortnoxWriteAdapter` returns `permit_validated_no_live_write`. The newer `FortnoxAdapter` in `accounting_agent.adapters.fortnox` supports safe reference reads, local draft payload generation, dry-run draft creation, idempotency checks, and permit-gated supplier-invoice draft creation for future approved sandbox use.

Important live-write constraint: `draft_only` permits are dry-run only. If the
Fortnox adapter is ever configured with `dry_run=false` and
`allow_draft_writes=true`, supplier-invoice draft creation requires an
`approval_required` or `escalation_required` permit with recorded approved
reviews. This keeps low-risk local proposal work from silently becoming a live
Fortnox write.
