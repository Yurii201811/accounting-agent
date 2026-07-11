# Release process

Accounting Agent releases are evidence-bound. Publication is fail closed and
does not imply deployment or production approval.

## State labels

- `local`: checks ran in a named worktree at an exact revision.
- `artifact`: wheel and source distribution were reproducibly built and
  inspected.
- `remote`: the exact revision passed required remote CI.
- `deployed`: a named preview's bytes match a reviewed artifact.
- `production`: separately authorized operational use with all external
  prerequisites. No current public-core release has this state.

Never infer a later state from an earlier one.

## Prepare the revision

1. Confirm a clean worktree and preserve the v1 import, 142-symbol, and
   nine-command CLI contracts.
2. Confirm every commit has the DCO `Signed-off-by:` trailer.
3. Review the complete Git history and current tree for secrets, real client
   data, private course material, local paths, incompatible licenses, and
   uncertain provenance.
4. Update CHANGELOG.md and directly affected contracts.
5. Run focused tests, repository and CI contract tests, package checks, then
   the documented quick/full/release QA modes as applicable.

All test inputs and evidence must be synthetic. Do not call a live provider,
mailbox, ERP, payment, filing, hosted-model, or production service to complete a
release gate.

## Publication gates

External publication remains blocked until the exact candidate revision has:

- passing required remote CI, with the three reviewed workflows unchanged or a
  separately reviewed workflow-policy change;
- reproducible package and source-distribution evidence;
- a completed manual VoiceOver assessment bound to the exact preview bundle;
- independent legal review and accounting review;
- a complete history and privacy review, including provenance and secrets; and
- maintainer approval recorded for that evidence set.

A local green run, code-owner review, merge, automated axe pass, or pending
external review cannot satisfy these gates. Missing evidence remains pending;
failed or mismatched evidence blocks publication.

## After publication

Record the tag, revision, artifact hashes, remote CI result, reviewer decisions,
and known limitations. Treat preview deployment, private-cloud deployment, and
production authorization as separate approvals. Follow [SECURITY.md](../SECURITY.md)
for vulnerabilities and update the changelog for any corrective release.
