# Remedy Server

Remedy Server is the PDF, modern Office and HTML accessibility checking,
remediation and conversion engine. FastAPI exposes `/v1/*`; it has no frontend.
The Python package remains `project_remedy`. Conductor is the staff integration,
[ADAPT Scanner](https://github.com/johnnyrobot/adapt-a11y-scanner-dev#readme)
submits rendered questions, and
[Remedy Bridge](https://github.com/johnnyrobot/libretexts-remedy-bridge-dev#readme)
provides CXone page scan/preview and guarded write/history operations.

One maintained codebase/package retains the full signed integration, including
apply, restore and outcome recovery. Engine/Scanner standalone operation and
Bridge review-only operation are **optional rollout choices**. LibreTexts chooses
its rollout timing. A scan, preview, readable download or reduced finding count
does not mean content was fixed, specialist-reviewed or WCAG/PDF-UA conformant.

**Production automatic writes are held. There is no bypass toggle.** Before
activation, LibreTexts' integration/deployment team must obtain vendor-supported
revision-atomic conditional-write confirmation and authorized validation, and
review any required conditional adapter, target policy and allowlist changes.
Keys alone do not enable production writes. This is not a Johnny checkpoint.
The current Bridge policy is restricted to its reviewed host/owner sandbox;
this package does not silently widen it to other libraries.

## Release status and supported candidate

The deployment package remains a candidate until the exact archives and pulled
Scanner digest pass the complete Linux service proof and operational acceptance.
`deploy/stack/bundle.json` deliberately keeps `deploymentReady` and
`productionWritesEnabled` false. Do not infer acceptance from image build,
process liveness, partial test output or component-only tests.

Optional Bridge review acceptance is currently blocked by an upstream-read
readiness defect in the pinned Bridge; the [health limitations](deploy/stack/README.md#health-bounds-and-failures)
record the actual failure. The corrective Server envelope and packaging work
still require complete Linux proof and review.

The [stack guide](deploy/stack/README.md) is the next entry point. It describes
artifact verification, exact configuration/credential **file names**, private
transport, modes, mounts, limits and operator checks. Current fixed inputs are:

| Input | Exact reference |
|---|---|
| Server baseline | `065c86ebb0d856d5b9ada8bd7b41bd8c4d90ce10` or the reviewed descendant recorded in the candidate manifest |
| Bridge | `03d961d7fbfbcc36bad885f5ec06d5f289cba09e` (`cxone-review-v1`, `cxone-terminal-v1`) |
| Scanner | Registry manifest `sha256:00ab363669ccc7ae50fe7fc79286508af5923d3326d397f87cff91ee76e379a6`, source `1541bb8f3962553b65dab7bfd5aeb429354a8a4f` |
| Platform | Linux amd64, Docker Engine/Compose v2, compatible pidfd/subreaper/user/PID namespace and Chromium seccomp support |

Server uses the full runtime, never runtime-slim for HTML/Scanner. The candidate
workflow archives Server/Bridge OCI images, downloads/imports those same archives
in another job, and pulls Scanner by its exact registry manifest digest. Resolved
base, lock, profile, source, archive and runtime measurements belong to that
immutable run's metadata. No `latest` tag or rebuilt Scanner is a substitute.
Actual production host, storage/network policy and external providers are not
verified merely by that synthetic CI run.

## Choose the needed modules

| Mode | Required modules | Readiness and unavailable work |
|---|---|---|
| Engine | Server | `/readyz` proves engine/store admission; Bridge absent is valid and CXone capabilities are explicitly false. |
| Engine + ADAPT | Server + exact Scanner | Authenticated scan results matter; Scanner `/healthz` proves admission availability, not live ADAPT credentials or complete rendering. |
| Optional Bridge review | Add actual Bridge with `REMEDY_BRIDGE_PROFILE=review-only` | Authenticated named scan+preview required; mutation always false; historical status optional. No signer/keyring/ledger needed for scan/preview. |
| Full signed integration | Same images/implementation plus reviewed signing/history configuration | All required capabilities and production hold apply. Signed paths remain delivered; automatic production writes are unavailable while the vendor/policy gate remains open. |

An absent/unknown producer profile is never interpreted as review-only. Malformed
or inconsistent known readiness fields fail closed. Optional nonsecret
`REMEDY_REVIEWER_TRUST_EPOCH` belongs to Bridge/Conductor terminal-proof recovery,
separately from signer settings; absence does not break engine/scan/preview
startup. Lookup remains read-only, can work with signing disabled when configured,
and a404/null proof is never proof of no write.

## Safe starting sequence

1. Read the [stack prerequisites and mode/config matrix](deploy/stack/README.md).
2. Obtain only reviewed exact candidate archives/metadata and the matching proof;
   verify hashes before import. Keep private credentials outside repository/image
   layers and use the documented per-role files/UID permissions.
3. Pre-provision the bounded local POSIX state/mounts and approved private network.
   Run the documented fail-closed preflight on the intended Linux host. An
   unsupported host is a stop condition, never a reason to disable sandbox/auth,
   add capabilities or loosen host policy.
4. Follow that guide's drain/start/health and operator acceptance order. Production
   candidate acceptance, coherent backup/restore, compatible upgrade/rollback and
   full Conductor recovery remain required release gates; this README grants no
   live deployment, credential provisioning or write activation.

The current isolated CI topology denies non-fixture egress. Real external-service
connectivity requires the deployment team's reviewed target network/TLS policy;
no permissive outbound or public-Bridge workaround is supplied. Bridge stays on
127.0.0.1 in a shared private network namespace and has no published staff panel.

## API, artifacts and limitations

[HTTP routes and engine configuration](docs/http-api.md) document the interface.
All `/v1/*` calls require `X-API-Key` in production. The bundle reads credentials
from private files; Server never holds a reviewer signing private key. `/healthz`
is liveness; `/readyz` is engine/store readiness. Authenticated `/v1/cxone/health`
checks the private Bridge's `/readyz` and named capabilities.

HTTP202 is acceptance, not success. Poll jobs to `done` or `failed`; result409
means unavailable for queued/running/failed work,410 means a completed artifact is
now missing/empty/unreadable. Modern Office/HTML outcomes independently validate
usable artifacts; accessibility/quality advisories preserve genuine downloads.
Legacy DOC/PPT/XLS remediation is415, without changing unrelated handlers.

Calibration-dependent quality is unavailable until parser-readable, attributable
corpus/result evidence has independent operator approval. The historical bootstrap
corpus does not qualify; no approval is manufactured to make readiness green.
See [calibration evidence](deploy/calibration-evidence.md). Optional AI/WAVE/Adobe
work needs its own authorized provider configuration and actual failures remain
failures; availability of the base engine does not prove those providers.

[Execution, admission and offline recovery](deploy/engine-execution.md) covers
Linux ownership, finite deadlines, quarantined work and one process per store.
[HTML policy](deploy/html-resource-policy.md) covers offline resources and real
sandbox requirements. The [stack operations guide](deploy/stack/README.md#operations-and-remaining-acceptance)
is the entry for storage, backup/upgrade/rollback and target-host acceptance.
Never erase unresolved markers, restore an old independent fence to force trust,
blindly retry uncertain writes/jobs, or turn a preview into conformance evidence.

## Development

Use `uv sync --extra dev --frozen`, then `uv run --frozen pytest tests/unit`.
macOS/unsupported platforms intentionally refuse strict engine admission with503;
profile-gated local skips do not establish shipping support. Actual Linux CI uses
nonroot processes, cap-drop ALL, NNP, reviewed seccomp and real Chromium/native
work. No Docker Desktop/host-policy relaxation or fake frontend is required.
See `.github/workflows/ci.yml` and `stack-candidate.yml` for exact checks. TestSprite
work is separate and is not claimed by these API/stack tests.
