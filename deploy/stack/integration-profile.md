# Full integration candidate and optional review rollout

This package runs the actual compiled Conductor with Server, exact ADAPT Scanner,
Bridge, its rendered-page scanner and authenticated Mongo. It is one maintained
full implementation, including signed apply/restore/status/recovery. LibreTexts
chooses rollout timing; review-only is an optional mode of the same package.
Start at the [stack guide](README.md) and [Server README](../../README.md).

**Production automatic writes remain held, with no bypass toggle.** LibreTexts'
integration/deployment team owns vendor-supported revision-atomic preconditions,
authorized evidence, adapter/policy/target validation and rollout. Keys alone
never enable writes. Neither these instructions nor a synthetic Linux rehearsal
authorize a live deployment, credential provisioning or contact with a real
library/provider. `bundle.json` keeps `deploymentReady:false` and
`productionWritesEnabled:false` pending exact proof, normal gates and Chief
acceptance.

## Exact compatible inputs

Use [bundle.json](bundle.json), [conductor-candidates.json](conductor-candidates.json)
and their matching immutable Linux receipts together. The authoritative original
32-patch index is from Conductor patch source
`dd152c5eca8e48609bbf7df9a9c8c63cf7b48fd2`, SHA-256
`99d70fe71fdf956bc60e34ca55b262cc39747cd5fd30bd386ec7518d3ba58da8`.
Choose exactly one target; never combine its patches, archive or manifest with
the other target or substitute the older 24-patch delivery.

| Target | Preserved upstream base | Original compressed archive SHA-256 |
|---|---|---|
| Release 2.156.2 | `352a657ec6de7b317a70ad3f8f744bc6d5054d9d` | `363b016ed5177187159afbf3db13fab2bf124e78e0561b2659f5b59e09d08781` |
| Staging | `67301b35c3784ed73ba1a65011ef5a1d689abca1` | `fd65b40b251b9e0326e361fbe9422939702a796ce055d08fe885109fe29f99f9` |

The original artifacts expire November 12, 2026 (exact UTC times and artifact
URLs are in the index). Verify availability and provenance before expiry and
retain the exact accepted bytes under the release owner's retention policy.
If unavailable, obtain a newly executed and reviewed compatible delivery;
silently rebuilding a consumer is not equivalent. Server/Bridge/renderer
candidate archives have their own producing-run retention and hashes.

Bridge and its separately archived renderer use source
`f39566e0fa6413ed17e7a5c2a11fefc540ed5233`, with `cxone-review-v1` and
`cxone-terminal-v1`. Scanner is pulled at the literal registry manifest
`sha256:00ab363669ccc7ae50fe7fc79286508af5923d3326d397f87cff91ee76e379a6`;
Mongo is `mongo:7.0.14@sha256:0032d2ca20db5fa34926f196c8a43b74e34ed239a7f2453ff1505b6f12ba8ea6`.
Use the reviewed full Server runtime, never runtime-slim for HTML/Scanner.

Verify original artifact ZIP, archive, source/base/lock/profile and filesystem
layer hashes, then inspect the imported runtime configuration and immutable
loaded image ID. Original config and OCI manifest digests can differ from Docker's
loaded ID; retain the exact import verifier's binding rather than assuming
equivalence. Supply only those **verified loaded immutable IDs** through
`REMEDY_SERVER_IMAGE`, `REMEDY_BRIDGE_IMAGE`, `REMEDY_RENDERER_IMAGE` and
`REMEDY_CONDUCTOR_IMAGE`. Compose substitution checks presence; it does not verify
identity or provenance. No `latest`, mutable tag, `build:` or rebuilt consumer is
a deployment input.

## Retaining and checking the handoff

