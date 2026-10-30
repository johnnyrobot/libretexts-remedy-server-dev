# One maintained Remedy integration package

Start at [Server README](../../README.md). This directory replaces the old
build-from-siblings/public-panel guidance. These are candidate inputs, not an
accepted production deployment: release flags remain false until exact Linux
proof, the operational slice and release-owner review finish. LibreTexts selects
rollout timing. Review-only is optional; full signed apply/restore/history code is
retained. Production automatic writes have no bypass toggle and still require
the LibreTexts-owned vendor, adapter and target-policy validation.

## Immutable artifacts and prerequisites

Use host Python 3.11+ for the standard-library preflight CLI (including
`hashlib.file_digest`); the service interpreter is inside the exact image.
Use Linux amd64 with Docker Engine/Compose v2, cgroup v2, pidfds/subreaper and
unprivileged user/PID namespaces/Chromium seccomp support. No arm64, Podman,
rootless/userns-remap or target-host guarantee is inferred. Preflight must refuse
unsupported policy; never use root browsers, no-sandbox, extra capabilities,
seccomp unconfined or host-wide changes to make it pass.

The `Private stack candidate` workflow builds clean canonical Server full-runtime
and Bridge sources with resolved base digests, exports OCI archives and hashes,
then downloads/imports those exact archives in a different Linux job. It pulls
Scanner at the literal registry digest in `compose.scanner.yml`; it does not
rebuild Scanner. Candidate artifacts have 30-day retention: a reviewed handoff
must retain the exact accepted artifacts beyond that window. Builds, partial
commissioning runs and unsigned local JSON are not proof of trusted provenance.
Use the exact reviewed main run/commit, its candidate manifest and complete proof,
never a floating branch/tag or a substituted rebuild. The build includes no
runtime credentials; synthetic credentials are created only after image import.

The veraPDF 1.30.1 installer is pinned in
`tools/build-inputs/verapdf-installer.json`. Its detached signature was checked
against the full fingerprint in the publisher's installation documentation.
`tools/fetch_verapdf_installer.py` verifies size/SHA-256 before use; Docker checks
the same pin before extraction or Java execution. The installer and pin hashes
are recorded with build inputs. An upstream change fails the build until reviewed.

The bundle input file lists source/contracts/resource choices. Runtime output
records actual source/base/lock/profile/archive/image IDs, registry manifest
identity, host and measurements. OCI manifest/config IDs and registry manifest
digests are distinct. Global `deploymentReady`/`productionWritesEnabled` stay false
until the release owner reviews the complete compatible bundle.

OCI config digests and Docker's imported image IDs can differ across the import
format conversion. The proof records both in `imports.json` and requires equal
filesystem diffIDs and runtime configuration (including credentials-free image
environment, user, command, labels and healthcheck). An archive hash alone is
insufficient to identify the running image. No rebuild is substituted.

## Modes and command order

One base Compose file plus optional overlays use the same images/data formats:

- Engine: `docker-compose.yml`.
- Engine+Scanner: add `compose.scanner.yml`.
- Optional Bridge: add `compose.bridge.yml`, with explicit existing
  `REMEDY_BRIDGE_PROFILE=review-only` or `full-write`. Omission must not silently
  choose review-only. Full-write production readiness remains held.

Load verified immutable image IDs from the imported archives into
`REMEDY_SERVER_IMAGE`/`REMEDY_BRIDGE_IMAGE`. Do not put `build:` or `latest` into the
start command. Supply absolute `REMEDY_SERVER_SECCOMP_FILE` and
`REMEDY_SCANNER_SECCOMP_FILE` pointing to the exact reviewed JSON files; Scanner
policy provenance/license are in `scanner-profile-source.json`. Its unchanged
Apache-2.0-derived policy comes from the pinned Scanner source and Playwright
profile referenced in that repo's shipping guide.

