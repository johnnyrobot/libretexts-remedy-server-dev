# HTTP API and engine configuration

Start with the [supported deployment entry point](../README.md).

## Endpoints

### High-level (async jobs)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/remediate` | Upload PDF **or** modern Office (DOCX/PPTX/XLSX) → async remediation. Legacy DOC/PPT/XLS return 415. |
| `POST` | `/v1/office/remediate` | Modern Office-only variant of the above (DOCX/PPTX/XLSX). |
| `POST` | `/v1/convert/pdf-to-html` | PDF → accessible HTML (async). |
| `POST` | `/v1/convert/office-to-html` | Office → accessible HTML (async). |
| `POST` | `/v1/convert/html-to-pdf` | HTML → tagged PDF (async, via Playwright). |
| `POST` | `/v1/vision-plan/run` | **Opt-in Tier 3.** Vision-planner rescue (async). Not the default. |
| `GET` | `/v1/jobs/{id}` | Status (`queued`/`running`/`done`/`failed`), stage, progress. |
| `GET` | `/v1/jobs/{id}/result` | Download the produced file (media type depends on job kind). |
| `GET` | `/v1/jobs/{id}/report` | HTML conformance report (when available). |
| `DELETE` | `/v1/jobs/{id}` | Remove job + on-disk artifacts. |

HTTP 202 means the upload was accepted, not that conversion succeeded. Poll the
job until `done` or `failed`. Modern Office remediation, modern Office-to-HTML and HTML-to-PDF publish
`done` only after successful processing and independent structural validation
of the produced file. A readable file stays downloadable when accessibility
acceptance or optional quality checks have advisory findings/errors; see job
metadata. Structural readability does not certify accessibility or fidelity.

Result download responses:

| Status | Meaning |
|---|---|
| 200 | Completed job artifact available; response media type matches the output. |
| 404 | Job does not exist. |
| 409 | Job is queued, running or failed; no result is available. |
| 410 | Job completed, but its artifact is now missing, empty or unreadable. |

Legacy Office admission on checking, markdown extraction and Office-to-HTML
has not changed. Those paths use modern native parsers and do not provide a
supported legacy converter. Convert legacy files to DOCX/PPTX/XLSX first.

### Synchronous: PDF analysis

| Method | Path | Returns |
|---|---|---|
| `POST` | `/v1/pdf/check` | All accessibility checks (Adobe-equivalent). |
| `POST` | `/v1/pdf/tags` | Structure-tree dump. |
| `POST` | `/v1/pdf/info` | Metadata, pages, tagged/language flags, font keys. |
| `POST` | `/v1/pdf/reading-order` | XY-Cut++ reading order per page. |
| `POST` | `/v1/pdf/screen-reader` | Screen-reader simulation + issues. |
| `POST` | `/v1/pdf/alt-text/audit` | Missing / generic alt text findings. |
| `POST` | `/v1/pdf/artifacts` | Artifact marker counts per page. |
| `POST` | `/v1/pdf/fonts/check` | Per-font ToUnicode / embedding / encoding status. |

### Synchronous: PDF mutations

| Method | Path | Returns |
|---|---|---|
| `POST` | `/v1/pdf/fix` | Run `fix_and_verify` — JSON with changes + `download_token`. |
| `GET` | `/v1/pdf/fix/download/{token}` | Download the fixed PDF. |
| `POST` | `/v1/pdf/fix/{rule_id}` | Apply a single fix rule → PDF inline. |
| `POST` | `/v1/pdf/vision/alt-text` | Generate alt text for an uploaded image. |
| `POST` | `/v1/pdf/contrast/audit` | Vision-detected WCAG contrast issues. |
| `POST` | `/v1/pdf/contrast/fix` | Remediate contrast issues → PDF inline. |
| `POST` | `/v1/pdf/rebuild` | Faithful rebuild (`force_mode=preserving\|mode_a\|mode_b\|simple_font`). |
| `GET` | `/v1/pdf/rebuild/download/{token}` | Download rebuilt PDF. |
| `POST` | `/v1/pdf/redistill` | Ghostscript redistillation (optional `use_ocr=1`). |
| `POST` | `/v1/pdf/ocr` | ocrmypdf subprocess (requires `ocrmypdf` on PATH). |