The candidate workflow's final `remedy-stack-handoff-<source commit>` artifact is
created only after all nine acceptance receipts match. It contains `package.tar`,
the identical internal/external `manifest.json`, `checksums.sha256` and the
external `seal-receipt.json`. The TAR contains the exact tracked source archive,
three downloaded/imported owned OCI archives, both original Conductor ZIPs and
saved archives, allowlisted receipts and metadata. Scanner and Mongo retain
their literal registry digest references; a registry pull is still required.
Runtime credentials, private TLS/signing keys, raw cold-state archives and live
databases are never package inputs. A refused seal is incomplete evidence, not
a distributable accepted package.

Obtain the handoff only from the exact reviewed source/run and independently
verify its GitHub artifact ZIP digest. Compare `package.tar` with the
`packageTARSHA256` in that run's seal receipt, then compare the external manifest
and checksums file against their recorded digests. Extract only the verified TAR
into a new private directory and run `sha256sum --check checksums.sha256` there;
compare its internal manifest bytes with the external manifest before using any
input. SHA-256 proves integrity, not a signature or independent authenticity.
The trusted source/run is a separate prerequisite. Re-run the package's import
verification against the actual loaded images; archive checks do not replace
runtime identity, sandbox, host or authenticated capability checks.

New workflow artifacts have 30-day retention. The original Conductor inputs have
the separate expiry recorded above; a completed sealed copy preserves their
original bytes and provenance beyond that download window. Retain the **whole**
package and its trusted receipt before either download expires. Missing bytes
require a newly verified delivery, never substitution. Even a completed seal
keeps `deploymentReady`, `productionWritesEnabled`, `liveProvidersVerified`,
`productionSSOVerified` and `releaseOwnerAcceptance` false. LibreTexts still owns
target-host/provider/SSO acceptance and rollout, and vendor conditional-write
validation remains an independent hold.

## Host, filesystems and private transport

The candidate target is Linux amd64, rootful Docker Engine with Compose v2,
cgroup v2 and host Python 3.11+. Preflight must establish pidfd/subreaper support,
unprivileged user/PID namespaces and the reviewed Chromium/seccomp behavior in
the exact images. macOS/Docker Desktop, arm64, Podman, rootless/userns-remap,
network filesystems and unverified storage/network providers are unsupported by
this package. Refusal is a stop condition; do not change host security, add
capabilities or disable browser sandbox/TLS checks.

All paths must already exist, be absolute/canonical, and match the inspected
mount inventory. Every bind uses `create_host_path:false`. Pre-provision private
local ext4/XFS bounded filesystems; the current checks require the underlying
filesystem capacity to fit the budget and do not certify project/directory quota
enforcement on a larger shared filesystem. Record usable/free capacity as well
as the selected bounds. Keep credentials, TLS, independent epoch and fence
outside all three data stores and backup archives.

| Compose input | Container destination | Owner / maximum selected capacity |
|---|---|---|
| `REMEDY_STATE_ROOT` | Server `/app/state` | UID/GID 999, mode 0700, 1 GiB |
| `REMEDY_BRIDGE_STATE_ROOT` (history) | Bridge `/ledger` | UID/GID 1000, mode 0700, 512 MiB |
| `REMEDY_MONGO_STATE_ROOT` | Mongo `/data/db` | UID/GID 999, mode 0700, 1 GiB |
| `REMEDY_FENCE_ROOT` (history) | Bridge `/fence` | UID/GID 1000, mode 0700, independent 32 MiB |

Mongo runs `mongod --auth --bind_ip_all --wiredTigerCacheSizeGB 0.25` as UID 999,
with 1 GiB RAM, private networking and no host port. The deployment team must
provision its authenticated application database and least-privilege account
before starting this package. The Conductor URI file names that existing
database and `authSource`. No anonymous/default-password bootstrap or automatic
database initialization is supplied. `/data/configdb` is a bounded 16 MiB tmpfs
masking the image's unused volume; it is not a second persistent database.