`REMEDY_STATE_ROOT` is a pre-provisioned private UID 999 dedicated local POSIX
filesystem within the recorded 1 GiB candidate budget. Directory/project quota
verification is not implemented in this candidate; a larger underlying filesystem
is refused even when it has a separately configured quota. Local ext4/XFS are accepted;
network filesystems and active independently copied SQLite stores are unsupported.
`REMEDY_SECRET_ROOT` contains separate private per-role directories. Do not let
Compose create unknown host paths: bind mounts use `create_host_path:false`.
Copy the nonsecret `env/*.env.example` files to the matching `*.env` names and
replace only authorized nonsecret deployment settings. No plaintext credentials
belong there. Do not run commands with placeholder hosts/permissions.

Before any start, verify artifact/config hashes, release acceptance, host/runtime,
state capacity/ownership, credentials and per-image kernel/sandbox checks.
`preflight.py` is the fail-closed entry point; partial static checks must not be
reported as operational acceptance. Production remains refused while the bundle
is unaccepted. The actual reviewed safe start/stop/upgrade/rollback sequence must
be frozen with the completed operational proof, not invented from `compose up`.

## Private transport and authentication

Server and Scanner use the dedicated private Docker network with no host port
publication. Authorized callers on that network use `remedy-server:8000` and `adapt-scanner:5176`;
off-host/private TLS ingress belongs to the reviewed operational package. Scanner
requires `SCANNER_API_KEY`; its `REMEDY_API_KEY` must equal Server's application
key. Bridge uses `network_mode:service:remedy-server`, still listens on 127.0.0.1 and
has **no published Bridge port, direct panel or alternate bind address**. Server
reaches it via 127.0.0.1:5175; another container cannot use Server's external address
to reach that loopback listener. Both hops remain authenticated. Off-host callers
need reviewed private TLS; no public/tunnel workaround is authorized.

The candidate network is internal/default-deny. The synthetic rehearsal supplies
only external ADAPT/CXone/AI fixtures; it is not evidence that real providers or
production networking work. A real deployment needs the team's reviewed
restricted egress/TLS policy and target acceptance; do not disable internal
isolation as an undocumented workaround.

`secret-env.mjs` is a bundle entrypoint mounted read-only, not a new producer
signing protocol. It reads private regular nonsymlink files owned by the actual
application UID (mode 0400/0600), rejects ambiguous direct values, then starts the
unchanged product command. Values are printable ASCII, optionally one final LF;
no embedded newline/NUL or oversized credential. Provider values never appear in
arguments/logs/images. Changes require a coordinated drain/restart.

| Role/file below secret root | Existing product variable | Bundle file variable |
|---|---|---|
| `server/app` | `APP_API_KEY` | `APP_API_KEY_FILE` |
| `server/ollama` | `OLLAMA_API_KEY` | `OLLAMA_API_KEY_FILE` |
| `scanner/api` | `SCANNER_API_KEY` | `SCANNER_API_KEY_FILE` |
| `scanner/adapt` | `ADAPT_TOKEN` | `ADAPT_TOKEN_FILE` |
| `scanner/remedy` | `REMEDY_API_KEY` | `REMEDY_API_KEY_FILE` |
| `bridge/key` | `SERVER_KEY` | `SERVER_KEY_FILE` |
| `bridge/secret` | `SERVER_SECRET` | `SERVER_SECRET_FILE` |
| `bridge/user` | `SERVER_USER` | `SERVER_USER_FILE` |
| `server/service`, `bridge/service` | Existing file-backed private-hop key | `REMEDY_BRIDGE_SERVICE_KEY_FILE` |

Server UID 999 and Bridge UID 1000 need separate mode 0400 files with identical
service-key bytes; Scanner keeps the image's `pwuser` UID, checked from the exact
artifact. Application-key copies likewise match without broad group/world access.
The service key format is 64 lowercase hex characters, optionally one LF. These
are file names/prerequisites, not authorization to provision real credentials.

