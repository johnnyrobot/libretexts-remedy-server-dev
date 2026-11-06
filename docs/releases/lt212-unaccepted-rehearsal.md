# LT212: UNACCEPTED current integration candidate

This is a reviewable draft, not a released configuration or deployment approval.
LT227 is repaired in reviewed main`e7e86801ef95098358d6ef8e25887f23e597c457`;
main CI42173247382 passed clean exact installed Node22/24 and Python audits.
A new package using that lock still requires all matching proofs and review.
All five release/write/provider/SSO/owner flags remain false; there is no clean
package seal or production-write bypass. LibreTexts owns rollout timing and the
vendor conditional-write, adapter and target-policy validation before writes.
One maintained full integration retains optional review-only operation.

## Source selection and staging

The canonical bundle and Conductor index retain their previous selections.
The shared sealer preserves its default32-patch behavior and adds an explicit,
reviewed staged-candidate mode for the selected36-patch input; no default is promoted.
The canonical full proof, signed proof, public Compose, renderer env, preflight
and integration guide remain byte-identical to base
`8ca8d17607a3ac5cb48588a3de942fd7e5cb1d76`; they retain the older renderer's NSS
interface. Do not run those paths as though they selected the new producer.

The separate `.github/workflows/lt212-rehearsal.yml` stages `git archive HEAD`
under `.stack-inputs/server`, then invokes `lt212_rehearsal.py prepare`.
It refuses accepted/reused stages, changed security locks and unknown baselines.
It checks and applies the hash-pinned `lt212-inputs/renderer-trust.patch` using
`git apply --no-index --unidiff-zero`, without requiring a Git repository in the
source stage. Whole-file hashes are mandatory before and after this zero-context
patch; it is never applied on an unknown baseline. A child-only Git discovery
ceiling isolates the source stage from any parent checkout and caller index.
The patch changes the six paths above only inside that stage. Its expected
before/after hashes and original functional-proof source are in `inputs.json`.

The repaired Node lock is pinned to SHA256
`86c63beacdf9019db77ade11c00441a248e8910a7a018b0d442cd5fd7bddfcf1`.
The stage records `CLEAN_LOCKED_AUDITS_REQUIRED`; this is a requirement, not an
audit result. The candidate must include both source/lock-bound installed audit
records and actual proof of their success.

The same operation then overlays the exact bundle producer pins and Conductor
index, and replaces the old index constant in the staged preflight/importer.
`UNACCEPTED-LT212.json` records every modified path's before/after hash, the
source patch and false flags. These are deliberately modified staged sources,
not unmodified main. No recorded old proof transfers to another image or lock.

Selected reviewed inputs:

| Input | Immutable source |
|---|---|
| Bridge and renderer | `95a54dd3af850ca8eb5b8bf8be0395f0543c049e` |
| Original 36-patch Conductor deliveries | `617187fd7993714ae4d6fb939b30268fb7be6eee` |
| Conductor index SHA256 | `2e1297e9c180af7dce1f2e6894c6afffd0aff20ed71c3434dbccd36f14dc6e29` |
| Scanner registry manifest | `sha256:00ab363669ccc7ae50fe7fc79286508af5923d3326d397f87cff91ee76e379a6` |

## Public CA contract in the staged configuration

