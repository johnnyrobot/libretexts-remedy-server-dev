# Cold evidence capture and conservative restore (LT-197)

[`cold_state.py`](cold_state.py) captures the three complete, stopped Server,
Bridge and Conductor Mongo store trees together. It restores a verified archive
only into three new, already empty directories while retaining every original
store. This is a cold-clone rehearsal and evidence-preservation helper. It does
not establish disaster recovery, production readiness, database compatibility or
permission to start applications. Start at the [stack guide](README.md) and read
[engine ownership and recovery](../engine-execution.md) first.

Production automatic writes remain held by the LibreTexts integration/deployment
team. There is no write-enablement or safety-bypass option here. No live server
operation, real credential provisioning, migration or cleanup is authorized by
this guide.

## Supported operator environment

The operator CLI requires Python 3.11+, Linux amd64, effective UID 0 for exact
numeric ownership, and local rootful Docker at `unix:///var/run/docker.sock`.
It refuses Docker endpoint environment overrides, remote contexts, Docker
Desktop, rootless/userns-remap, and filesystems other than local ext4/XFS. All
store roots, the current fence, excluded credential/configuration roots, output
parents and restore targets must be existing absolute canonical paths. The
reviewed package's normal host, capacity, kernel and security preflight still
applies; this helper does not replace it or change host settings.

Stores must be exclusively owned by the stopped configured workloads. The
operator must disable external admission, automatic restart/orchestration and
host-side writers before capture, and keep them disabled through clone
verification. Docker observations detect competing running containers mounting a
store, restore target or the independent current fence, including an ancestor
mount. A running container using a different ledger still causes refusal when
it can access this same current fence. They cannot prove that an
unrelated host process, administrator or storage controller will never write.
Use the existing dedicated bounded private state filesystem and retain enough
space for all originals, the complete uncompressed archive and all three clones.
Sparse allocation is not preserved; plan for full file lengths.

Only regular files and directories are supported. Symlinks, multiply linked
files, device/FIFO/socket entries, xattrs/ACLs and cross-device nested stores are
refused rather than silently transformed. Overlapping data roots, nested Docker
data mounts and data roots containing the fence or any declared credential root
are refused. All independent epoch/configuration files, private keys and
credential directories must be declared outside the three archived trees.
The helper cannot identify a secret that was incorrectly copied into a data
file: deployment owners must ensure that data roots contain no credential files.
The archive contains private job documents, snapshots and audit data; handle it
as sensitive evidence.

## Freeze the actual plan

Use the exact reviewed immutable image IDs actually imported into Docker, not
tags, source config digests or an unverified replacement image. Record every
configured process, including Conductor, Scanner and the Bridge renderer, even
when that process has no data mount. All listed processes must have actually
started and now be stopped. Resolve each data root from its owner's inspected
mount source and exact destination. Preserve the original stopped containers
until both capture and clone verification finish.

The version-1 JSON plan has exactly these top-level fields. The following is a
shape example with deliberately invalid identity placeholders; obtain and review
real values before invoking the helper. Values are paths and nonsecret identity
metadata, never credential contents or environment dumps.

```json
{
  "version": 1,
  "stores": {
    "server": {"source": "/srv/remedy/state/server", "container": "SERVER_CONTAINER_64HEX", "destination": "/app/state"},
    "bridge": {"source": "/srv/remedy/state/bridge", "container": "BRIDGE_CONTAINER_64HEX", "destination": "/ledger"},
    "mongo": {"source": "/srv/remedy/state/mongo", "container": "MONGO_CONTAINER_64HEX", "destination": "/data/db"}
  },
  "processes": {
    "server": {"id": "SERVER_CONTAINER_64HEX", "image": "sha256:SERVER_RUNTIME_64HEX", "exit_code": 143},
    "bridge": {"id": "BRIDGE_CONTAINER_64HEX", "image": "sha256:BRIDGE_RUNTIME_64HEX"},
    "mongo": {"id": "MONGO_CONTAINER_64HEX", "image": "sha256:MONGO_RUNTIME_64HEX"},
    "conductor": {"id": "CONDUCTOR_CONTAINER_64HEX", "image": "sha256:CONDUCTOR_RUNTIME_64HEX"},
    "scanner": {"id": "SCANNER_CONTAINER_64HEX", "image": "sha256:SCANNER_RUNTIME_64HEX"},
    "renderer": {"id": "RENDERER_CONTAINER_64HEX", "image": "sha256:RENDERER_RUNTIME_64HEX"}
  },
  "fence": "/srv/remedy/trust/current-fence.json",
  "credential_roots": ["/srv/remedy/credentials", "/srv/remedy/trust"]
}
```

