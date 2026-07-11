# Governance

Accounting Agent is maintained as an Apache-2.0 open-source core with an
explicit safety ceiling and a separately governed private-cloud program.

## Roles

- Contributors propose issues, documentation, code, tests, and reviews under
  the DCO.
- Reviewers provide evidence-based feedback but do not gain merge or release
  authority from review alone.
- Maintainers triage work, protect compatibility and safety boundaries, merge
  accepted changes, and manage releases. The initial code owner is
  `@Yurii201811`.

Maintainer access is granted or removed by existing maintainers based on a
record of sound contributions, respectful collaboration, security judgment,
and stewardship of the accounting safety boundary.

## Decisions

Routine decisions seek consensus in the relevant issue or pull request. When
consensus is unavailable, a maintainer records the decision and its rationale.
Changes to public API compatibility, licensing, governance, provenance policy,
the safety ceiling, or release gates require explicit maintainer approval and
the relevant specialist review.

CODEOWNERS requests review; it does not grant accounting, legal, security, or
production authority. Conflicts of interest must be disclosed, and an affected
maintainer should recuse from the final decision when practical.

## Repository boundary

This repository contains the public core: deterministic domain logic,
synthetic examples, dry-run or read-only contracts, documentation, and local QA.
Hosted multitenant services, identity, production tenant storage, commercial
operations, production infrastructure, and provider credentials belong outside
the public core. See [docs/production_program.md](docs/production_program.md).

## Releases and policy changes

A maintainer may tag or publish only after every gate in
[docs/release-process.md](docs/release-process.md) has evidence for the exact
revision. A merge, local green run, or code-owner approval is not release
approval. Governance changes use the same pull-request, DCO, review, and
history/privacy requirements as code changes.