Rebuild the exact producer Dockerfile, including its Python guardian, signed
Ubuntu snapshot NSS tool and pinned Playwright base. Mount only the approved
public root PEM read-only at `/run/remedy-public-ca/roots.pem`, selected by
`RENDER_PUBLIC_CA_FILE`. The bundle's role directory is UID1001/mode0700; its
file is UID1001/mode0400 or mode0444, regular, absolute and without a final symlink
or any write bits. Maximum input is65,536 bytes/eight distinct self-issued,
signature-verified CA roots. Keys, leaf/intermediate certificates and parent
keystores are rejected. Startup snapshots the input; every admitted job gets its
own NSS database and SHA256/fingerprint provenance under the existing guardian.
Trust setup is bounded to1MiB/32entries, within the existing job/storage limits.
There is no TLS/hostname/sandbox disabling flag or shared writable browser HOME.
The separate frontend browser and other Node roles retain their own trust setup.
The immutable [producer contract](https://github.com/johnnyrobot/libretexts-remedy-bridge-dev/blob/95a54dd3af850ca8eb5b8bf8be0395f0543c049e/browser-scanner/README.md#operator-public-ca-trust-lt-239)
and patched staged integration guide provide the full details.

## Exact prior execution and remaining gates

[Source7ee60a1, run41464793233](https://github.com/johnnyrobot/libretexts-remedy-server-dev/actions/runs/41464793233)
passed build/unit/shipping/renderer/prove while the security job failed:
781 Linux unit passes/42 explicit toolchain-profile skips;273 shipping and39
renderer passes with zero skips. Both original compiled targets, private TLS
positive/negative controls, real browser sessions, public profiles/preflights,
evidence/recovery and cold restore/compatible upgrade/rollback rehearsals passed.
Review/production-held mutations were0. Separate synthetic development/test
flows made12 fixture writes, with0 recovery retries. No live service was used.

The [sanitized source/image/artifact receipt](lt212-functional-receipt-7ee60a1.json)
records the exact identities, hashes, results and finite expiry.

That source's exact uploaded archives and imported identities are retained in the
[image artifact](https://github.com/johnnyrobot/libretexts-remedy-server-dev/actions/runs/41464793233/artifacts/13149529362)
and [matching proof](https://github.com/johnnyrobot/libretexts-remedy-server-dev/actions/runs/41464793233/artifacts/13154387928),
with finite retention through December2,2026 UTC. Current isolation changes must
be assessed separately: matching patch-output bytes demonstrate source
equivalence for those paths, not new image acceptance or a rebuilt source hash.

LT227's supported repair is complete; the records above remain historical and
are not accepted proof for the new lock or package. The refreshed candidate
workflow requires all unit/shipping/renderer/audit jobs before assembled proof,
then validates the real signed/recovery/cold-state receipts and creates one
UNACCEPTED `remedy-stack-handoff-v1` candidate. All five flags stay false.

## Current candidate archive and operator verification

The explicit `seal_package.py --staged-checkout` mode checks the canonical
checkout/HEAD, the recorded before/after source recipe, exact36-patch producer
index, actual OCI/config/layer/import bindings, all required functional receipts
and clean Node22/24/Python audit records bound to the same source and locks.
It archives both `canonical-source.tar` and actual tested `source.tar`, with
`source.layout=canonical-git-archive-with-recorded-staging-overlays` and complete
per-file hashes. The build's resolved Dockerfile is reconstructed from its
recorded base digests, without another registry resolution; that overlay is
recorded too. No unrecorded source difference is accepted. Original Conductor
ZIP/archive/expiry guards and all existing receipt/image validators remain.

The workflow uploads only `package.tar`, `manifest.json`, `checksums.sha256` and
`seal-receipt.json` as `lt212-UNACCEPTED-candidate-<source>`, avoiding duplicate
loose payloads. The fresh readback job gets the trusted manifest and TAR hashes
from the producing job's outputs, downloads that exact wrapper, verifies every
member, expands into a new private directory and rechecks sources/OCI/original
consumer archives/receipts/audits. It imports the same archives and runs genuine
no-network kernel/crypto/browser prerequisite probes; Scanner/Mongo are pulled
only at their fixed registry digests. Its receipt is source-specific and never
authorizes deployment, store admission, cleanup or production writes.

Use Python3.11+ for file verification. Obtain both expected hashes from the
reviewed immutable source/run and trusted handoff record, independently of the
untrusted files being checked. Run from the reviewed repository source, without
executing downloaded source or image content before verification:

```sh
python3 .github/stack-proof/seal_package.py \
  --unpack "${REMEDY_DOWNLOADED_WRAPPER:?required}" \
  --output "${REMEDY_NEW_VERIFIED_DIRECTORY:?must not exist}" \
  --expected-manifest-sha "${REMEDY_EXPECTED_MANIFEST_SHA256:?trusted receipt required}" \
  --expected-tar-sha "${REMEDY_EXPECTED_TAR_SHA256:?trusted receipt required}"
python3 .github/stack-proof/seal_package.py \
  --verify "${REMEDY_NEW_VERIFIED_DIRECTORY:?required}" \
  --expected-manifest-sha "${REMEDY_EXPECTED_MANIFEST_SHA256:?trusted receipt required}"
```

No existing output is overwritten, links/traversal/extra or mismatched members
refuse, and a completed manifest is published last. Integrity hashes are not
signatures or independent authenticity. New artifacts have30day retention; the
candidate manifest records original consumer expiry separately. Retain exact
bytes and trusted receipts before expiry. The original20a retained release
remains separate historical provenance and is never overwritten.

Extract only the verified `source.tar` into a new private source directory;
its paths and hashes must match the manifest. Follow its staged
`deploy/stack/integration-profile.md` for supported Linuxamd64 DockerEngine/
Composev2/Skopeo, exact imports, private TLS and namespace, readonly per-role
credential FILE mounts/UID permissions, finite quotas, drain/start/health,
backup/compatible upgrade/rollback and target-host preflight. The source snapshot
is deliberately modified by documented overlays; checking out the canonical
commit alone does not reproduce those files. All fixed producer/image/lock/
policy identities come from the matching manifest and import receipts.

Required final native/external gates, new complete exact-package proof and
Chief review remain mandatory. All global flags stay false until the appropriate
owner accepts evidence; no deployment or approved release is published here.
Actual production host/provider/SSO and LibreTexts-owned vendor conditional-write,
adapter/allowlist/target-policy validation remain separate. Production writes
have no bypass toggle; review-only remains optional in one maintained full stack.