Every process defaults to expected raw exit status 0. Only the exact `server`
role may explicitly expect 143: the frozen Uvicorn signal handler re-raises
SIGTERM after its shutdown sequence, and the existing wrapper retains that raw
status. **143 alone is not proof of graceful descendant cleanup.** Do not change
wrappers to convert it to 0. OOM, Docker errors, killed/other nonzero exits,
running/paused/restarting/dead states or changed identities always refuse capture.
Missing containers and unexpected data mounts also refuse it. Unknown plan fields
are rejected to avoid serializing unintended configuration into the archive.

The receipt records raw exit codes and always sets `processCleanupCertified` and
`admissionAuthorized` to `false`. A successful capture, including a capture with
unresolved ownership markers, preserves evidence only. Actual owned-stack Linux
shutdown/lifetime/marker/journal assertions are separate operational acceptance.
This distinction permits retaining unresolved evidence without pretending it is
safe to reopen the store.

The current Bridge fence is an independent, nonsymlink, single-link regular file
outside every data root. Its SHA-256 and file identity/stat fingerprint are
checked before/after capture and before/after restore. Its bytes are never copied
into the archive or restore targets. The fingerprint is filesystem metadata,
not a cryptographic signature. The current trust epoch is deployment
configuration outside data archives: retain it unchanged and record that fact
in the operational acceptance evidence. Historical epoch metadata already stored
in the ledger remains preserved; it does not replace the independent current
configuration. Never restore an old fence or epoch to
make old history appear trusted. Terminal proof is not independently signed by
this helper.

## Drain, stop and capture

1. Have the deployment owner freeze the compatible source/image/configuration
   manifest, trust epoch, exact mount inventory and accepted start/stop procedure.
   This task's rehearsals use disposable synthetic data and fake external
   providers only. An unapproved live deployment remains out of scope.
2. Close ingress/admission and await actual in-flight outcomes. Account for
   ambiguous accepted jobs and writes; do not blindly resubmit or replay them.
   Stop consumers/submitters first, keep their dependencies available for drain,
   then stop Server and its owned engines, Bridge and its renderer, and Mongo
   after its clients. Use the accepted role-specific graceful stop procedure,
   not a kill, volume deletion, or a blanket claim based on one exit status.
3. Preserve the three whole store roots, including SQLite databases and WAL/SHM,
   job inputs/outputs/options and staging journals, ownership locks and unresolved
   markers, quarantined evidence, Bridge ledger/snapshots/audit, and Mongo data,
   lock files and journals. Do not open SQLite/Mongo independently or copy only
   selected database files. Do not clear any marker or claim. This tool uses
   stopped byte-for-byte trees; it performs no SQLite checkpoint or database API
   backup and no database repair.
4. Keep current independent fence/epoch and credentials outside those roots.
   Prepare a private output directory and a reviewed plan file (mode 0600);
   output parents must already exist. Use new archive and receipt names. The
   helper refuses existing outputs and never deletes failed output evidence.
5. From the reviewed checkout, run the command below with the actual absolute
   paths. These example `/srv/remedy` paths are operator-selected prerequisites,
   not directories the helper provisions.

```sh
sudo python3 deploy/stack/cold_state.py backup \
  --plan /srv/remedy/operations/cold-plan.json \
  --archive /srv/remedy/backups/cold-001.tar \
  --receipt /srv/remedy/backups/cold-001.receipt.json
```

