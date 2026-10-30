# Engine admission, deadlines, and recovery

LT-139/LT-144 use **Linux amd64**, Python 3.11+, kernel pidfds and child
subreaper adoption, and a local POSIX SQLite/filesystem store. Run one uvicorn
process per store. Network filesystems and independently copied active stores
are unsupported. The runtime must permit `PR_SET_CHILD_SUBREAPER`, `pidfd_open`
and `pidfd_send_signal` under its security policy, including after capabilities
are dropped. The full-runtime CI exercises the shipped non-root policy.

An isolated spawn preflight verifies subreaper permission before readiness,
admission or queue recovery; the API itself never becomes a subreaper. A
required full-runtime test session fails immediately if the complete production
profile is unavailable, rather than passing with skipped lifetime checks.

macOS and other runtime profiles cannot prove the same ownership guarantee.
They refuse strict engine admission with HTTP 503 before upload staging or
queue-row creation. `/healthz` stays available and `/readyz` returns 503.
There is no production fallback to census-only process tracking or threads.
Use the Linux profile for local engine integration and production verification.

## Admission and deadlines

| Setting | Default | Meaning |
|---|---|---|
| `WORKER_CONCURRENCY` | `1` | Active compute lifetimes, shared with direct operations |
| `WORKER_MAX_PENDING` | `8` | Additional admitted work, including direct calls awaiting a slot |
| `JOB_TOTAL_TIMEOUT_SECONDS` | `900` | Finite positive total seconds from admission, including upload, queueing, retries and processing |

Limits must be positive. Admission returns 503 with `Retry-After: 5` before
persistent upload staging or queue creation. Authenticate first. This is
backpressure guidance, never permission to retry a mutation automatically.
Upload validation/storage failure releases its reservation and temporary files.
Accepted jobs survive caller disconnect; direct operation cancellation requests
cleanup and waits for proof before releasing capacity.

`deadline_at` is an additive persisted UTC deadline. Restart never grants a
fresh budget. Old rows use `created_at` plus the configured total budget.
Expired queued jobs fail without executing; inputs remain available. Existing
PDF remediation/acceptance/quality deadlines are upper bounds inside the total
budget. Internal retries consume the remaining time.

Dequeueing is not dispatch. A durable upload stays `queued` while a direct
request owns the shared execution slot. Only after slot acquisition can the
parent publish `running` and begin the supervised startup. Shutdown preserves
never-dispatched queued rows and their original input/options/deadline for cold
recovery. Expired queued rows still fail without work; unresolved prior
ownership still blocks restart/recovery entirely. A running row is never
automatically replayed. Submission journaling must claim dispatch at this same
slot-acquisition seam, not at queue removal.

## Lifetime proof and publication

The API exclusively locks `<database>.execution.lock.owner` and holds a shared
`<database>.execution.lock`. Before spawning anything, it creates and fsyncs an
operation marker in `<database>.execution.lock.unresolved/` and fsyncs that
directory. Startup checks this directory under exclusive locks **before**
recovering running/queued rows. Never unlink/replace locks or markers during
active work; include these files in cold recovery evidence.

A dedicated lightweight supervisor acquires the shared lifetime lock and
establishes Linux subreaper adoption. It reports ready; the API must explicitly
authorize dispatch before it forks compute. Compute is a distinct process and
never owns the lifetime lock or adoption. Ordinary subprocesses, setsid groups,
rapid double-forks, and Playwright driver/Chromium groups stay below this
persistent subreaper even after compute exits. No engine is dispatched after
a failed or expired handshake.

The supervisor consumes buffered compute messages after compute return/exit.
At result, cancellation, timeout, API EOF/death, or a handled supervisor signal,
it starts cleanup. It repeatedly reaps and signals its current direct children
using kernel PID handles, for up to 5 seconds of TERM and 5 seconds of KILL.
Discovery continues on every iteration, including after TERM-time forks and
kernel adoption. Children cannot recycle their numeric PID before this sole
reaper reaps them; signals use pidfds and never a process-group number. The
supervisor does not infer ownership from a historical PID/PGID census.

Completion requires `waitpid(-1, WNOHANG | __WALL)` reporting ECHILD, including
clone children and zombies. The kernel's adoption rule ensures no live
ordinary descendant can remain after all children are reaped. This claim
covers processes descended from compute; it does not contain work deliberately
submitted to an external daemon, remote host, or privileged process manager.
Those adapters are unsupported. This is lifetime ownership, not a security
sandbox for untrusted executable code.

Only an explicit clean certificate followed by successful supervisor exit can
clear the marker (with directory fsync), publish a terminal job/download, or
release capacity. EOF or a dead supervisor alone never proves cleanup. A
partial/missing certificate, failed kill/adoption, uninterruptible work, or
supervisor crash retains admission capacity and running state with
`stage: termination_failed`; readiness and new admission fail. Pending work is
quarantined rather than dispatched. A still-running direct operation's files
are preserved. A result is never published from unknown cleanup.

The API owns SQLite updates and publication. Compute receives an in-memory
progress adapter. Office/HTML usable-artifact/advisory acceptance remains
unchanged from PR #8: queued/running/failed result download is 409; unavailable
completed artifact is 410. Structural readability does not certify accessibility.
Direct PDF/HTML/Office/quality/validator/markdown operations share the same
admission and slots. Parent publication retains authenticated fix/rebuild token
downloads. Active job deletion returns 409.

