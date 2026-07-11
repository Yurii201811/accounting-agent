# QA strategy

## Purpose and scope

Accounting Agent v1 has no HTTP API. The release surface is the exported Python API, CLI commands, connector and model contracts, SQLite stores, generated cockpit, packaged resources, and synthetic public preview. The canonical inventory and its user-story mapping live in `qa/traceability.json`; `tests/test_qa_traceability.py` fails when that inventory drifts.

The QA program protects accountants from silent automation errors. It verifies preparation and review workflows while preserving human authority over posting, approval, payment, communication, filing, and period locking.

## Test levels

1. **Deterministic unit and contract tests** cover public symbols, schemas, policy decisions, approvals, permits, evidence, connector declarations, and model-routing boundaries.
2. **Workflow and storage tests** cover synthetic intake, supplier invoices, reconciliation, close, checkpoint/resume/cancel, SQLite concurrency, rollback, migration, and integrity behavior.
3. **Generative tests** exercise money and FX invariants, Unicode identities, policy monotonicity, journal balance, and mutation invalidation across larger input spaces.
4. **Packaging tests** build wheel and source distributions, install them in clean environments, and run every supported CLI surface without checkout-relative dependencies.
5. **Browser and accessibility tests** exercise English and Swedish, Guided and Expert views, six roles, supported browsers, responsive widths, keyboard operation, runtime-request restrictions, and WCAG 2.2 A/AA axe rules.
6. **Security and privacy tests** deny sockets in inherited subprocesses, scan code and dependencies, detect secrets, validate synthetic resources, and probe hostile inputs without contacting external services.

## QA modes

- `python scripts/qa.py quick` is the developer loop: compile, offline unit/integration tests, and the v1 synthetic system check.
- `python scripts/qa.py full` adds branch coverage, property and process tests, static analysis, dependency and secret checks, and Playwright/axe.
- `python scripts/qa.py release` adds deterministic dual builds, wheel and sdist clean-install CLI checks, a deterministic preview rebuild, preview contract verification, deployment smoke evidence, and a revision/bundle-bound manual accessibility readiness gate.

The fixture/privacy gate can also be run directly:

```bash
python scripts/fixture_policy.py --json
python scripts/fixture_policy.py --preview-root .local/public-preview --json
```

It never follows symlinks and never needs access to Downloads, course PDFs, client folders, credentials, or external services.

## Release gates

A release candidate is not ready until all required checks pass on the same revision and no P0/P1 defect, unsafe mutation survivor, accessibility violation, secret, private-data leak, or unresolved safety ambiguity remains. Coverage must meet the repository thresholds, including stricter branch coverage for safety-critical modules. The wheel and source distribution must be independently installable and the public preview must match its local bundle hashes.

The manual VoiceOver result is recorded separately from automated axe output. If the manual pass has not been completed, release evidence must state `manual_accessibility: pending`; automation must not infer completion. Release mode exits `2` and records `release_ready: false` until the attestation matches the clean Git revision and exact five-file bundle digest.

## Failure protocol

For every failure:

1. Reproduce it with the smallest red regression test.
2. Classify its user story, safety class, severity, and affected release surface.
3. Apply the smallest fail-closed fix.
4. Run the focused test and the nearest safety-contract tests.
5. Run the complete release suite before shipping.

Accounting or compliance ambiguity is a stop condition for human judgment. The agent does not invent a tax treatment, lower a policy decision, or reinterpret an unsupported jurisdiction to make a test green.