Exit 0 returns the archive and manifest SHA-256 values plus the explicit limited
receipt. Both output files are created exclusively with mode 0600. The archive
and containing directory are fsynced before a receipt is durably written. Full
source inventories, file identity/stat fingerprints, Docker state and fence
must remain unchanged during capture. A failure may leave a private partial
archive or receipt: retain it as incomplete evidence and use new paths after
owner investigation; file existence alone is never acceptance.

The receipt is local integrity evidence held with the reviewed manifest. It is
not signed provenance or authenticity against someone able to replace both
archive and receipt. Retain them under the deployment owner's access and
retention controls; do not publish them as CI artifacts containing private data.

## Verify and restore only to empty new targets

Provision three private empty local directories outside every original store,
credential/configuration root, fence and backup location. Do not rename,
overwrite, delete or empty current data. A targets JSON file maps all three roles:

```json
{
  "server": "/srv/remedy/clones/cold-001/server",
  "bridge": "/srv/remedy/clones/cold-001/bridge",
  "mongo": "/srv/remedy/clones/cold-001/mongo"
}
```

Keep the same actual original stopped containers and the same exact plan. Run:

```sh
sudo python3 deploy/stack/cold_state.py restore \
  --plan /srv/remedy/operations/cold-plan.json \
  --archive /srv/remedy/backups/cold-001.tar \
  --receipt /srv/remedy/backups/cold-001.receipt.json \
  --targets /srv/remedy/operations/cold-targets.json
```

Before any target write, the helper verifies the archive checksum, manifest,
complete inventory, every file digest and represented permission/UID/GID/mtime,
member names/types, duplicate/traversal/link refusal, exact original process and
mount identities, the independent current fence, and unchanged original store
inventories. It checks all target directories are still empty, then uses
exclusive no-follow file creation through pinned directory descriptors. Each
file is fsynced with its bytes and metadata; directory metadata is applied and
fsynced from children to parents. Restored bytes and represented metadata are
re-inventoried, with another original-store/Docker/fence/archive check. Numeric
UID/GID, permissions and nanosecond mtime are preserved; inode, ctime, atime,
sparse layout and unsupported extended metadata are not recreated.

Exit 0 means only that these three new cold trees verified. The helper never
starts applications, remounts data, migrates schemas, clears quarantine/ownership,
replays work, generates keys or alters the fence/epoch. An error during copying
can leave a partial clone. Keep it disabled and preserve it for owner review;
there is no automatic cleanup, resumption or overwrite flag. An original store
or current fence that is missing, replaced, modified or newer than the snapshot
causes refusal, even if its bytes were later changed back.

## Compatible upgrades, rollback and manual recovery

A compatible code upgrade/rollback retains current data, current fence/epoch,
unknown outcomes and immutable journals. Capture and verify the cold clone first
while original identities still exist. Only the accepted package's separate
start/health/authorization/marker procedure can permit reopening the current
stores under a proven compatible binary. The helper does not compare schemas or
certify a binary compatible. An older binary that cannot enforce the current
submission journal phases must not open the store.

If any current work/history/configuration advanced after backup, automatic data
rollback is refused. Never replace the originals with the older clone, clear a
claim, edit the receipt, reset the current fence/epoch or replay unknown writes
to get past that refusal. Deployment-owner recovery is required for lost or
changed originals, changed container identities, changed fence/epoch, incompatible
schemas, uncertain process lifetime, unresolved ownership, missing audit,
unsupported metadata/storage, failed partial clones or genuine host loss. This
helper intentionally supplies no destructive disaster-recovery path. Engine
restart refusal and Bridge/Conductor trust/freshness checks remain in force.

The storage tests in `tests/unit/test_cold_state.py` use temporary files and
controlled Docker observations. They prove preservation/refusal behavior, not
actual Linux services, production PKI/SSO, vendor atomicity, schema migration or
operator readiness. The full integration workflow must separately prove the
same CLI on actual stopped owned containers with disposable data, inspect the
original and clone bytes/history/markers, and exercise compatible code
upgrade/rollback while retaining current data and the independent fence. A green
unit suite alone does not close LT-197 or any production release gate.