Primary Linux semantics: [subreaper adoption](https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html),
[wait and ECHILD](https://man7.org/linux/man-pages/man2/wait.2.html),
[PID handles](https://man7.org/linux/man-pages/man2/pidfd_open.2.html).

## Shutdown and offline recovery

Shutdown stops admission and cancels job/direct executions concurrently.
The shipped uvicorn commands allow 15 seconds of HTTP draining; supervisor
cleanup/acknowledgment has a bounded 12-second parent wait, within the 30-second
application target. systemd allows 45 seconds and Compose allows two minutes.
An unresolved shutdown raises an explicit failure, retaining locks while the
API remains alive and leaving durable markers even after its OS exit. It never
claims descendants stopped merely to meet the shutdown target.

An API crash can leave an unresolved marker even if its supervisor subsequently
cleans up successfully. **Restart must refuse this store**. It does not change
running rows to interrupted, recover queued work, or reopen capacity while
markers remain. A service-manager retry does not resolve this condition.

Offline recovery requires an operator to stop every API for this store, retain
the database/inputs/outputs and markers as one cold evidence bundle, and prove
all prior work stopped. Rebooting the original execution host while the API is
disabled provides a conservative process-lifetime reset; restoring a copied
store on another host while the original can still run does not. Archive the
unresolved directory only after that proof, recreate it empty, then explicitly
restart. No automatic marker clearing or replay is provided. Deployment owners
must approve and document their recovery procedure; this change performs none
of these operator actions.

After a proven clean restart, leftover running rows become failed/interrupted,
with inputs retained and no automatic replay. Journalled queued rows reconcile
in stored order up to active-plus-pending capacity. Excess rows and legacy rows
without attributable submission intent become `submission_quarantined`, with
inputs retained. Expired queued work never starts. Cold
backup/restore, topology, resource envelopes, and assembled-stack upgrade and
rollback proof remain LT-111/LT-112 deployment gates.

## Recoverable submission and acknowledgement loss (LT-166)

Before a job becomes eligible, the server fsyncs the staged bytes and directory
ancestry, then commits the complete operation/options/media type/deadline,
staging and final owned paths, byte count and SHA256 in the same SQLite
transaction as the job row. SQLite uses WAL with `synchronous=FULL`, which
[syncs the WAL on each commit](https://www.sqlite.org/wal.html#performance_considerations).
The job's public status remains `queued`, with stage `finalizing`; it cannot
dispatch in that phase. The private journal is not exposed in job responses.

```text
prepared + finalizing -> durable rename + directory fsyncs + validation
  -> ready + queued -> validate exact bytes/options/path -> dispatched + running
  -> terminal outcome after owned process cleanup
```

Cold recovery may finish a prepared move from either retained staging input or
the final input, using the original journal and options. It never guesses from
a filename or supplies default options. Missing/changed bytes, changed options,
unsafe paths, ambiguous copies, unknown journal phases and excess queue capacity
produce explicit quarantine. Quarantined inputs/journals are excluded from
automatic retention pruning; explicit authenticated deletion remains available.
File reconciliation is bounded to admission capacity, with excess rows
quarantined by SQLite. A dispatch claim is committed before execution; an
interrupted claimed job is not automatically replayed. Existing unresolved
process ownership prevents all reconciliation until operator lifetime proof.

A hard process exit before the intent commits can leave unsubmitted staging
bytes without a job. Those files are retained and never automatically queued.
Ordinary pre-intent errors remove staging only when SQLite proves no intent
owns it; uncertain ownership retains the input. An ordinary post-intent failure
before enqueue quarantines the input. Once ownership transfers to the worker,
response/receipt failure cannot delete or undo that work.

HTTP acknowledgement loss is ambiguous: the job may already be accepted or
running even if the caller sees an error or no response. There is no new
idempotency contract. **Do not blindly resubmit or implement an automatic POST
retry.** Correlate the known job ID, request timing, input hash and retained
options with the operator's journal evidence; when the ID receipt was lost,
an operator must establish whether work exists and its outcome before any
explicit resubmission. No automatic recovery of unjournalled legacy queued rows
is safe because their original options cannot be proved.

This adds a table to local SQLite stores; this work performs no live migration.
Capture the complete stopped database/WAL/SHM, job files and ownership evidence
as one coherent cold tree. The [stack cold-state helper](stack/cold-state.md)
preserves those bytes without a checkpoint or database mutation; a database-only
SQLite API backup does not capture the input/options/ownership bundle. Keep quarantined
inputs and staging evidence. Before rollback to an older binary, stop all APIs
and retain the cold bundle: older code does not enforce journal phases and must
not open a store containing prepared/ready submissions. Restore a proven coherent
pre-upgrade bundle only after prior processes are stopped and uncertain accepted
work is accounted for; do not delete journal/input evidence or automatically
resubmit jobs. Actual assembled backup/restore and upgrade/rollback execution
remain release gates, not actions performed by this patch.

## Verification

```sh
PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m pytest tests/unit -v
REMEDY_FULL_RUNTIME_TESTS=1 PYTHON_DOTENV_DISABLED=1 .venv/bin/python -m pytest tests/unit/test_execution_http.py tests/unit/test_supervisor_lifetime.py tests/unit/test_job_outcomes_http.py -v
```

The full runtime Linux target runs these plus forwarding and HTML contract
regressions as the application user without external networking. The suites
use synthetic fixtures/local HTTP dependencies, real spawn/store/admission,
late detached helpers, rapid orphaning, buffered returns, supervisor/API death,
lock handoff, cancellation, queue expiry, auth/rate limits and genuine Chromium
rendering. Adapter-fault cases in the outcome suite explicitly substitute
parent-local runners; they do not claim spawn coverage. macOS checks prove
refused strict admission; Linux lifetime tests skip there. Component tests do
not establish assembled-stack deployment readiness.
