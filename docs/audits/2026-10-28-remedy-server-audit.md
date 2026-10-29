# Remedy Server audit — 2026-10-28

Ticket: [LT-98](https://linear.app/johnnyrobot/issue/LT-98/audit-libretexts-remedy-server-architecture-reliability-performance). Repository: [johnnyrobot/libretexts-remedy-server-dev](https://github.com/johnnyrobot/libretexts-remedy-server-dev). Audited `main` at [4c6eaa06818dba0742b78c61fb73dcda2d8d34ca](https://github.com/johnnyrobot/libretexts-remedy-server-dev/commit/4c6eaa06818dba0742b78c61fb73dcda2d8d34ca). Audit performed October 28 Pacific / October 29 UTC, 2026. The initial tracked tree was clean. The audit and planning phases made no application changes, commits, pushes, deployments, paid reviews, or live stack calls. This subsequent documentation archive preserves the findings and proposed spec; it implements no fixes. File/line references and baseline results below describe the audited SHA.

**Final disposition:** LT-98 is Done. The Chief selected candidate 1 and held TestSprite creation/runs. [Focused spec LT-102](https://linear.app/johnnyrobot/issue/LT-102/spec-honest-office-and-html-job-outcomes) and child tickets [LT-103](https://linear.app/johnnyrobot/issue/LT-103/lock-modern-office-httpworker-outcomes-and-result-availability), [LT-104](https://linear.app/johnnyrobot/issue/LT-104/reject-legacy-office-remediation-with-operation-scoped-http-415), and [LT-105](https://linear.app/johnnyrobot/issue/LT-105/make-office-to-html-and-html-to-pdf-outcomes-reflect-usable-artifacts) were prepared in Backlog for cross-audit review. The [archived spec](2026-10-28-office-html-outcomes-spec.md) records the proposed behavior and test boundaries. This is planning only; the defects below remain unresolved.

**Recommendation: first correct job completion after failed Office remediation and HTML rendering.** This is a small, confirmed correctness slice with an HTTP reproduction. Next, deepen execution ownership so deadlines and worker limits constrain actual work. Avoid broad file splitting or a worker-concurrency increase before those defects are resolved.

## Method and scope

Read shared CLAUDE.md and all four agent documents, repo README, stack README/compose, CI, configuration and relevant code. Applied Matt Pocock `ask-matt` routing, `improve-codebase-architecture`, and `codebase-design`; one required read-only architecture exploration subagent independently inspected code. Used the `diagnosing-bugs` feedback-loop approach for reproductions; stopped at diagnosis because the audit phase authorized no fixes. Read TestSprite onboard/verify instructions and the TDD/spec/ticket skills before recommending the next flow. This is an application audit, not a paid review gate.

Scope followed the brief and recent history: scan/remediation/conversion, process/worker ownership, error isolation, corpus gates, stack reliability. Last 35 commits most often touched stack README (5), root README (5), lockfile (4), ignore policy (4), and dependency manifest (3); runtime failure paths were examined even where they were not the largest recent files. No new module interface signatures are proposed; Chief selects the candidate first.

Detailed raw evidence is retained **local-only**, under `docs/audits/2026-10-28-lt-98/` in the original audit checkout. Logs, reproduction harnesses, TestSprite drafts, HTML previews and the operational plan index are excluded from this GitHub archive and remain uncommitted. Evidence filenames below identify those local records, not downloadable repository files. The two archived Markdown documents contain the findings, baseline outcomes, limits and selected scope needed to read this record independently.

## Ranked findings

### 1. Major — failed conversion/remediation is published as done

**Impact:** clients poll success and then receive a failing download. **Confidence:** high, reproduced. **Effort:** small for modern Office/HTML outcome handling; legacy format policy needs Chief selection.

`src/project_remedy/office_remediator.py:34-50` returns `success=False` after catching errors. `backend/app/engine_service.py:299` discards the outcome and publishes `done` at `347-354`. `src/project_remedy/html_to_pdf.py:147-153` returns a failed conversion result; `engine_service.py:492-502` discards it and also publishes `done`. `backend/app/routes.py:343-347` then returns 500 for a missing result file.

Actual HTTP reproduction: upload `PK\x03\x04broken` as `broken.docx` → **202 → job done → result 500**. A subsequent real DOCX in the same worker succeeds, downloads, and retains its body. Real worker probes reproduce missing output for DOCX/PPTX/XLSX and legacy DOC. HTML uses a deliberately injected failed renderer outcome, not a real browser crash. Legacy uploads are admitted at `routes.py:49`, although `OfficeRemediator` supports modern suffixes only. `tests/unit/test_office_remediate_gate.py:55-73` explicitly expects a legacy failure to become done: passing tests preserve part of this defect.

**Deepening candidate — Strong:** concentrate produced-artifact validation and terminal-state decisions inside the job execution module. Locality: converter outcomes and job status cannot disagree in separate callers. Leverage: both Office and HTML paths gain the same invariant. Deletion test: removing the current dispatch would move handler calls into the worker; it does not currently concentrate completion policy. Deepen the existing module rather than adding another pass-through.

**Acceptance:** genuine corrupt modern Office inputs and controlled renderer failures end failed with no advertised result; failed downloads return the documented non-success status; following valid jobs work. Valid produced documents with advisory accessibility findings remain downloadable. Decide whether legacy Office is rejected at upload or receives a real conversion adapter; never silently call it successful. Test through HTTP upload/status/download and worker execution, not only internal return types.

### 2. Major — timeout frees a worker slot while PDF work continues

**Impact:** CPU/memory and file writes outlive reported failure; concurrency limits lose their meaning. **Confidence:** high, controlled reproduction. **Effort:** medium to large.

`backend/app/engine_service.py:173-203` and `255-265` use `wait_for(to_thread(...))`. The timeout cancels the await, not the running synchronous callable. `backend/app/jobs.py:304-309` catches the timeout error and takes the next job. `stop()` at `285-292` similarly cancels async tasks without terminating executor work. Queue admission is unbounded at `jobs.py:270`.

Probe: three synthetic PDF operations each sleep 250 ms; timeout 20 ms; actual worker configured concurrency 1. All jobs became failed after approximately 66 ms, with **peak active work 3 and all 3 still active after queue.join()**. The harness waits for its threads before exiting. These are injected blocking callables through the real PDF handler, not production PDF workload measurements. Default timeout values are 900/300 seconds; the defect also applies when those deadlines eventually expire.

**Deepening candidate — Strong:** execution ownership absorbs deadlines, termination, admission, shutdown and output lifetime. Two real adapters vary: synchronous PDF work and asynchronous browser work. Locality: one module owns the slot until the work stops. Leverage: handlers no longer each need a cancellation strategy. Deletion test: deleting this proposed responsibility would spread lifetime policy back across every handler.

**Acceptance:** after timeout no work remains active, no later file writes occur, and peak real execution stays within the declared limit. Establish and verify an explicit shutdown budget. Bound admitted queued work and define overload behavior. Retain durable restart recovery. Choose process isolation or cooperative cancellation only after a small design exploration; ordinary executor cancellation is insufficient.

### 3. Major — invalid corpus artifacts can pass readiness from stored results

**Impact:** a green gate demonstrates metadata consistency, not that its quality calibration can be reproduced. **Confidence:** high for artifact invalidity/readiness mismatch; human provenance is unverified. **Effort:** medium, plus valid specialist corpus preparation.

The earlier advisory failure is reproduced offline: **0 metrics, 50 skipped audits, exit 1**, with the same `unable to find trailer dictionary while recovering damaged file`, `File is not a zip file`, and PPTX package errors preserved in `calibration-advisory.json`. All 50 paths exist and match recorded source hashes; all 30 PDFs are at most 42 bytes without a PDF EOF marker, and all 20 Office artifacts are at most 44 bytes and are not ZIP packages. Representative committed blob sizes verified with `git cat-file -s HEAD:<path>` are 42 and 44 bytes. This rules out missing files and hash drift; the synthetic invalid-file loop reproduces the same parser failures independently of the corpus.

The workflow's advisory path omits `--judge-results` (`.github/workflows/ci.yml:158-164`), so `tools/calibrate_judges.py:1052-1061` runs real audits. Enforcement supplies stored judge results (`ci.yml:182-187`) and passes: **27 metrics, calibration_ready=true**. Coverage, snapshot and stored behavioral readiness also pass. `tools/annotate_corpus.py:968-980` checks existence/hashes without requiring parser validity. `annotate_corpus.py:631-634` stamps human-specialist/human-verified provenance into built records; the inspected annotation names `automated_bootstrap`. That is not evidence a human actually reviewed it. `backend/app/quality_calibration.py:121-126` accepts threshold/sample records, not a fresh corpus execution.

**Deepening candidate — Strong:** concentrate corpus validity and provenance behind one readiness module before interpreting calibration. Locality: one definition of usable evidence. Leverage: annotation, snapshot, behavioral and calibration callers share that precondition. Deletion test: do not introduce a new shallow wrapper around the current metadata checks; move actual parser validity and evidence classification into the shared decision.

**Acceptance:** invalid PDF/OOXML bytes fail readiness even when their hashes and stored scores match. Synthetic scaffolding is distinguished from specialist calibration; no implicit human verification. A small valid synthetic corpus runs offline end to end; production readiness requires separately reviewed valid evidence. Do not regenerate or relabel the existing corpus during this audit.

### 4. Major reliability — synchronous document checks stall unrelated requests

**Impact:** health/status latency rises with document work on the single process. **Confidence:** high for mechanism and measured interference; production p95 unknown. **Effort:** medium; combine with candidate 2.

Async PDF check directly calls `checker.run_all()` (`backend/app/pdf_routes.py:77-83`); async Office check directly calls `evaluate_office_acceptance()` (`office_routes.py:93-99`). Office remediation also parses/saves synchronously inside async methods (`office_remediator.py:63`, called at `engine_service.py:299`).

Actual in-process HTTP run: timer plus `/healthz` delay was **1.99 ms idle versus 431.21 ms during one synthetic 100-page PDF check**. This measures event-loop interference, not network latency or a load-test percentile. The Docker and systemd commands intentionally run one HTTP process; adding HTTP processes would require rethinking shared queue ownership, not just changing a number.

**Acceptance:** at an agreed bounded workload, health and status requests remain responsive while check/remediation runs; measure p95/max against a selected latency budget. Offloading must preserve candidate 2's actual execution limit, cancellation and shutdown requirements. No claim that increasing worker concurrency alone fixes this.

### 5. Moderate — job lifecycle ordering leaks into callers

**Impact:** interrupted submission or deletion during execution can leave missing inputs, orphaned work or untracked output. **Confidence:** high statically; crash/delete fault injection not run. **Effort:** medium.

`backend/app/routes.py:120-130` separately creates a queued row, renames input, updates row, and enqueues. A crash after rename/before update leaves a queued row pointing at the old path; startup requeues it (`main.py:77-79`). DELETE removes running rows/files without cancellation (`routes.py:383-391`).

**Deepening candidate — Worth exploring:** concentrate recoverable submission and deletion with job/artifact ownership. The current helper's deletion would move ordering details into multiple callers, so keep its useful concentration and deepen it. Acceptance: fault injection at each step recovers or explicitly fails the job without losing the real input; running deletion either refuses or cancels and waits before removing artifacts.

### 6. Major candidate, static only — HTML resource trust policy is implicit

**Impact:** uploaded HTML can request loopback/internal resources from the renderer. **Confidence:** high that no policy is set here; exploit and deployment containment untested. **Effort:** medium; resource policy requires Chief choice.

`backend/app/routes.py:249-280` accepts uploaded HTML; `src/project_remedy/html_to_pdf.py:117-120` creates a default context and sets content without resource interception or JavaScript restrictions. The HTML validator similarly navigates uploaded files and injects remote axe (`validator.py:478-487`). No live/internal target was probed. This is not evidence that any live deployment was compromised.

**Deepening candidate — Worth exploring:** rendering owns a declared resource policy, not separate route guards. Acceptance: a synthetic loopback listener receives no request from forbidden uploaded resources; allowed embedded assets still render; blocked resources yield explicit outcomes. Chief selects offline-only versus explicitly permitted resources before implementation.

Lower priority: duplicate `validator.py:985-997,1096-1112` veraPDF helper returns pass on missing binary, timeout or invalid XML and does not kill on timeout. No current shipped caller was found. Active PDF acceptance uses a different implementation with explicit timeout/error results (`pdf_acceptance.py:891-912`); this finding is not a claim that active PDF acceptance uses the unused helper.

## Baseline evidence and limits

Environment: macOS 26.6.2 arm64, Python 3.13.7, existing project virtualenv; synthetic files only for runtime probes. Probe clocks use `perf_counter`. Dependency tools may contact their package/advisory services; no document data was sent. Product probes used no live services, real keys, learner data or private libraries. No application server was exposed; HTTP probes used in-process ASGI transport with isolated temporary storage.

| Check / command | Actual result |
|---|---|
| [Audit-time main CI run 40793209473](https://github.com/johnnyrobot/libretexts-remedy-server-dev/actions/runs/40793209473) at audited SHA | All 5 jobs passed: compile/scrub, unit tests, quality, pip-audit, Docker smoke |
| `uv sync --extra dev --frozen` | Passed; checked 63 packages in 12 ms |
| `.venv/bin/python -m compileall -q backend src tools` | Passed |
| Workflow vendor scrub and `git diff --check` | Passed |
| `.venv/bin/python -m pytest tests/unit -q` | 219 passed, 7 warnings, 12.10 s; full log retained |
| `uv build --wheel` (temporary output directory) | Passed; wheel built; not installed/deployed |
| Workflow frozen export + `uvx pip-audit` against the frozen exported requirements | Exit 0, no known vulnerabilities; hash/dependency warnings preserved in log |
| Annotation schema / coverage / snapshot / stored behavioral / stored-result calibration | Passed their current gates; validity limitation above |
| `reproduce.py` | Completed observations; `reproduce.py --expect-fixed` intentionally exits 1 with all six current invariant violations |
| `http_probe.py` | Health/ready 200, missing key 401, invalid magic 415; false done reproduced, later valid DOCX succeeds |
| `calibration_probe.py` | Offline advisory path exits 1, no metrics, all 50 audits skipped; exact output retained |

Exact red assertion:

```text
AssertionError: office-docx: done without output; office-pptx: done without output; office-xlsx: done without output; office-doc: done without output; html: done without output; pdf: timed-out work exceeds worker concurrency
```

Commands for all quality checks mirror `.github/workflows/ci.yml`, using a temporary experiment database to preserve existing state. The offline advisory harness additionally supplies default configuration and refuses network connects. CI contains no lint/typecheck job and the manifest configures neither; no lint/typecheck success is claimed. Local Docker build was not run; remote smoke builds **runtime-slim**, not the full Chromium stack (`ci.yml:271`). Full HTML stack, native binaries, Python 3.11/3.12 compatibility and live bridge/scanner behavior remain unverified.

| Synthetic measurement (3 repeats, same process) | Median / maximum |
|---|---|
| PDF checker, 1 page, 1,365 bytes | 0.1117 / 0.1540 s |
| PDF checker, 10 pages, 5,498 bytes | 0.3185 / 0.3191 s |
| PDF checker, 100 pages, 47,239 bytes | 0.3736 / 0.3805 s |
| Office acceptance, 10 paragraphs, 36,627 bytes | 0.0121 / 0.0148 s |
| Office acceptance, 1,000 paragraphs, 39,369 bytes | 0.4680 / 0.4738 s |

These small fixtures measure baseline and event-loop risk, not scaling guarantees, representative accessibility accuracy, remediation quality, or before/after performance. They justify measuring execution isolation before pursuing algorithmic optimizations.

## Historical TestSprite result and remaining prerequisites

At audit time, CLI 0.15.0 authenticated to Johnny's Starter workspace. The read-only account quote was 0.5 credits/run, with 491.8 credits remaining before and after inspection. The project list returned five projects, none Remedy, and no local Remedy project configuration existed. No project/test/environment was created, no plan generated, no tunnel opened and no run dispatched. Actual spend was zero; test/run/dashboard IDs and a TestSprite verification verdict are **not applicable**. An unscoped test-list attempt exited 5 because a project was required; that was not a run or product verdict.

The backend runner could not reach this computer's loopback; the inspected CLI supported local execution only for frontend tests. This was a backend-target blocker, not a missing credential. No frontend/mock or unrelated target was substituted.

Three authored, unregistered backend drafts remain local-only: auth/readiness, valid DOCX roundtrip, and corrupt DOCX failure/result unavailability. Synthetic package construction/remediation and draft syntax were checked locally, but the drafts were not executed by TestSprite. The failure scope is expected red at the audited SHA and does not yet exercise subsequent valid-job recovery; that recovery belongs to the proposed HTTP/worker tickets.

Creation/runs remain held pending a separately approved reachable disposable synthetic backend, or supported backend-local execution. Target ownership/SHA, isolated storage, managed fake authentication, synthetic public fixtures and exclusion of bridge/live/real AI access remain prerequisites. Provisioning and exposure are separate decisions. Fresh usage and backend-specific pricing must precede any separately authorized execution. The historical quote estimated **1.5 credits** for three individual runs; actual backend-specific billing and infrastructure cost remain unconfirmed. The earlier 20-credit ceiling does not lift this hold. Operational setup and execution instructions remain local-only.

## Follow-up proposals for Chief selection

At the initial audit search only LT-98 existed with this repo label; no duplicate work was found. The Chief-selected first slice now has spec LT-102 and three focused child tickets; no other candidates were ticketed.

1. **First slice: honest Office/HTML job outcomes.** No blocker; candidate 1 acceptance above. The selected seam is HTTP upload/status/result with real worker execution; proposed implementation uses TDD one vertical behavior at a time. Preserve successful output with advisory warnings.
2. **Execution lifetime and responsiveness.** Candidate 2 plus measured candidate 4; agree deadline/overload/shutdown budgets and choose the execution adapter design. Use a focused spec and tracer-bullet tickets if it spans sessions; keep cancellation behavior verifiable through the same execution seam.
3. **Corpus readiness means valid, attributable evidence.** Independent of slice 1; do not treat invalid scaffolding as a calibrated corpus. Chief decides the reviewed corpus source and provenance policy.
4. **Resource policy and lifecycle recovery.** Review candidates 5/6 after the confirmed correctness slice; do safe fixture-only fault injection before escalating static findings.

Cross-repo dependencies: first slice needs no teammate edits; bridge/scanner/Conductor clients may observe more honest failed states, so retain status vocabulary and error/result contracts. Full HTML-stack validation needs the actual full runtime and bridge/scanner fixture orchestration; no other repo was edited. The stack's existing guardrails, loopback ports and production configuration validation should be retained. Later code/runbook PRs require the full shared review gate; zero paid reviews were used here.

**Chief disposition:** candidate 1 selected; reject unsupported legacy remediation formats with 415 while preserving unrelated operation policies. Spec LT-102 and tickets LT-103/LT-104/LT-105 are prepared for Chief review, not implemented. TestSprite project/test creation and runs stay on hold until an approved reachable synthetic backend exists. No provisioning, server exposure or tunnel is part of this assignment. No further user decision is requested.