The dedicated `remedy` network is internal/default-deny, with no published ports.
Bridge uses `network_mode:service:remedy-server` and listens only on
`127.0.0.1:5175`. Server reaches it through that loopback address with the existing
private-hop service key. There is no public Bridge staff panel. The rendered
scanner is private on 5180 with a Bearer credential. Conductor listens privately
on 5000; production staff ingress, origins, TLS and SSO require the deployment
team's separately reviewed configuration. Do not publish a port or tunnel as an
ad hoc substitute.

Conductor and Scanner use **`https://remedy-server:8000`**. The Server overlay uses
Uvicorn's existing `--ssl-certfile /run/tls/cert.pem --ssl-keyfile /run/tls/key.pem`.
Pre-provision a valid leaf certificate with DNS SAN `remedy-server`, its protected
private key and the reviewed public CA chain. Under `REMEDY_TLS_ROOT`, provide
`server/cert.pem`, `server/key.pem`, `server/ca.pem` and per-role public CA copies
`scanner/ca.pem`, `bridge/ca.pem`, `conductor/ca.pem`. Each role directory is 0700,
owned by its actual UID, with regular nonsymlink files 0400/0600. Server UID 999
alone receives the TLS private key. Node uses `/run/tls/ca.pem` via
`NODE_EXTRA_CA_CERTS`; curl health checks use `--cacert`. Never mount a CA private
key or disable certificate/hostname verification. This package generates no PKI.

The isolated Linux proof fakes only external ADAPT/CXone/provider systems and
blocks live egress. Those fixtures are absent from the public overlays. The
reviewed producer policy still permits only `dev.libretexts.org` and owner scope
`Sandboxes/johnnyphung`; this guide grants no contact with that live host. Actual
deployment needs reviewed restricted egress/DNS/TLS/target acceptance; internal
isolation must not be silently removed to obtain green checks.

## Private credential FILE matrix

`secret-env.mjs` reads the listed private files and starts the unchanged product
command. Values are printable ASCII with at most one final LF, no embedded
newline/NUL, and at most 16 KiB. Files must be regular nonsymlinks, mode 0400/0600,
owned by the workload UID; role directories are 0700. Direct secret environment
values are rejected. Never put credentials in Compose interpolation files,
arguments, logs, image layers, repository files or browser configuration.

| Role / file under `REMEDY_SECRET_ROOT` | File setting | Existing product credential |
|---|---|---|
| Server `server/app` | `APP_API_KEY_FILE` | `APP_API_KEY` |
| Server `server/ollama` | `OLLAMA_API_KEY_FILE` | `OLLAMA_API_KEY` |
| Scanner `scanner/api` | `SCANNER_API_KEY_FILE` | `SCANNER_API_KEY` |
| Scanner `scanner/adapt` | `ADAPT_TOKEN_FILE` | `ADAPT_TOKEN` |
| Scanner `scanner/remedy` | `REMEDY_API_KEY_FILE` | `REMEDY_API_KEY` |
| Bridge `bridge/key` | `SERVER_KEY_FILE` | `SERVER_KEY` |
| Bridge `bridge/secret` | `SERVER_SECRET_FILE` | `SERVER_SECRET` |
| Bridge `bridge/user` | `SERVER_USER_FILE` | `SERVER_USER` |
| Server `server/service`, Bridge `bridge/service` | `REMEDY_BRIDGE_SERVICE_KEY_FILE` | Existing file-backed private-hop key |
| Bridge `bridge/renderer` | `RENDER_SCANNER_TOKEN_FILE` | `RENDER_SCANNER_TOKEN` |
| Renderer `renderer/token` | `RENDER_SCANNER_TOKEN_FILE` | `RENDER_SCANNER_TOKEN` |
| Conductor `conductor/session` | `SECRETKEY_FILE` | `SECRETKEY` |
| Conductor `conductor/mongo` | `MONGOOSEURI_FILE` | `MONGOOSEURI` |
| Conductor `conductor/remedy` | `REMEDY_API_KEY_FILE` | `REMEDY_API_KEY` |
| Conductor `conductor/openai` | `OPENAI_API_KEY_FILE` | `OPENAI_API_KEY` |
| Conductor `conductor/stripe` | `STRIPE_SECRET_KEY_FILE` | `STRIPE_SECRET_KEY` |
| Conductor `conductor/mailgun` | `MAILGUN_API_KEY_FILE` | `MAILGUN_API_KEY` |