Optional historical recovery uses existing issuer/store/fence settings and the
**nonsecret** `REMEDY_REVIEWER_TRUST_EPOCH` shared exactly by Bridge/Conductor.
It is separate from signer configuration. A missing epoch can disable terminal
proof recovery but must not prevent engine/scan/preview startup. Historical
lookup works without signing when correctly configured, never clears state and
never treats 404/pending/null as proof of no write. Compatible Conductor manifests
and its exact signer-setting matrix await the reviewed consumer/operational slice.

## Health, bounds and failures

Liveness is not readiness. Server `/readyz` concerns its store/engine; authenticated
`/v1/cxone/health` checks actual Bridge `/readyz` and strict named capabilities.
Review mode requires scan+preview, explicitly `mutate:false`; status is optional.
Full-write requires its published capability set. Unknown/malformed/partial
producer profiles are not inferred as review-only. Required read failure must
remain unavailable until genuine successful retry. Reviewed Bridge `998fa1e` corrects the observed upstream 401/403 failure
classification without changing the public contract. The preserved red
run `40987997157` remains evidence; acceptance requires a fresh exact-artifact
run with the corrected pin. Successful required/default scan or deterministic
preview is the verified recovery path; optional-source success does not itself
clear the latch (LT-202). Full-write read-capability debt (LT-204) remains a
separate blocker for the later full-integration freeze. A healthy metadata
response alone is insufficient. Scanner `/healthz` concerns admission;
only an actual authorized scan establishes its external/render/validator outcome.
Empty/malformed/partial data is not a clean pass. Calibration remains unavailable
on historical placeholder evidence; usable artifacts preserve explicit advisories.

The chosen finite CPU/memory/PID/tmp/state/request/deadline/shutdown inputs are in
`bundle.json`. They are candidate choices until measured actual Linux proof
passes. Scanner uses 1 GiB shm, 20-second stop grace, cap0/NNP/init and its exact
seccomp policy. Server retains the minimal pidfd exceptions and real HTML sandbox
requirements. Read-only image roots and bounded tmpfs are not replacements for
persistent-state capacity, safe full-disk failure or cold recovery proof.

Server's `MAX_REQUEST_BYTES=5000000` bounds the complete raw `/v1/` envelope,
including ignored JSON fields and multipart overhead, before normalization or
job acceptance. Declared and streaming/chunked bodies use the same limit.
`MAX_UPLOAD_MB=4` is a separate selected-file limit. Outside this package, an
unset total limit derives from the file budget plus 1 MiB overhead; zero or
negative explicit limits refuse startup. Authentication still precedes body
parsing/refusal, and rejected bodies do not reach Bridge or accept jobs.

## Operations and remaining acceptance

[Engine execution/recovery](../engine-execution.md) and
[calibration evidence](../calibration-evidence.md) define current retained state
and unavailability semantics. Drain all relevant owned work and preserve one
coherent cold SQLite/WAL/input/output/options/ownership bundle. Never erase
unresolved markers or replay uncertain jobs/writes. Bridge ledger/snapshots/audit
and Conductor Mongo immutable journals need their compatible cold procedure;
never restore an old independent fence/epoch to force trust. Original actor,
outcome/nonce/history and missing audit remain explicit.

Actual full-stack authorization, scan/preview/manual-evidence freshness,
production mutation denial, terminal/unknown status and explicit recovery/races
remain operational acceptance. Retained signed apply/rescan/restore/replay is
proved separately only in clearly labeled dev/test synthetic mode; it is not
vendor atomicity proof or a production-hold bypass. Coherent backup/restore,
compatible upgrade/rollback and unsupported-host refusal must pass on disposable
state before the complete package is called accepted. The current component
slice does not claim those later gates passed.

Other maintained entry points:
[Bridge README](https://github.com/johnnyrobot/libretexts-remedy-bridge-dev#readme),
[Scanner README](https://github.com/johnnyrobot/adapt-a11y-scanner-dev#readme), and
[Conductor patch README](https://github.com/johnnyrobot/conductor-remedy-patch#readme).
