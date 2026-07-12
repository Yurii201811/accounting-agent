# Bounded local Edge Worker foundation

The public Edge Worker foundation runs one operator-initiated, synthetic advisory
job against either Ollama or an unauthenticated OpenAI-compatible endpoint on the
same machine. It is a Python library surface, not a daemon, CLI command, cloud
poller, connector, computer-use agent, or production service.

## Exact boundary

`EdgeAdvisoryJobV1` binds the tenant, client, legal entity, case, request, model
provider, model identifier, purpose, public-synthetic classification, prompt
hash, evidence hashes, byte budgets, and UTC deadline into one canonical digest.
The raw prompt stays in memory and is excluded from the wire representation.

The only capability is `model_advisory`. The job and result tool inventories are
hard-coded empty. There is no parameter or import surface for ERP credentials,
connectors, MCP tools, computer use, subprocesses, approvals, posting, sending,
payments, filing, deletion, settings changes, or any external write.

Both model transports:

- require an explicit per-call opt-in;
- accept only literal loopback HTTP base URLs and no embedded credentials;
- disable redirects and environment proxies;
- use fixed API paths, bounded prompts, responses, timeouts, and strict JSON;
- require the completed response to name the requested model; and
- return advice that still requires deterministic validation and human review.

## Signed result

`EdgeAdvisoryResultV1` repeats every scope and evidence binding, records the
canonical structured payload and hashes, and permanently sets approval and
execution authority to false. `LocalEd25519Signer` is available through the
optional `accounting-agent[edge]` dependency. A caller injects the 32-byte key in
memory; this package does not load a key, credential, environment variable, or
file. The corresponding verifier contains only the public key.

Verification checks the Ed25519 signature and the exact expected job before a
process-local replay guard consumes it. That replay guard is useful for local
synthetic execution only. It is not durable, distributed, mTLS-backed, or a
substitute for the future cloud idempotency and device-revocation store.

## Explicitly not implemented

- real-client or confidential accounting input;
- cloud polling, inbound listening, mTLS, or device enrollment;
- hosted OpenAI, Anthropic, Gemini, Codex, OpenClaw, or Hermes invocation;
- credentials of any kind in model prompts or result payloads;
- connectors, restricted Fortnox MCP, ERP reads or writes, and computer use;
- autonomous deterministic acceptance, approval, or accounting execution; and
- production signing-key custody or non-repudiation assurance.

Production activation still requires a clean threat-model review binding,
durable replay protection, authenticated device lifecycle, operational testing,
and every first-real-client-byte gate. This foundation makes no production or
compliance claim.
