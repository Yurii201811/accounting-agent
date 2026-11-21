# Accounting Agent v1 QA

This folder is the release-facing reference for Accounting Agent v1 quality assurance.

- [QA strategy](strategy.md) explains scope, test levels, and failure handling.
- [Personas and user stories](personas-and-user-stories.md) summarizes the machine-checked catalog in `qa/traceability.json`.
- [Accessibility release checklist](accessibility-checklist.md) separates automated evidence from the required manual macOS VoiceOver pass.
- [Release evidence](release-evidence.md) defines the local evidence layout and sanitization rules.
- [Safety and compliance boundaries](safety-and-compliance-boundaries.md) states what the product and the test suite must never claim or do.

Run QA with:

```bash
uv sync --frozen --group qa
npm ci
npx playwright install chromium firefox webkit
uv run --frozen --group qa python scripts/qa.py quick
uv run --frozen --group qa python scripts/qa.py full
ACCOUNTING_AGENT_PREVIEW_URL=https://your-preview.vercel.app \
uv run --frozen --group qa python scripts/qa.py release
```

All QA data is synthetic. A green run is evidence about the tested revision, not legal, tax, audit, or jurisdictional certification. Release mode rebuilds the deterministic preview and remains exit `2`/`release_ready: false` until the exact revision and bundle have a completed manual VoiceOver attestation.

Release mode requires `ACCOUNTING_AGENT_PREVIEW_URL` to identify the already-deployed deterministic Vercel preview and always verifies the canonical `.local/accounting-agent-v1-preview-release` bundle. To finalize a manual pass in a fresh run, repeat the URL and provide the prior canonical evidence file with `--manual-accessibility-evidence .local/qa/runs/<prior-run-id>/accessibility/manual-voiceover.md`. Evidence and summary paths outside `.local/qa/runs/`, or paths containing symlinks, are rejected.
