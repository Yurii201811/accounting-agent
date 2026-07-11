# AI system inventory and authority boundary

Status: PRELIMINARY — NOT APPROVED

This inventory separates implemented advisory components from proposed provider
integrations. It is not an EU AI Act classification or compliance assessment.
It does not authorize real-client data, hosted-model processing, autonomous
accounting decisions or external actions.

## Authority rule

Deterministic extraction validation, accounting policy, approval integrity and
connector safety remain mandatory. Models may propose, classify, summarize or
explain. They cannot approve their work, mint trusted identity or permits,
change risk, call connectors directly, post, send, pay, file, delete, alter
settings or change supplier bank details. Provider failure produces a visible
stop, never silent fallback.

## Inventory

| Component | State | Intended use | Data boundary | Authority | Required next evidence |
| --- | --- | --- | --- | --- | --- |
| Deterministic accounting/risk engine | IMPLEMENTED, synthetic/local | Validate and propose | Synthetic/local inputs | Policy authority within documented rules; no external action | Ongoing QA and jurisdiction review |
| Ollama/local OpenAI-compatible route | IMPLEMENTED advisory adapter | Local suggestion/explanation | Explicitly allowed local classifications | Advisory only | Capability, privacy, quality and resource evaluation |
| Codex workspace adviser | DECLARATION/OPERATOR INITIATED | Bounded development or advisory job | No raw client documents or credentials | Advisory only | Edge-worker envelope and signed-result design |
| OpenClaw/Hermes advisory job | DECLARATION/OPERATOR INITIATED | Specialist proposal/review packet | Exact evidence references, no connector credentials | Advisory only | Isolation, tool inventory and prompt-injection tests |
| OpenAI hosted adapter | NOT IMPLEMENTED/NOT APPROVED | Optional tenant-approved advice | NONE | None | DPA, no-training, region/retention, subprocessor and evaluation approval |
| Anthropic hosted adapter | NOT IMPLEMENTED/NOT APPROVED | Optional tenant-approved advice | NONE | None | Same provider-specific evidence |
| Gemini hosted adapter | NOT IMPLEMENTED/NOT APPROVED | Optional tenant-approved advice | NONE | None | Same provider-specific evidence |
| Supervised computer-use capture | NOT IMPLEMENTED/NOT APPROVED | Read-only evidence observation | NONE | No writes; human-supervised only | Origin, credential, injection and recording controls |

## Per-system record required before activation

Record owner, provider/model/version, intended purpose and excluded uses, data
classes, legal/privacy assessment, tenant consent, region/retention/training
terms, redaction, prompt/output retention, tools/capabilities, human oversight,
evaluation set and thresholds, bias/accuracy limits, cost budget, logging,
incident/kill switch, fallback behavior, deployment date and review trigger.

## Evaluation and monitoring

Use invented or lawfully approved evaluation data. Test prompt injection,
tenant/entity confusion, fabricated evidence, unsupported VAT/jurisdiction
claims, confidence calibration, refusal, redaction, budget exhaustion and
provider unavailability. A passing average cannot offset a safety-critical
failure. Outputs remain labelled suggestions with provenance and correction.

The European Commission describes transparency and human-oversight obligations
and a phased AI Act application timeline. The accountable legal reviewer must
classify each actual system and role against the rules in force at launch; this
inventory does not infer a risk category.

Source: [European Commission, AI Act](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai).

## Approval record

- Decision: PENDING
- Required reviewers: AI governance owner; privacy lead/DPO; security owner;
  qualified EU AI legal reviewer; accounting safety owner
- Approved systems/models and revision: PENDING
- AI-literacy and transparency evidence: PENDING
