# Provenance and private-data policy

This repository is public-source material. Every committed fixture, example,
document, image, and generated artifact must have a provenance basis that is
safe to publish and redistribute under its stated license.

## Allowed material

- Invented, deterministic synthetic data created for this repository.
- Original project documentation and code contributed under the DCO.
- Third-party material with verified redistribution rights, a compatible
  license, necessary attribution, and maintainer approval.

Record the origin, license, and transformation for any third-party asset. An
educational or publicly reachable source is not automatically redistributable.
When evidence is missing or ambiguous, fail closed and replace the material
with an independently invented fixture.

## Prohibited material

Never commit, paste, transcribe, summarize into a near-copy, or package:

- real client data, client identifiers, accounting documents, mailbox content,
  bank details, credentials, tokens, or production exports;
- private course material, paid course files, instructor content, answer keys,
  screenshots, distinctive examples, or derived exercises;
- files from a personal downloads folder, user-home path, cloud drive, private
  workspace, or local evidence directory; or
- third-party content whose license or contributor authority is unknown.

Private course references may be used outside source control only for an
authorized, human-led gap analysis. No text, media, file name, local path,
distinctive structure, or derived client/course example may cross into the
repository. The resulting public work must be independently written and use
synthetic data. Attribution alone does not cure a privacy, confidentiality, or
copyright restriction.

## Review and enforcement

The repository privacy scanner covers fixtures, previews, publishable docs,
and Python source. Detector implementations are narrowly exempt so they can
recognize prohibited markers; that exemption does not permit product or
documentation content to contain them. Findings block release.

Reviewers must check both the current tree and Git history before external
publication. Removal in a later commit does not remove private data from
history. If prohibited material is discovered, stop sharing, preserve only the
minimum private incident evidence, follow [SECURITY.md](../SECURITY.md) when
appropriate, and complete a history/privacy review before publication resumes.
