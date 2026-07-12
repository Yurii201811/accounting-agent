# Bounded offline read connectors

`accounting_agent.adapters.read_only` is the public-core boundary for provider
reads. It ships no HTTP client, socket code, OAuth exchange, environment lookup,
credential resolver, or default transport. Constructing a connector therefore
cannot contact Fortnox or NetSuite. A commercial or edge runtime must inject an
object satisfying `SemanticReadTransport`.

Every injected transport must expose a frozen `SemanticTransportIdentity` with
the exact provider, connection ID, revision, canonical connection hash and
tenant/source-company/environment/auth-reference binding. Connector
construction rejects a mismatch before any read, and the identity is checked
again before and after each transport call.

An injected transport receives a frozen `SemanticReadRequest` containing the
exact public `ConnectorConnection` ID, revision and canonical hash; its opaque
tenant/source-company/environment binding; one fixed resource, capability and
versioned operation ID; and bounded pagination integers. It receives no URL,
headers, token, arbitrary query text, or generic SQL. The concrete connector is
sealed after construction so its connection and transport cannot drift.

## Supported catalog

| Provider | Resource | Required capability | Versioned operation | Paging |
|---|---|---|---|---|
| Fortnox | `accounts` | `read_master_data` | `fortnox.accounts.v1` | `page:<positive-int>` |
| Fortnox | `suppliers` | `read_master_data` | `fortnox.suppliers.v1` | `page:<positive-int>` |
| Fortnox | `financial_years` | `read_master_data` | `fortnox.financial_years.v1` | `page:<positive-int>` |
| NetSuite | `subsidiaries` | `read_master_data` | `netsuite.suiteql.subsidiaries.v1` | `offset:<non-negative-int>` |
| NetSuite | `accounts` | `read_master_data` | `netsuite.suiteql.accounts.v1` | `offset:<non-negative-int>` |
| NetSuite | `vendors` | `read_master_data` | `netsuite.suiteql.vendors.v1` | `offset:<non-negative-int>` |
| NetSuite | `accounting_periods` | `read_period_locks` | `netsuite.suiteql.accounting_periods.v1` | `offset:<non-negative-int>` |

Fortnox `financial_years` is inventory/master data. It is not evidence of a
locked period. A future lock resource needs its own provider-semantic model and
tests. NetSuite has no transaction resource in this slice, so
`read_transactions` remains declared but unavailable. The NetSuite transport
must map the four operation IDs to reviewed fixed SuiteQL templates; callers
cannot submit query text.

NetSuite offsets must be divisible by the requested page size. Every
nonterminal page must be full, and the next offset advances by that page size.
This preserves Oracle's offset/limit contract and prevents cursor drift.

## Raw response boundary

`RawReadResponse` preserves immutable source bytes plus provider, operation,
canonical semantic-request hash, status, media type and retry evidence. The
request hash covers the connection ID/revision/hash, complete binding,
resource, capability, versioned operation and pagination parameters, so a
response cannot be replayed across a connection, scope, revision, resource or
cursor. `decode_raw_json_object` accepts only a matching HTTP-200 UTF-8 JSON
object within the size bound. It rejects duplicate keys, non-standard numeric
constants, non-finite or non-interoperable-range numbers, wrong
provider/operation/request, non-JSON media, invalid UTF-8 and oversized bodies.
The `ConnectorPage.raw_snapshot_hash` is calculated from the exact bytes before
mapping, and returned mappings, lists and nested values are recursively frozen
so the evidence cannot mutate while retaining that hash.

Fortnox pagination is derived only from `MetaInformation`. NetSuite pagination
is derived only from `offset`, `count`, `hasMore` and `totalResults`. Provider
navigation links are never followed and are removed from returned records.

## Fail-closed limits

- The connection must be `active`, provider-matching and grant the immutable
  resource capability before the transport is called.
- Tenant/source-company/environment binding and page bounds are checked before
  the transport is called.
- Transport identity and response request hashes prevent wrong-account wiring
  and cross-request replay; a transport identity change invalidates the read.
- Health reports `not_configured` with
  `offline_transport_health_unavailable`; it does not infer health or call the
  transport.
- The API contains no create, post, approve, send, pay, file, delete, settings,
  arbitrary-query or generic-write method.
- A returned page is raw read evidence only. It does not create a
  `SyncCheckpoint`, verify source reconciliation, or mark a `SyncRun` complete.
  Those outcomes require separately persisted counts, canonical hashes and
  source evidence under the production sync contracts.

Tests use complete synthetic provider envelopes and an in-memory injected
boundary. They never use real credentials or make a provider call.
