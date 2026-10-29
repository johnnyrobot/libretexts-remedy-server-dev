# Signed reviewer forwarding (LT-138)

Implements the Server portion of approved LT-1 corpus `lt1-wire-v1-r2`, Bridge
commit `a67d9d8b7efd9189f76885ecbd6394a9f3d92f54`, plus Chief's approval addendum
on LT-1 (2026-10-29). Final Conductor → Server → actual Bridge integration is
still required. This is not exposure or deployment approval.

Conductor sends the existing `X-API-Key` matching Server `APP_API_KEY`. Server
rejects duplicate headers before routing or body parsing and compares fixed
SHA-256 digests in constant time. The application key never goes to Bridge.
Configure TLS for off-host Conductor traffic in the separately reviewed bundle.

For enabled CXone integration the default `REMEDY_REVIEWER_REQUIRED=true` requires
an application key and `REMEDY_BRIDGE_SERVICE_KEY_FILE`. This file contains exactly
64 lowercase hex characters, optionally followed by one LF. The Server reads it
once at startup and sends only its value as `X-Remedy-Service-Key` on the Bridge
hop, including readiness, scans, previews, snapshots and status. File changes
require a coordinated restart; changing only one hop breaks authentication.
Synthetic keys are used in tests. Server holds no reviewer signing key.

The file must be mounted privately and readable by the application UID; never
put its value in image layers, command arguments, browser configuration, logs,
request bodies or source. Configure the same file-backed service credential on
Bridge. Provisioning real credentials, container mounts and rotation remain part
of the reviewed deployment bundle and Johnny's live rollout decision.

An explicit `REMEDY_REVIEWER_REQUIRED=false` is supported only in development
with a loopback Bridge URL. Production refuses this downgrade. This mode permits
legacy token workflows and does not prove signed authorization. Required mode
never retries or falls back to legacy after any error.

Apply/restore accept exactly one top-level JSON `reviewer_assertion` in canonical
compact transport form. Duplicate JSON members (including escaped duplicates),
camelCase/nested aliases, header/query/cookie carriers and Authorization overloads
are rejected with fixed diagnostics. Server validates transport encoding, forwards
the compact string unchanged, and neither reads signed claims nor changes reviewer
identity. Bridge owns signature, time, key, binding, target and replay checks.
Preview binding and integer `review_expires_at` remain authoritative Bridge data.

All received Bridge HTTP statuses and JSON bodies pass through, including 502
`unknown_write`, `applied:null`, pending/hold, confirmed no-change/preserve and
stale-target/invalidate. Server does not flatten these into generic errors or
reinterpret a false/null applied flag. A missing/non-JSON response or transport
failure on a mutation is conservatively unknown, with no retry. Resolve using
Conductor's stored issuer/jti mapping and readonly
`POST /v1/cxone/page/operation-status` with exactly `{issuer,jti}`; a 404 is not
proof of no write and never authorizes resubmission. No new assertion is generated.

`GET /v1/cxone/health` authenticates both hops and requests Bridge **`/readyz`**.
It returns Bridge's HTTP 200/503, state and boolean capabilities
`scan`, `preview`, `mutate`, `operation_status`, with `enabled:true`. Malformed,
inconsistent or unreachable readiness fails with 503. A profile must check each
capability it needs: ready for scans alone does not imply mutation readiness.
Public `/healthz` reports process liveness only.

Tests run actual FastAPI ASGI requests through HTTP to a local synthetic Bridge,
with public shared vectors and fake service keys. Python independently checks raw
Ed25519 validity labels on all 43 frozen vectors; this is primitive interoperability,
not product Bridge verification. No test here proves ledger durability, signature
policy, real CXone behavior, assembled topology or exposure safety. The corpus is
byte-for-byte from the approved immutable proposal, SHA-256
`fbdb4e1cb6a66ed47f2de5393a23e84a37b509ef2bf23aa001a36452c5a50e4b`.