### Synchronous: Office + conversions

| Method | Path | Returns |
|---|---|---|
| `POST` | `/v1/office/check` | `evaluate_office_acceptance` report (checks + screen-reader + package validity). |
| `POST` | `/v1/convert/extract-markdown` | Inline markdown extract (sync, no job). |

### Synchronous: validators

| Method | Path | Requires |
|---|---|---|
| `POST` | `/v1/validate/html` | Upload HTML → axe + pa11y + Lighthouse merged report. Needs the full runtime with pinned local HTML checker assets and sandboxed Chromium. |
| `POST` | `/v1/validate/html/wave` | Form field `url=...` → WAVE API. Needs `WAVE_API_KEY`. |
| `POST` | `/v1/validate/pdf/verapdf` | Upload PDF → veraPDF JSON. Needs `verapdf` binary + Java 17+. |
| `POST` | `/v1/validate/pdf/adobe` | Upload PDF → Adobe PDF Services report. Needs `ADOBE_CLIENT_ID` + `ADOBE_CLIENT_SECRET`. |
| `POST` | `/v1/validate/pdf/wcag` | Upload PDF → 2-tier vision WCAG verifier. Needs a vision provider. |

### Infrastructure

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness (unauthenticated). |
| `GET` | `/readyz` | Readiness: SQLite open/query, writable job directory, worker running. |
| `GET` | `/docs` | Swagger UI. |
| `GET` | `/openapi.json` | OpenAPI schema. |

---

HTML tools default to offline document resources, pinned local checkers and a non-root Chromium sandbox. Documents requiring blocked resources are incomplete; see [HTML resource policy](../deploy/html-resource-policy.md) for supported assets, native setup and the Linux container policy.

## What the engine does

Each job kind maps to a dedicated handler in `backend/app/engine_service.py`. The **default** PDF remediation (`/v1/remediate` for PDFs) runs:

1. **`fix_and_verify()`** — 48 auto-fix functions + up to 3 verify-refine cycles + optional veraPDF-driven conformance repair.
2. **`evaluate_pdf_acceptance()`** — composite gate (checker + screen reader + veraPDF + visual diff).
3. **`generate_document_report()`** — per-PDF HTML conformance report.

Vision-planner / Tier-3 agentic remediation is **not** part of this default flow. It's an opt-in tool (`/v1/vision-plan/run`) because the deterministic path is faster, cheaper, and more reliable on the corpus we've tested.

---

## Configuration

Calibration-dependent quality is unavailable until parser-readable,
attributable evidence is approved independently. The committed bootstrap corpus
does not qualify. Base remediation can retain usable artifacts with an explicit
quality advisory. See [calibration evidence](../deploy/calibration-evidence.md) for
capability status and operator requirements; no accessibility certification is
implied by a completed conversion.

All env-driven. See `.env.example` for the full list. Key knobs:

**HTTP layer** (`backend/app/config.py`):
`APP_ENV`, `APP_DOCS_ENABLED`, `APP_API_KEY`, `MAX_UPLOAD_MB`, `MAX_REQUEST_BYTES`, `JOB_STORE_PATH`, `JOB_DIR`,
`JOB_RETENTION_HOURS`, `JOB_BACKUP_DIR`, `JOB_BACKUP_KEEP_N`, `JOB_BACKUP_INTERVAL_HOURS`,
`WORKER_CONCURRENCY`, `WORKER_MAX_PENDING`, `JOB_TOTAL_TIMEOUT_SECONDS`, `CORS_ALLOW_ORIGINS`,
`CXONE_INTEGRATION_ENABLED`, `CXONE_BRIDGE_BASE_URL`, `CXONE_BRIDGE_TIMEOUT_SECONDS`,
`CXONE_HEALTH_TIMEOUT_SECONDS`, `REMEDY_REVIEWER_REQUIRED`, `REMEDY_BRIDGE_SERVICE_KEY_FILE`,
`RATE_LIMIT_DEFAULT`, `RATE_LIMIT_UPLOADS`, `RATE_LIMIT_STORAGE`.

