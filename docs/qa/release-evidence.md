# Release evidence

## Local layout

Each QA run writes sanitized evidence beneath `.local/qa/runs/<run-id>/`. The run identifier is UTC and the summary identifies the exact Git revision.

```text
.local/qa/runs/<run-id>/
├── summary.json
├── logs/
│   └── <gate>.log
├── junit/
│   ├── python.xml
│   └── playwright.xml
├── coverage/
│   ├── coverage.json
│   ├── coverage.xml
│   └── html/
├── playwright/
│   ├── html/
│   └── results/
├── accessibility/
│   └── manual-voiceover.md
├── mutation/
│   └── summary.json
├── package/
│   ├── accounting_agent-1.0.0-py3-none-any.whl
│   ├── accounting_agent-1.0.0.tar.gz
│   └── package-summary.json
└── security/
    ├── bandit.json
    ├── evidence-privacy.json
    ├── fixture-policy.json
    ├── gitleaks.json
    └── pip-audit.json
```

Some folders appear only in `full` or `release` mode. Missing required evidence is a failed or pending gate, never an implicit pass.

The mutation report retains aggregate results for every generated mutant and
enforces the reviewed authority-weakening targets in
`qa/mutation-safety-targets.json`. Every curated target must be killed. Other
survivors remain visible for triage and are not silently described as passing;
equivalent, diagnostic-text, or strictly fail-closed mutations are outside the
release authority gate.

## Summary requirements

`summary.json` records the schema version, mode, Git revision, dirty-worktree state, UTC generation time, automated result, step names, exit codes, durations, and relative log paths. Release summaries also record `manual_accessibility` as `passed`, `failed`, or `pending`, plus `release_ready`. A green automated `passed` value is not a final release claim while `release_ready` is false. A dirty worktree always keeps `release_ready` false because its evidence cannot be bound to the recorded commit. Package and deployment evidence additionally records artifact hashes.

`preview/deployment-smoke.json` records the normalized public `*.vercel.app` HTTPS target and the local and remote SHA-256 for each of the exact five files. Localhost, private origins, custom ports or paths, redirects, missing files, oversized responses, and unequal hashes fail before deployment equality can be claimed.

Release mode overrides any caller-provided bundle path with the canonical deterministic `.local/accounting-agent-v1-preview-release` directory before deployment smoke, so remote equality and manual accessibility bind the same bytes.

The `release` command exits `2` when every automated step passes but the manual, bundle-bound accessibility gate is pending or failed. Exit `0` is reserved for an evidence-complete release; ordinary automated gate failures exit `1`. After completing the first run's template, pass it to a fresh run with `--manual-accessibility-evidence .local/qa/runs/<prior-run-id>/accessibility/manual-voiceover.md`. The runner copies only recognized metadata into the new evidence directory.

When manual evidence is absent, the runner creates `accessibility/manual-voiceover.md` with `status: pending`. A passing attestation must record the tester, UTC time, macOS version, browser, VoiceOver version, exact Git revision, and the runner-computed SHA-256 over the exact five-file preview bundle. The digest binds sorted file names, lengths, and contents. Missing, duplicate, malformed, revision-mismatched, or bundle-mismatched fields fail closed rather than being inferred from axe results.

CLI-provided summaries must use `.local/qa/runs/<run-id>/summary.json`; manual inputs must use the canonical accessibility path inside another QA run. Existing symlink components, non-regular files, and paths outside that root are rejected. The runner records both the starting and ending Git revision and requires a clean source at both endpoints with no revision drift for `release_ready`. Release QA must run in its dedicated worktree without concurrent edits; endpoint sampling is not an immutable filesystem snapshot.

## Privacy and retention

- `.local/` is ignored and must never be committed. A clean CI runner may
  upload only the sanitized `.local/qa/runs/<run-id>/` evidence directory;
  accounting workflow artifacts and every other `.local` path are forbidden.
- Logs replace the repository and home-directory prefixes with safe placeholders.
- The final evidence-privacy gate scrubs text reports, inspects packaged archives
  and binary artifacts for the current repository/home/host identity, rejects
  symlinks, and fails if any machine-local path or hostname remains.
- Evidence must not contain environment dumps, credentials, tokens, passwords, bank secrets, real client identifiers, source documents, private course material, or local absolute paths.
- Security reports use redaction where the tool supports it.
- Tests use deterministic synthetic data and inherited socket denial.
- Share only a deliberately sanitized summary or a public-preview hash manifest after human review.

Before release, run the fixture policy against both repository resources and the generated preview:

```bash
python scripts/fixture_policy.py --preview-root <generated-preview> --json
```

Any finding blocks release until the resource is removed, replaced with invented data, or—only for an independently verified redistributable educational asset—added by exact path to the educational allowlist. The scanner still applies path, secret, extension, size, and symlink checks to allowlisted assets.
