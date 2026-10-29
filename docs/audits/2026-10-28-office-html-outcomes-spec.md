# Spec: Honest Office and HTML job outcomes

Prepared October 28, 2026 (Pacific), from [LT-98](https://linear.app/johnnyrobot/issue/LT-98/audit-libretexts-remedy-server-architecture-reliability-performance) and the Chief-selected first slice. Spec: [LT-102](https://linear.app/johnnyrobot/issue/LT-102/spec-honest-office-and-html-job-outcomes). Baseline: [audited main 4c6eaa0](https://github.com/johnnyrobot/libretexts-remedy-server-dev/commit/4c6eaa06818dba0742b78c61fb73dcda2d8d34ca); findings and limits are in the [archived audit](2026-10-28-remedy-server-audit.md). Planning only: implementation is held for the Chief's cross-repo audit review. The Chief selected HTTP upload/status/download plus real worker execution as the behavioral seam; no further user interview is required for this planning assignment.

## Problem Statement

A client can upload a corrupt modern Office document, receive HTTP 202, poll a job marked done, and then receive HTTP 500 when downloading its nonexistent result. A controlled failed HTML renderer produces the same false completion. An existing unit test even expects unsupported legacy Office remediation to finish done. Users cannot trust job completion or distinguish processing failure from advisory accessibility findings.

## Solution

Publish done only when the operation succeeds and produces an independently readable artifact of the promised format. Publish failed with a useful error when processing or structural output validation fails. Keep genuinely generated artifacts downloadable even when accessibility checks or optional quality audits report advisory problems. Reject unsupported legacy Office remediation before creating a job. Keep existing status names and explain result availability through documented HTTP responses.

## User Stories

1. As an Office remediation client, I want a corrupt DOCX job to fail, so that I do not promise a download that cannot exist.
2. As an Office remediation client, I want corrupt PPTX and XLSX jobs to fail consistently, so that format selection does not change completion semantics.
3. As a client of either remediation upload route, I want the same modern Office outcome, so that an alias does not hide a failure.
4. As an HTML-to-PDF client, I want a renderer's failed return value honored, so that a caught renderer error does not become success.
5. As a conversion client, I want raised processing errors to become failed jobs, so that polling always reaches a useful terminal outcome.
6. As an Office-to-HTML client, I want extraction and generation failures surfaced, so that an error page is not presented as converted content.
7. As a downloading client, I want an empty, missing, wrong-format or unreadable produced artifact rejected before done, so that success represents an actual document.
8. As a user with residual accessibility findings, I want my readable remediated file retained and downloadable, so that advisory findings do not erase useful work.
9. As a user opting into quality checks, I want quality-check unavailability recorded separately, so that it does not discard a valid output.
10. As a user of legacy DOC, PPT or XLS remediation, I want an immediate 415 with the supported formats, so that I can convert the input before retrying.
11. As a user of PDF remediation or another format operation, I want its own format policy preserved, so that the Office remediation restriction does not disable an unrelated handler.
12. As a polling client, I want queued, running and failed results to return 409, so that I can handle unavailable results without interpreting a server crash.
13. As a client with an unknown job id, I want 404, so that absence is distinct from processing failure.
14. As a client whose completed artifact was subsequently lost, I want 410, so that I can distinguish artifact loss from a processing failure.
15. As the next user sharing a worker, I want my valid job to succeed after a failed one, so that a bad input cannot poison later processing.
16. As a maintainer, I want these contracts exercised through HTTP and the real worker, so that internal success flags cannot silently diverge from public behavior.
17. As an operator, I want errors without host paths, document contents or credentials, so that useful diagnostics do not expose sensitive information.
18. As a user of generated HTML or PDF, I want downloadable bytes verified as that format, so that a file extension alone is not treated as evidence of successful conversion.

## Implementation Decisions

- Keep the current job vocabulary: queued, running, done, failed. Do not add a state or change persistent schema. A failed operation has a nonempty, bounded, client-safe error and does not publish an output location or advertise a result. Existing result media-type metadata is not itself an availability promise.
- Deepen the existing job-execution boundary to own completion decisions for modern Office remediation, modern Office-to-HTML and HTML-to-PDF. Prefer a small private validation policy here over a generic pipeline framework or another pass-through service.
- Honor explicit remediator/renderer success and failure results as well as raised exceptions. An explicit failure stays failed even when a partial file happens to exist. Success without a usable artifact also fails. Use the worker's existing error-to-failed behavior; avoid a second independent terminal-state writer.
- Validate the job-owned expected artifact, not an arbitrary returned filename. It must be a nonempty regular file, have the promised media type and pass the structural format check. Do not publish partial or mismatched output. The current per-job artifact directory remains the ownership boundary.
- DOCX/PPTX/XLSX output must open with its corresponding native parser, using the existing Office package-validation capability separately from accessibility acceptance. A ZIP signature or overall acceptance flag is insufficient.
- HTML-to-PDF output must open as a PDF with at least one page. This is structural readability, not a new PDF/UA or visual-fidelity gate.
- Modern Office-to-HTML output must be nonempty UTF-8 HTML with a document/body structure. Structural HTML validity does not assert content fidelity or accessibility conformance. Extraction and generation errors continue to propagate rather than being converted into successful HTML.
- Run structural output validation before optional advisory acceptance/quality work. Once structural validity is independently established, residual checker findings, screen-reader findings, acceptance evaluator exceptions and optional quality errors remain advisory metadata; they do not suppress the artifact.
- Generic remediation continues to accept PDF and modern Office. The Office-only remediation alias accepts modern Office. Both reject DOC/PPT/XLS with 415 before staging, persistence or enqueue; the message lists DOCX/PPTX/XLSX, and PDF where appropriate. This applies equally when quality is requested and to mixed-case suffixes.
- Use operation-specific acceptance policies. Do not globally remove legacy FileType entries or narrow shared staging defaults used by checking, extraction or Office-to-HTML. No legacy remediation adapter or format renaming is introduced.
- Result retrieval contract: unknown job 404; known queued/running/failed job 409 with a status-specific unavailable explanation; done with a readable regular nonempty artifact 200 with existing media type and attachment behavior; done whose artifact is missing, empty, nonregular or unreadable at retrieval 410 with a stable artifact-unavailable explanation. Avoid disclosing filesystem paths. A normal failed conversion must never reach the old missing-file 500 branch. Existing rows marked done are not migrated.
- The shared result-route guard performs only safe file-availability checks; do not apply Office/HTML parsers to unrelated job kinds. A parser-invalid artifact manufactured during this slice must be caught before completion. Full parser revalidation on every download and external file tampering are outside this slice.
- Document accepted formats per operation and the result responses in user-facing API documentation and OpenAPI responses. Report/download behavior beyond the result route, authentication, upload-size limits, queue ownership, PDF remediation internals and unrelated handlers retain their current scope.

## Testing Decisions

- Use one primary seam: in-process authenticated HTTP upload -> the actual app lifespan, isolated SQLite store and real JobWorker -> bounded terminal polling -> result download. Do not mock status, worker, persistence or download. Put the new tests and fixtures in the committed unit-test subtree so the existing CI actually runs them; local-only API tests are insufficient.
- Prior art includes existing Office fixture builders, the Office remediation acceptance/quality advisory tests, and LT-98's HTTP/worker synthetic reproductions. Replace the obsolete expectation that legacy remediation finishes done.
- Drive implementation with TDD one observable behavior at a time. First lock the modern Office regressions and shared download contract; include valid output and advisory preservation in the same ticket, not a later cleanup task.
- Parameterize real corrupt ZIP-prefix inputs over DOCX/PPTX/XLSX and both remediation routes. Assert upload 202, terminal failed, safe nonempty error, result 409 and no successful artifact. Then upload a genuine valid fixture on the same worker and parse its downloaded output, checking source sentinel text, slide text or cell value.
- Exercise false-success and partial-output behavior with controlled adapter outcomes: explicit failure with a leftover file; claimed success with no file, zero bytes, nonregular output, wrong format or parser-invalid bytes. These are injected fault cases, explicitly distinguished from real parser/render runs.
- Verify a genuinely readable package with advisory checker findings remains done/downloadable and keeps acceptance metadata. Independently verify acceptance and optional quality exceptions preserve a structurally valid result; no advisory exception may bypass structural validation.
- Check legacy 415 for DOC/PPT/XLS with plausible OLE signatures, both upload routes, mixed-case names and quality opt-in; assert no new job/enqueue/staged upload. Assert PDF dispatch still accepts its fixture and that checking/extraction/conversion routes retain their operation-specific dispatch policy without calling external providers.
- For modern Office-to-HTML, use real native extraction and the real converter/writer with deterministic responses at the external AI transport boundary. Assert downloadable HTML contains fixture content. Exercise corrupt inputs, extraction/generation exceptions and invalid/empty claimed output without real AI calls.
- For HTML-to-PDF, inject renderer failure to deterministically lock the original bug, plus success without a usable PDF and failure with a partial PDF. Require a real minimal inline-HTML render using installed Chromium in a supported synthetic environment, parse the resulting PDF and check its sentinel text. Label the real-render test separately and report dependency absence explicitly; a stubbed success is not renderer verification.
- For both HTML conversion kinds, follow a failing job with a valid job on the same worker. Test status/download, not just adapter return types.
- Test unknown, queued, running, failed and done result states; for done, remove only the test's own artifact or simulate unreadability and assert the documented 410. Keep filesystem fault handling deterministic across CI platforms.
- Run the repository's required CI-equivalent checks for later implementation. No new tests or product fixes are being written in this audit assignment. Existing audit red observations remain red.

## Out of Scope

- Application implementation, deployment, running a server, paid reviews, TestSprite project/test creation or paid execution. The original audit/planning phases made no commits, pushes or PRs; the subsequent docs-only archive does not authorize implementation.
- Adding LibreOffice or another legacy converter; correcting legacy checking/extraction/conversion behavior outside the remediation routes.
- PDF execution lifetime, subprocess isolation, queue admission, cancellation, shutdown, synchronous check offloading, throughput tuning or new latency budgets.
- Corpus repair, calibration/provenance changes, new quality models, broad module splitting, client repo edits, HTML resource trust policy and job submission/deletion recovery.
- New accessibility acceptance gates, PDF/UA certification, visual fidelity claims, external AI accuracy evaluation, automatic cleanup/deletion or historical job migration.

## Further Notes

Chief direction selects candidate 1 ahead of performance/refactor work, explicitly chooses legacy remediation rejection, preserves advisory output, and holds TestSprite. The spec and three child tickets are concrete review material; ready-for-agent describes specification completeness, not authorization to start implementation.

Verified operation matrix at audited main: modern Office native remediation/package checks/extraction exist; legacy suffixes are currently admitted but remediation and package checking have no native support. Legacy extraction dispatches to modern native parsers; optional missing-library OCR fallback is not an installed legacy conversion adapter or demonstrated legacy support. Legacy conversion/check behavior is a known limitation left outside this focused change. HTML rendering uses Playwright/Chromium plus PDF post-processing.

Proposed tickets: (1) [LT-103](https://linear.app/johnnyrobot/issue/LT-103/lock-modern-office-httpworker-outcomes-and-result-availability), modern Office outcomes plus HTTP/worker/download regression contracts, no blockers; (2) [LT-104](https://linear.app/johnnyrobot/issue/LT-104/reject-legacy-office-remediation-with-operation-scoped-http-415), operation-scoped legacy remediation 415, no blockers; (3) [LT-105](https://linear.app/johnnyrobot/issue/LT-105/make-office-to-html-and-html-to-pdf-outcomes-reflect-usable-artifacts), modern Office-to-HTML and HTML-to-PDF completion/validity, blocked by LT-103's result contract and validity/advisory policy. No broad prefactor is required ahead of ticket 1.

All remaining audit candidates stay ranked proposals. TestSprite prerequisites and cost remain in the audit: an approved reachable disposable synthetic backend with isolated storage and managed fake authentication, supported backend execution, bridge/live/AI access disabled for the three drafted scopes, followed by fresh usage/price inspection and explicit run authorization. The historical audit account quote was 0.5 credits/run (three individual runs estimate 1.5 credits); backend-specific charge and infrastructure cost are unconfirmed. No target is provisioned and no TestSprite verification is claimed.