Server is UID 999; Bridge and Conductor are UID 1000; renderer is UID 1001.
Scanner retains the exact image's `pwuser` UID: inspect and record it rather than
assuming it matches another image. Copies of Server's API key on Scanner and
Conductor must match byte-for-byte while remaining individually UID-owned.
Server/Bridge service files likewise match and contain exactly 64 lowercase hex
characters, optionally one LF. Bridge/renderer bearer copies also match, with
separate ownership. No signing private key belongs on Server, Bridge or renderer.

Current original Conductor/Server startup requires the provider files listed
above, even when a deployment does not exercise those optional provider features.
That requirement does not verify provider authorization/reachability or approve
paid activity. CI uses synthetic unused values; those are not production setup.

## Renderer public trust seed

Supply `REMEDY_RENDERER_SECCOMP_FILE` as the absolute reviewed
`renderer-seccomp-amd64.json` and verify [renderer-profile-source.json](renderer-profile-source.json).
The single recorded chroot correction preserves sandboxing and kernel denial in
the initial unprivileged namespace. Never use extra capabilities, unconfined
seccomp, ignored certificate errors or sandbox-disabling flags.

`REMEDY_NSS_SEED_ROOT` is a read-only **fresh CA-only** public seed containing
`cert9.db` and `key4.db`, readable only by renderer UID 1001. Deployment owners
must verify it contains only approved public trust certificates and no private
keys, client identities or copied user profile. Use the compatible Ubuntu 24.04
NSS toolchain and retain its version/hash with the exact image's runtime NSS
package. Actual Linux run `41029837474` on Ubuntu 24.04.5 recorded
`libnss3-tools=2:3.98-1ubuntu0.3`, tool SHA-256
`505b13e3087e1abcabec3f1485e0e76b81322667dcae25758341b46bcfc5b62d`, and
renderer `libnss3=2:3.98-1ubuntu0.2` in its `full-result.json` receipt. That is a
verified compatibility pair, not permission to replace runtime libraries or
assume an arbitrary newer tool is compatible. A host NSS 3.117 database failed
against immutable runtime NSS 3.98 and is unsupported.

The single [browser-home.sh](browser-home.sh) initializer requires nonroot
`HOME=/tmp/renderer-home`, umask 077, and fresh current and legacy NSS directories.
It copies **only** `cert9.db`/`key4.db` into `$HOME/.local/share/pki/nssdb` and
`$HOME/.pki/nssdb`, then execs the unchanged command. It never imports host module
configuration or offers diagnostic variants. HOME lives inside the renderer's
512 MiB tmpfs; shm is 1 GiB and stop grace 30 seconds. A failed initializer is a
stop condition, not permission to reuse arbitrary host browser state.

## Overlay and mode selection

Prepare the matching nonsecret `env/*.env` files from their `.example` templates
without overwriting existing configuration. Replace placeholder origin/provider
metadata with authorized values. `NODE_ENV=production` applies throughout.
Conductor keeps `REMEDY_ENABLED=true`, matching `ORG_ID`/`REMEDY_ORG_ID`, project
authorization and its real compiled `node dist/server.js`. The private URI/session
files remain outside the nonsecret Compose interpolation file.

Apply files in this order, retaining the same exact list/project name for every
config/start/stop operation:

| Mode | Ordered Compose files after `docker-compose.yml` | Explicit profile |
|---|---|---|
| Full signed implementation, writes held | `compose.scanner.yml`, `compose.bridge.yml`, `compose.integration.yml`, `compose.history.yml`, `compose.signed.yml` | `full-write` |
| Optional review with history | `compose.scanner.yml`, `compose.bridge.yml`, `compose.integration.yml`, `compose.history.yml` | `review-only` |
| Optional review scan/preview | `compose.scanner.yml`, `compose.bridge.yml`, `compose.integration.yml` | `review-only` |

