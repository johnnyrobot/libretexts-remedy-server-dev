# LT212: UNACCEPTED, security-blocked rehearsal

This is a reviewable draft, not a released configuration or deployment approval.
LT227's actual production npm audit still fails with five moderate findings.
All five release/write/provider/SSO/owner flags remain false; there is no clean
package seal or production-write bypass. LibreTexts owns rollout timing and the
vendor conditional-write, adapter and target-policy validation before writes.
One maintained full integration retains optional review-only operation.

## Source selection and staging

The canonical bundle, Conductor index and sealer remain on their retained inputs.
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

LT227 still requires a supported parent dependency fix without override,
downgrade or audit ignore, followed by affected runtime and a fresh exact package
validation. Normal PR/native/external gates, retained final artifacts and
release-owner/production-host/provider/SSO/vendor acceptance remain pending.
The original20a retained delivery is historical provenance, not endorsement of
its old vulnerable runtime. See the root and stack READMEs for the preserved
canonical instructions; this staged rehearsal does not promote their pins.
