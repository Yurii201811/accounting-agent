# Production contract reference

The contracts in `accounting_agent.contracts` are dependency-free public-core
types for crossing future process, API, database and provider boundaries. They
are immutable evidence and command envelopes. They do not authenticate a user,
call a provider, persist themselves, or grant accounting authority.

## Contract families

- `scope.py` binds authenticated tenant, client, legal entity, actor, roles,
  authentication strength and request identity.
- `archive.py` binds document provenance, quarantine, retention, legal holds,
  processing lineage and signatures.
- `canonical.py` supplies typed suppliers, invoices, journals, balances,
  periods and dimensions with integer money and exact sync provenance.
- `sync.py` supplies read-only connection, checkpoint, run and source
  reconciliation records. A completed run requires ordered cursor chains and
  exact count/hash evidence for every requested resource.
- `commands.py` supplies MFA-backed approval decisions, hash-only
  supplier-invoice draft commands and provider-observation receipts. Only an
  exact read-back of an unbooked reversible draft avoids a freeze.
- `model.py` supplies one-provider tenant routing policy with classification,
  region, retention, redaction, authenticated-consent evidence, evaluation and
  budget controls. Model authority and silent fallback are always false.

The original v1 types remain supported. New production contracts are additive;
they do not alias weaker legacy proposal, connector, approval or routing types.

## Wire and hashing rules

Every top-level wire object has `schema_version: "v1"`, rejects missing,
unknown and duplicate fields, and uses canonical UTC timestamps ending in `Z`.
Identifiers are Unicode-normalized opaque identifiers; digests are lowercase
SHA-256 hex. Money is an integer number of minor units. Integers are limited to
the interoperable JSON range `-(2^53 - 1)` through `2^53 - 1`; this prevents a
JavaScript consumer from rounding a value before hashing. Floats, NaN and
infinity are never accepted for accounting or canonical hashes.

`accounting-agent-restricted-json-sha256-v1` is:

1. Validate recursively that values contain only JSON objects with string keys,
   arrays, strings without Unicode control/format characters, exact integers,
   booleans and null.
2. Serialize UTF-8 JSON with keys sorted, no ASCII escaping and separators
   `,` and `:` with no added whitespace.
3. Calculate lowercase SHA-256 over those UTF-8 bytes.

Golden cross-language vectors live in
`accounting_agent/contracts/production-contract-vectors.json` and ship with the
wheel. A cloud, TypeScript, Java or other consumer must pass those vectors
before its hashes are trusted.

## Successor and authority rules

Revision successors advance exactly once and preserve tenant/provider/source
identity. They may resolve unknown facts or narrow permissions, budgets and
retention. They cannot reopen locked periods, regress terminal accounting
states, reactivate an inactive supplier/dimension, add model classifications,
widen connector capability, replace prior evidence, or reinterpret an
ambiguous provider result as success. Changing model consent requires a later
timestamp and a new authenticated-consent evidence hash.

A parsed `ApprovalDecisionCommand` is still only a command. The future API must
derive scope from authenticated membership, apply optimistic concurrency and
idempotency, and persist the result in trusted storage. Likewise, an
`ExternalDraftCommand` must be reloaded and verified by an isolated gateway;
its construction never authorizes a network call. Final posting, approval,
sending, payment, filing, deletion, settings changes and supplier-bank-detail
changes remain structurally unavailable.

The bounded connectors in `accounting_agent.adapters.read_only` can produce a
strict raw `ConnectorPage` through an injected transport, but they do not
construct checkpoints, assert source counts/hashes, or complete a `SyncRun`.
Those success claims remain unsupported until an orchestrator persists and
independently verifies the production sync evidence.