Engine/Scanner standalone operation remains available as documented in the stack
guide. Never interpret an absent/unknown older producer profile as review-only.
The integration overlay does not infer a profile and has no writer-readiness
restart dependency. Automatic container restarts are disabled for the full
topology; the operator must reconcile outcomes before an explicit restart.

Historical review adds only existing `REMEDY_CLAIM_DB=/ledger/claims.sqlite3`,
`REMEDY_CLAIM_FENCE_DIR=/fence`, `REMEDY_OPERATION_STATUS_ISSUER` and exact opaque
**nonsecret** `REMEDY_REVIEWER_TRUST_EPOCH`. The same epoch string is given to
Conductor. `/fence/fence.json` has exact `trust_epoch` and `durability_seq` fields
and remains independent of ledger backups. The deployment team must provision
matching current ledger/fence/epoch before use; application startup never creates
or repairs them. Missing epoch affects terminal-proof recovery, not engine,
scan or preview startup. Historical lookup can work with Conductor signing
disabled; unknown/pending/404/null is never proof of no write.

The signed overlay additionally binds only the public keyring to Bridge through
`REMEDY_REVIEWER_KEYRING_PATH` → `REMEDY_REVIEWER_KEYRING_FILE`, and only the
protected Ed25519 private signer to Conductor through
`REMEDY_REVIEWER_SIGNING_KEY_PATH` → `REMEDY_REVIEWER_SIGNING_KEY_FILE`.
Both are regular nonsymlink UID-1000 files, mode 0400/0600, outside all data roots;
the Bridge keyring must contain public material only. The seven existing Conductor
settings are `REMEDY_REVIEWER_SIGNING_KEY_FILE`, `REMEDY_REVIEWER_KEY_ID`,
`REMEDY_REVIEWER_ISSUER`, `REMEDY_REVIEWER_AUDIENCE`,
`REMEDY_REVIEWER_KEY_ENABLED` (explicit `true` or `false`), `REMEDY_REVIEWER_KEY_NOT_BEFORE` and
`REMEDY_REVIEWER_KEY_NOT_AFTER` (epoch seconds). Coordinate key ID, issuer,
audience, validity, production environment and exact trust epoch with Bridge's
existing keyring/ledger/fence; test keys are refused in production. Snapshot and
audit paths remain `/ledger/snapshots` and `/ledger/audit.log`.

## Preflight, drain, start and health

Before any actual deployment, the deployment team must freeze the accepted
manifest, target, inspected image IDs, selected files, runtime versions,
configuration hashes, mount capacities/ownership, credential-name inventory,
network/PKI policy and current independent fence/epoch. The integration entry to
[preflight.py](preflight.py) requires `--profile integration` and explicit
`--integration-mode review-only` or `full-write`. It checks the original consumer
archive, matching actual-service receipts, resolved public Compose configuration,
per-role mounts, bounded filesystems and private TLS/NSS material. An engine-only
preflight does not validate those added services. Successful candidate checks
report `startupCompatibility:true`, `writeReady:false`, `admission:false`;
production acceptance remains refused while release flags are false. Add
`--production` for production acceptance: the current package must refuse it.

After that acceptance, from the reviewed repository root define the following
for the full signed selection. `REMEDY_COMPOSE_ENV` must name an already prepared
absolute nonsecret interpolation file containing image IDs, absolute bind/profile
paths, explicit `REMEDY_BRIDGE_PROFILE=full-write` and coordinated nonsecret
history/signer metadata. For optional review, select `review-only` and omit the
final signed file (and history file when unused) **consistently in every call**.

```sh
stack() {
  docker compose --project-name remedy --env-file "${REMEDY_COMPOSE_ENV:?required}" \
    -f deploy/stack/docker-compose.yml \
    -f deploy/stack/compose.scanner.yml \
    -f deploy/stack/compose.bridge.yml \
    -f deploy/stack/compose.integration.yml \
    -f deploy/stack/compose.history.yml \
    -f deploy/stack/compose.signed.yml "$@"
}
stack config --quiet
```

