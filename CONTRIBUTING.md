# Contributing

Thank you for helping improve Accounting Agent. Contributions to the public
core are reviewed for correctness, compatibility, provenance, privacy, and the
accounting safety ceiling before they are merged.

## Before you start

- Read [GOVERNANCE.md](GOVERNANCE.md), [SECURITY.md](SECURITY.md), and
  [docs/provenance-and-private-data.md](docs/provenance-and-private-data.md).
- Use only invented, deterministic synthetic data. Never submit real client
  data, credentials, bank details, private course material, or copied client or
  course documents.
- Do not add live ERP, email, payment, tax, filing, hosted-model, or production
  infrastructure calls to this repository.
- Discuss compatibility changes before implementation. Public v1 imports and
  all nine CLI commands remain supported through 1.x.

## Development and checks

Create changes in a focused branch, preserve unrelated work, and run the
smallest relevant tests first. The standard local checks are:

```bash
./.venv/bin/python -m unittest
./.venv/bin/python scripts/qa.py quick
```

Use the locked QA environment described in the README when the repository
virtual environment is unavailable. A pull request must explain its safety
impact, test evidence, and any check that could not run.

## Developer Certificate of Origin

Every contribution uses the repository's [Developer Certificate of
Origin](DCO.md). Every commit must include a certificate line in this form:

```text
Signed-off-by: Your Name <your-address@example.com>
```

Create it with `git commit -s`. The sign-off certifies that you have the right
to submit the contribution; it is not a substitute for authorship or
third-party-license review. The project enforces this as repository policy and
does not add an unpinned sign-off action.

## Pull requests

Pull requests should be reviewable, signed off, covered by deterministic tests,
and free of generated local evidence. Maintainers may require accounting,
security, accessibility, privacy, or compatibility review before merge. A
merged change is not by itself a publication or production approval.

Report suspected vulnerabilities through the private process in
[SECURITY.md](SECURITY.md), not in a public issue.