`MAX_REQUEST_BYTES` limits the complete raw `/v1/` request, including ignored
fields and multipart overhead. It is separate from the selected-file limit
`MAX_UPLOAD_MB`. The deployment package uses 5,000,000 bytes; when unset, the
standalone total limit derives from the file budget plus 1 MiB overhead.

**Engine** (`src/project_remedy/config.py`):
- Ollama Cloud: `OLLAMA_BASE_URL` (default `https://ollama.com/v1`), `OLLAMA_API_KEY`,
  `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, `OLLAMA_ESCALATION_MODEL` — all default to
  `kimi-k2.7-code:cloud`. `APP_ENV=production` requires `OLLAMA_API_KEY` to be non-empty.
  Optional `OLLAMA_VISION_FALLBACK_MODELS` and `OLLAMA_VISION_FALLBACK_BASE_URLS`
  configure ordered vision fallbacks such as a local `gemma4:26b` model.
  The `/v1` path is used because `OllamaClient` speaks the OpenAI-compatible
  `/chat/completions` surface; new direct callers should prefer native
  `https://ollama.com/api` with `/api/chat`.
- Quality layer model separation: `QUALITY_JUDGE_MODEL` and `BEHAVIORAL_TEST_MODEL`
  must be different model families from `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, and
  `OLLAMA_ESCALATION_MODEL`. The default separated setup uses
  `QUALITY_JUDGE_MODEL=mistral-large-3:675b` and
  `BEHAVIORAL_TEST_MODEL=gemma4:31b-cloud`.
  Runtime checks reject same-family judge or behavioral models.
- Ghostscript: `GHOSTSCRIPT_ENABLED`, `GHOSTSCRIPT_PATH`
- veraPDF: `VERAPDF_PATH`
- Rebuild tier (semantic-rebuild escalation, opt-in per job via `allow_semantic_rebuild`):
  `REBUILD_ENABLED` (default `true`), `REBUILD_BACKEND=questpdf|typst` (default `questpdf`),
  `REBUILD_TYPST_TIMEOUT_S` (default `120`). Per job, `POST /v1/remediate` also accepts an
  `allow_semantic_rebuild` form field and an optional `rebuild_backend` form field that
  overrides `REBUILD_BACKEND` for that job. The Typst backend adds a compile-time PDF/UA-1
  gate (`typst compile --pdf-standard ua-1`) plus a struct-tree assertion pass — verifying the
  compiled tag tree round-trips the semantic AST — before the shared veraPDF acceptance gate.
- Adobe PDF Services: `ADOBE_CLIENT_ID` / `ADOBE_CLIENT_SECRET`
- WAVE: `WAVE_API_KEY`
- Contrast: `CONTRAST_ENABLED`, `CONTRAST_LEVEL`, `CONTRAST_DPI`
- Branding (HTML output): `BRAND_NAME`, `BRAND_PRIMARY`, `BRAND_ACCENT`, `BRAND_NEUTRAL`, `BRAND_START_URL`
- Feature flags: `FONT_MODE_A_ENABLED`, `FONT_MODE_B_ENABLED`, `SIMPLE_FONT_*`, `VISION_PLANNER_AS_FALLBACK`

See `config.example.yaml` for the equivalent YAML template.

---

## CLI

Optional dev CLI for local inspection:

```bash
remedy-pdf check   file.pdf
remedy-pdf fix     file.pdf -o fixed.pdf
remedy-pdf report  fixed.pdf --original file.pdf
remedy-pdf tags    file.pdf
remedy-pdf vision  file.pdf
# ... remedy-pdf --help
```

The API is the primary interface; the CLI is for ad-hoc debugging.

---