Resolve the **same** selection to a private mode 0600 JSON file, outside the
repository. It contains file paths and nonsecret metadata, never credential
values. Preserve it with the operator's private deployment inventory. The
following candidate verification runs no product admission or write enablement;
every path must already exist with the documented ownership and permissions:

```sh
(umask 077; stack config --format json > "${REMEDY_RESOLVED_CONFIG:?required}")
python3 deploy/stack/preflight.py --profile integration \
  --integration-mode full-write \
  --artifacts "${REMEDY_CANDIDATE_ARTIFACTS:?required}" \
  --proof "${REMEDY_PRIVATE_PROOF:?required}" \
  --integration-proof "${REMEDY_INTEGRATION_PROOF:?required}" \
  --conductor-target "${REMEDY_CONDUCTOR_TARGET:?required}" \
  --conductor-artifacts "${REMEDY_CONDUCTOR_ARTIFACTS:?required}" \
  --compose-config "${REMEDY_RESOLVED_CONFIG:?required}" \
  --state-root "${REMEDY_STATE_ROOT:?required}" \
  --mongo-state-root "${REMEDY_MONGO_STATE_ROOT:?required}" \
  --secret-root "${REMEDY_SECRET_ROOT:?required}" \
  --tls-root "${REMEDY_TLS_ROOT:?required}" \
  --nss-seed-root "${REMEDY_NSS_SEED_ROOT:?required}" \
  --renderer-seccomp "${REMEDY_RENDERER_SECCOMP_FILE:?required}" \
  --history --bridge-state-root "${REMEDY_BRIDGE_STATE_ROOT:?required}" \
  --fence-root "${REMEDY_FENCE_ROOT:?required}" \
  --trust-epoch "${REMEDY_REVIEWER_TRUST_EPOCH:?required}" \
  --status-issuer "${REMEDY_OPERATION_STATUS_ISSUER:?required}" \
  --signing-config "${REMEDY_SIGNING_CONFIG_JSON:?required}" \
  --keyring "${REMEDY_REVIEWER_KEYRING_PATH:?required}" \
  --signing-key "${REMEDY_REVIEWER_SIGNING_KEY_PATH:?required}"
```

The signing JSON is a private regular mode 0600 file containing exactly the seven
existing Conductor setting names listed above, including the in-container key
file path, never private-key bytes. The final two arguments select their actual
host files. This CLI checks a consistent configured pair, including an explicitly
disabled Conductor signer; it does not make that signer active. Review-only uses
`--integration-mode review-only` and omits all three signing arguments when the
signed overlay is absent. Omit `--history`, bridge/fence roots, epoch and issuer
only when the history overlay is absent. `--conductor-target` is exactly
`staging-67301b35` or `release-2.156.2`. The artifacts directory contains the
matching `candidate.json`, `build-inputs.json` and three original OCI archives;
the consumer directory contains its original ZIP and saved archive. Proof paths
select that same source/run's `result.json` and `full-result.json`.

1. Close external admission and orchestration; retain current containers/stores.
   Drain submitters/Conductor/Scanner while dependencies remain available. Record
   every accepted job and uncertain write outcome. Do not blindly replay it.
2. Stop Conductor and Scanner, then gracefully stop Server's owned engines,
   Bridge, renderer, and Mongo after its clients. Preserve raw exit states,
   descendant cleanup evidence, unresolved markers and current journals. The
   independent fence/epoch must remain current. Follow [cold-state.md](cold-state.md)
   before upgrades/rollback; no `down -v`, deletion or forced cleanup is supplied.
3. For a fresh accepted install or reconciled restart, start dependencies first:
   `stack up -d --no-deps mongo remedy-server remedy-renderer`. Verify authenticated
   database access, actual Server TLS `/readyz`, renderer liveness and intact
   storage/permissions before continuing. Process creation alone is insufficient.
4. Run `stack up -d --no-deps remedy-bridge adapt-scanner`, then verify Bridge's
   authenticated capabilities through Server and Scanner admission. Server must
   be running before Bridge because they share its network namespace. Start
   `stack up -d --no-deps conductor` only after the private dependencies work.
5. Check `stack ps`, Conductor `/health`, Server `/healthz` and `/readyz`, renderer
   `/healthz` and Scanner `/healthz`. These are separate liveness/admission facts.
   Use the actual authenticated Conductor project health, source/rendered scan,
   preview and current manual-evidence paths with authorized fixture data for
   acceptance. Never put keys into shell arguments or output.

In production full-write mode, Bridge `/readyz` **503 with `mutate:false` is the
expected immutable vendor hold**. Keep that fact explicit while independently
checking liveness, reads and historical status. It is neither a reason to loop
restarts nor to silently select review-only. Review mode requires strict
scan/preview booleans with mutation false; status is optional. Required-read
failure must remain unavailable until genuine successful required/default retry.
Full signed paths remain installed, but signer/liveness/metadata success does
not certify write readiness. A valid production signed mutation must still be
denied without creating an intent or external write. No test-mode production
workaround is provided.

## Recovery and remaining acceptance

Read [cold capture/restore and compatible rollback](cold-state.md),
[engine ownership/recovery](../engine-execution.md),
[HTML sandbox/resource policy](../html-resource-policy.md) and
[calibration evidence](../calibration-evidence.md). Freeze actual mount destinations
(`/app/state`, `/ledger`, `/data/db`) in the cold plan. Preserve coherent whole
SQLite/job/options/markers, Bridge ledger/snapshots/audit and Mongo journals.
Restore only into new bounded empty targets while retaining originals and the
independent current fence/epoch. Never restore an old fence to manufacture trust,
discard uncertain work, clear a claim, repair missing audit by assertion or replay
unknown operations. Compatible code upgrade/rollback must retain current history
and prove schema/journal compatibility on disposable state before real use.

The new YAML/static unit checks prove package configuration only. Actual exact
archive Linux service and browser proofs, full public-Compose operation,
failure/race/restart/terminal-unknown recovery, cold clone/upgrade/rollback,
shutdown and normal code/runbook reviews are distinct required receipts. Retained
signed apply/rescan/restore/replay must be tested separately in explicitly labeled
synthetic development/test proof; those receipts are not production vendor proof.
Production SSO, host/storage/network, provider authorization, external adapter,
vendor atomicity and specialist accessibility acceptance remain LibreTexts-owned
gates. No paid TestSprite or live validation is claimed here.

Related maintained entry points: [Bridge README](https://github.com/johnnyrobot/libretexts-remedy-bridge-dev#readme),
[renderer README](https://github.com/johnnyrobot/libretexts-remedy-bridge-dev/tree/f39566e0fa6413ed17e7a5c2a11fefc540ed5233/browser-scanner),
[ADAPT Scanner README](https://github.com/johnnyrobot/adapt-a11y-scanner-dev#readme),
[Conductor patch README](https://github.com/johnnyrobot/conductor-remedy-patch#readme)
and [pinned Conductor targets/storage prerequisites](https://github.com/johnnyrobot/conductor-remedy-patch/blob/dd152c5eca8e48609bbf7df9a9c8c63cf7b48fd2/docs/integration/pinned-targets.md).


### Reviewed key reload

The bundle wrapper forwards `SIGHUP` to the Bridge child in the signed profile.
A reviewed public-keyring replacement still needs the producer's normal reload
procedure; changing a file alone does not acknowledge revocation. Failed reload
keeps writes unavailable. Service-key changes require a drained restart.
Production `/readyz` remains 503 with `mutate:false` while the vendor hold is open;
a key reload never clears that hold. Review-only startup needs no keyring and is
not a signed-key reload target.
