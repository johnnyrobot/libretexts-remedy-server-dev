# PRD: Quality Layer Extension for Remedy Server

> Companion document to the existing repo at `projectremedyai/remedy-server`.
> This is an **additive** spec — it extends the existing system, it does not replace it.

---

## 1. Context: What We Already Have

Remedy Server already implements a substantial portion of a document remediation system. Before specifying what to add, we name what's already in place so the agent doesn't rebuild it:

**Compliance layer (mature):**
- `src/project_remedy/pdf_checker.py` — 34 rule-based accessibility checks + 9 screen-reader checks
- `src/project_remedy/pdf_acceptance.py` — composite acceptance gate (`PDFAcceptanceResult`)
- `src/project_remedy/tag_tree_reader.py` — tag-tree-based screen-reader simulation
- `src/project_remedy/pdf_wcag_verifier.py` — 2-tier vision WCAG verifier (Triage + Focused)
- veraPDF + Adobe PDF Services integration via `validate_routes.py`
- `src/project_remedy/compliance_report.py` — per-document HTML report with WCAG 2.1 AA mapping

**Remediation layer (mature):**
- `src/project_remedy/pdf_fixer.py` — `fix_and_verify` with 48 auto-fix functions and up to 3 verify-refine cycles
- `src/project_remedy/faithful_rebuild/` — Mode A / Mode B / simple-font rebuilds
- `src/project_remedy/contrast/` — color-contrast detection + remediation
- `src/project_remedy/vision.py` — vision-based alt text + chart recreation
- `src/project_remedy/ocr_escalation.py` — OCR triage
- `src/project_remedy/office_remediator.py` + `office_acceptance.py` — DOCX/PPTX/XLSX remediation

**Agentic Tier-3 (mature, PDF only):**
- `src/project_remedy/vision_planner/` — Grounder → Planner → Executor
- `experiment_store.py` — SQLite-backed experiment tracking with harness variants
- `proposer.py` — failure-driven proposal generation (currently keyed on veraPDF rule IDs)
- `scorer.py` — Pareto-frontier scoring (currently aggregate-only)
- `evolution.py` — propose / evaluate / promote / retire loop

**Behavioral signals already in use:**
- Visual diff (page-level pixel diff against original) — visual fidelity proxy
- Text similarity (Jaccard, rebuild mode only) — content preservation proxy

**What this means for the agent:** the compliance and remediation layers don't need rebuilding. The work is to add a **quality layer** on top, addressing the specific gaps below — and to make the existing evolution loop *dimension-aware* and extend the quality layer to **Office formats**.

---

## 2. The Gap

The system is strong at **structural compliance** — does the PDF have tags, do images have alt text, are headings nested, does veraPDF pass — and it iterates well to convergence on those signals. What it lacks is the **quality layer**: signals that distinguish "passes the checker" from "actually works for a screen reader user." It also can't currently propose harness variants based on *which quality dimension* is weak, only based on which compliance violation is firing.

| Gap | Symptom | What to add |
|---|---|---|
| No narrow LLM judges for quality | `pdf_wcag_verifier` checks compliance, not "is this alt text useful in context" | Quality judge ensemble (Section 5) |
| No behavioral proxies beyond text-similarity and visual-diff | Can't tell if reading order is coherent, or if alt text actually substitutes for the image | Behavioral proxy module (Section 6) |
| Aggregate-only metrics | `scorer.py` reports conformance_rate, no per-dimension visibility | Per-dimension metrics extension (Section 8) |
| Calibration contamination | Everything runs on `kimi-k2.6:cloud`; judges would judge themselves | Different model family for judges (Section 9) |
| No annotated reference corpus | `tools/remediate_pdf_corpus.py` produces pass/fail, not per-dimension gold annotations | Annotated corpus extension (Section 7) |
| No human-in-the-loop calibration | Evolution loop is fully automated; specialist verdicts not captured | Calibration sampling loop (Section 10) |
| Evolution is compliance-driven only | `proposer.py` keys on veraPDF rule IDs; can't see "passes compliance, fails quality" | Dimension-aware evolution (Section 17) |
| Quality layer is PDF-only | Office (`office_remediator.py`) has no quality judges or behavioral proxies | Office quality layer (Section 18) |
| Thin test coverage | Only `test_smoke.py` ships in the repo dump | Module-level test buildout (Section 11) |

---

## 3. Goals and Non-Goals

**In scope:**
- A `quality_judges/` module with format-namespaced narrow judges (PDF + DOCX + PPTX + XLSX)
- A `behavioral_proxies/` module with format-namespaced behavioral tests
- Reference corpus annotations covering both PDF and Office, with a JSON-schema'd annotation format and a starter set of 50–80 documents (~30 PDF + ~20 Office) annotated by accessibility specialists
- Per-dimension metric extensions to `scorer.py`, `experiment_store.py`, and `PDFAcceptanceResult` / Office acceptance equivalents (additive, backward-compatible)
- A calibration loop using the existing `experiment_store.py` to track judge-human agreement
- A model-selection mechanism that prevents calibration contamination
- **Dimension-aware evolution**: extension to `proposer.py` so harness variants are proposed based on which quality dimension is weak in which document class, not just which compliance violation is firing
- **Office quality layer**: judges + behavioral proxies + corpus annotations + endpoints for DOCX/PPTX/XLSX
- Hardened test coverage: per-module unit tests + corpus-based integration tests
- New endpoints: `/v1/quality/audit/pdf`, `/v1/quality/audit/office`, calibration and review queue endpoints

**Out of scope:**
- Replacing or rewriting any existing module
- Changing the default `/v1/remediate` or `/v1/office/remediate` behavior (new layer is opt-in)
- Building an Office equivalent of `vision_planner/` (Office remediator stays deterministic in v1; its evolution loop is a future phase)
- Adding new document formats beyond PDF + DOCX/PPTX/XLSX
- Real-time UI / interactive editor
- Operating live screen reader user testing (we add hooks; we don't run it)

---

## 4. Architectural Integration Map

Where each new piece plugs in. Format-namespaced from the start so Phase H is purely additive:

```
src/project_remedy/
├── quality_judges/                ← NEW
│   ├── __init__.py
│   ├── shared/
│   │   ├── base.py                ← Judge protocol, model_separation check, common types
│   │   ├── ensemble.py            ← Format-agnostic aggregation
│   │   └── rubrics/               ← Shared rubric primitives where dimensions translate
│   ├── pdf/                       ← Phase C
│   │   ├── alt_text_judge.py
│   │   ├── reading_order_judge.py
│   │   ├── heading_semantics_judge.py
│   │   ├── table_structure_judge.py
│   │   ├── link_text_judge.py
│   │   ├── decorative_judge.py
│   │   ├── complex_content_judge.py
│   │   └── prompts/               ← Versioned prompt files
│   └── office/                    ← Phase H
│       ├── docx/
│       │   ├── alt_text_judge.py
│       │   ├── heading_semantics_judge.py
│       │   ├── table_structure_judge.py
│       │   ├── link_text_judge.py
│       │   ├── decorative_judge.py
│       │   └── prompts/
│       ├── pptx/
│       │   ├── alt_text_judge.py
│       │   ├── slide_reading_order_judge.py
│       │   ├── slide_title_judge.py        ← PPTX equivalent of heading semantics
│       │   ├── decorative_judge.py
│       │   └── prompts/
│       └── xlsx/
│           ├── alt_text_judge.py            ← charts and embedded images
│           ├── table_structure_judge.py     ← Excel Tables, header rows
│           ├── sheet_organization_judge.py  ← tab names, sheet purpose
│           └── prompts/
│
├── behavioral_proxies/            ← NEW
│   ├── __init__.py
│   ├── shared/
│   │   ├── base.py                ← BehavioralTest protocol
│   │   └── question_generator.py  ← Comprehension-question generation utilities
│   ├── pdf/                       ← Phase B
│   │   ├── reading_order_comprehension.py
│   │   ├── alt_text_substitution.py
│   │   ├── heading_navigation.py
│   │   ├── table_cell_lookup.py
│   │   ├── decorative_skip_test.py
│   │   └── transcript_analyzer.py
│   └── office/                    ← Phase H
│       ├── docx/
│       │   ├── alt_text_substitution.py
│       │   ├── heading_navigation.py
│       │   └── table_cell_lookup.py
│       ├── pptx/
│       │   ├── alt_text_substitution.py
│       │   ├── slide_reading_order_comprehension.py  ← per-slide
│       │   └── slide_title_navigation.py
│       └── xlsx/
│           ├── alt_text_substitution.py
│           ├── table_cell_lookup.py
│           └── sheet_navigation.py
│
├── pdf_acceptance.py              ← EXTEND (add QualityResult field, backward-compatible)
├── office_acceptance.py           ← EXTEND (same)
├── compliance_report.py           ← EXTEND (render per-format quality dimensions)
└── vision_planner/
    ├── scorer.py                  ← EXTEND (per-dimension metric methods)
    ├── experiment_store.py        ← EXTEND (judge-human agreement table + dimension scores)
    └── proposer.py                ← EXTEND (dimension-aware strategy generators) ← Phase G

backend/app/
├── quality_routes.py              ← NEW (/v1/quality/audit/{pdf,office}, calibration, review)
└── routes.py                      ← UNCHANGED (default /v1/remediate flow preserved)

tools/
├── remediate_pdf_corpus.py        ← UNCHANGED
├── annotate_corpus.py             ← NEW (specialist annotation CLI, format-aware)
├── corpus_annotations/            ← NEW (annotated reference set, version-controlled)
│   ├── schema.json                ← Format-aware schema (pdf + docx + pptx + xlsx)
│   ├── manifest.jsonl
│   └── annotations/
│       ├── pdf/{doc_id}.json
│       ├── docx/{doc_id}.json
│       ├── pptx/{doc_id}.json
│       └── xlsx/{doc_id}.json
└── calibrate_judges.py            ← NEW (run judges against annotations, compute κ per format×dimension)

tests/
├── test_smoke.py                  ← UNCHANGED
├── quality_judges/
│   ├── pdf/
│   └── office/{docx,pptx,xlsx}/
├── behavioral_proxies/
│   ├── pdf/
│   └── office/{docx,pptx,xlsx}/
└── corpus/
    ├── test_pdf_corpus_integration.py
    └── test_office_corpus_integration.py
```

**Backward-compatibility rule:** every extension is additive. Existing endpoints, dataclass fields, and function signatures keep working. Clients that don't care about quality results never see them.

---

## 5. Quality Dimensions and Judges

Each quality dimension has its own narrow judge with a structured rubric. **No "is this good overall" judges.**

### 5.1 Per-format dimension applicability

Not every dimension applies to every format. The matrix:

| Dimension | PDF | DOCX | PPTX | XLSX |
|---|---|---|---|---|
| Alt text quality | ✓ | ✓ | ✓ | ✓ (charts/images) |
| Reading order coherence | ✓ | partial (mostly linear) | ✓ (per-slide) | n/a |
| Heading semantic correctness | ✓ | ✓ (Word styles) | ✓ (slide titles) | n/a |
| Table structure | ✓ | ✓ | ✓ (table shapes) | ✓ (Excel Tables) |
| Link text descriptiveness | ✓ | ✓ | ✓ | ✓ |
| Decorative classification | ✓ | ✓ | ✓ (decorative flag) | sparse |
| Complex content description | ✓ | ✓ | ✓ | ✓ (charts) |
| Sheet organization | n/a | n/a | n/a | ✓ (tab names, purpose) |
| Slide title quality | n/a | n/a | ✓ | n/a |

PPTX adds slide-title-quality as a distinct dimension; XLSX adds sheet-organization. Otherwise the framework is shared.

### 5.2 Judge design rules (non-negotiable)

- Each judge takes one input artifact and one rubric, returns a structured per-criterion score (1–5 or yes/no, not free-form opinion)
- Judges support pairwise comparison mode (`compare(A, B) → A_better | B_better | tied`) wherever reference annotations include "better/worse" pairs
- Multiple independent judges per dimension via different prompts; ensemble aggregates and surfaces variance
- Judge prompts are version-controlled files in `quality_judges/{format}/prompts/`, not strings in code
- Each judge has an explicit `model_family` config that **must differ** from the production remediation model (Section 9)
- Format-specific judges share rubric definitions where dimensions translate (e.g., "informativeness" applies to alt text in any format)

### 5.3 Output schema

```python
@dataclass
class QualityDimensionScore:
    dimension: str                     # "alt_text", "reading_order", etc.
    format: str                        # "pdf" | "docx" | "pptx" | "xlsx"
    score: float                       # 0.0–1.0, mean across judges
    variance: float                    # surface inter-judge disagreement
    per_criterion: dict[str, float]    # rubric breakdown
    judge_versions: list[str]          # which prompt versions ran
    sample_findings: list[dict]        # representative issues
    confidence: float                  # judge-reported confidence


@dataclass
class QualityResult:
    format: str
    dimensions: dict[str, QualityDimensionScore]
    behavioral: dict[str, BehavioralTestResult]
    overall_pass: bool                 # all applicable dimensions exceed thresholds
    failing_dimensions: list[str]
```

Both `PDFAcceptanceResult` and the Office acceptance result get a new optional `quality_result: QualityResult | None = None` field. Existing consumers ignore it; new consumers read it.

---

## 6. Behavioral Proxy Tests

Functional tests measuring information preservation. They are the system's most trustworthy signals and are preferred over judges whenever they apply.

### 6.1 Reading Order Comprehension Test (PDF, PPTX-per-slide)
- **Input:** serialized reading order
- **Method:** generate N comprehension questions from the original visually-laid-out document; ask an independent LLM to answer them given only the serialized version; compare to baseline (LLM answering with the visual version)
- **Pass:** ≥ 90% answer accuracy retention
- **PPTX variant:** runs per-slide; aggregate is mean across slides

### 6.2 Alt Text Image-Substitution Test (all formats)
- **Input:** document with images replaced by their proposed alt text
- **Method:** generate questions whose answers require information from the images; ask LLM to answer using only the substituted text; compare to baseline
- **Pass:** ≥ 80% answer accuracy retention

### 6.3 Heading / Title Navigation Test (PDF, DOCX, PPTX)
- **Input:** heading outline only (PDF/DOCX) or slide title list (PPTX)
- **Method:** "where in the document would you find information about X" for X drawn from body content
- **Pass:** ≥ 85% navigation accuracy

### 6.4 Table Cell Lookup Test (PDF, DOCX, PPTX, XLSX)
- **Input:** screen-reader-style table serialization
- **Method:** "what is the value at row Y, column Z" for randomly sampled cells
- **Pass:** ≥ 95% lookup accuracy

### 6.5 Decorative Skip Test (PDF, DOCX, PPTX)
- **Input:** two transcripts — one including decorative-tagged images, one excluding them
- **Method:** compare information content via LLM-judged equivalence
- **Pass:** transcripts judged information-equivalent

### 6.6 Sheet Navigation Test (XLSX)
- **Input:** list of sheet tabs with their purposes
- **Method:** "which sheet would contain information about X" for X drawn from sheet contents
- **Pass:** ≥ 80% navigation accuracy

### 6.7 Screen Reader Transcript Analysis (PDF primary; Office best-effort)
- **Input:** the document run through actual TTS where available (NVDA via subprocess for PDF; PowerPoint/Word/Excel screen-reader simulations are weaker)
- **Output:** structured findings list, not pass/fail

**Integration:** behavioral tests wire into `pdf_acceptance.py` and `office_acceptance.py` as new optional layers, runnable via flag. Existing acceptance gates stay intact.

---

## 7. Reference Corpus with Annotations

### 7.1 Annotation schema
JSON Schema lives at `tools/corpus_annotations/schema.json` and is **format-aware**:

```json
{
  "doc_id": "...",
  "format": "pdf|docx|pptx|xlsx",
  "source_path": "...",
  "document_class": "form|paper|slide_deck|marketing|data_report|spreadsheet_workbook|...",
  "edge_case_flags": ["complex_table", "math_equations", "multi_column", "..."],
  "gold_remediation_path": "...",
  "annotator": "specialist_id",
  "annotated_at": "ISO timestamp",
  "annotation_version": "1.0",
  "applicable_dimensions": ["alt_text", "heading_semantics", "..."],
  "dimensions": {
    "alt_text": {
      "score": 0.92,
      "per_image": [
        {"image_id": "...", "gold_alt_text": "...", "notes": "..."}
      ]
    },
    "reading_order": {"score": 0.88, "notes": "..."}
  },
  "pairwise_comparisons": [
    {"a_path": "...", "b_path": "...", "winner": "a", "dimension": "alt_text", "rationale": "..."}
  ],
  "format_specific": {
    "pptx": {"per_slide": {...}},
    "xlsx": {"per_sheet": {...}}
  }
}
```

### 7.2 Initial corpus
Target 50–80 documents in v1, stratified across:
- **PDF (30+):** forms, papers, slide-deck PDFs, marketing collateral, data reports
- **DOCX (~10):** memos, reports, technical docs with tables and figures
- **PPTX (~10):** decks with mixed slide types — title, content, table, chart, image-heavy
- **XLSX (~5):** workbooks with multi-sheet structures, embedded charts, data tables
- Edge cases across all formats: complex tables, math, multi-column, charts as images, scanned, long-form

### 7.3 Annotation workflow
- `tools/annotate_corpus.py` is a format-aware CLI that walks an annotator through a document, surfacing each applicable dimension and capturing structured judgments
- Annotations are versioned as immutable per-release snapshots (e.g., `corpus_annotations/v1/`)
- Schema validation runs in CI

---

## 8. Per-Dimension Metrics Extension

`vision_planner/scorer.py` currently produces `ScoringResult` with aggregate fields. Extend (not replace) to add:

```python
@dataclass
class DimensionMetrics:
    dimension: str
    format: str                       # "pdf" | "docx" | "pptx" | "xlsx"
    quality_score: float              # judge ensemble mean
    behavioral_pass_rate: float       # if behavioral test applies
    judge_human_agreement: float      # cohen's kappa vs annotations
    sample_size: int
    regression_from_baseline: float   # negative = regression


@dataclass
class ScoringResultV2(ScoringResult):
    per_dimension: dict[str, DimensionMetrics] = field(default_factory=dict)
    document_class_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
    format_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)
```

`HarnessScorer.score_variant()` returns `ScoringResultV2` going forward. Per-dimension metrics are primary; aggregate metrics are kept for backward compatibility but never surface as primary KPIs.

### 8.1 Per-dimension experiment tracking

`ExperimentRecord` is extended with quality dimension scores so the proposer (Phase G) can analyze them:

```python
@dataclass
class ExperimentRecord:
    # ... existing fields unchanged ...
    quality_dimensions: dict[str, float] = field(default_factory=dict)  # dimension → score
    behavioral_results: dict[str, bool] = field(default_factory=dict)   # test_name → passed
```

`experiment_store.py` schema additions:

```sql
-- New column on experiment_records (JSON for flexibility)
ALTER TABLE experiment_records ADD COLUMN quality_dimensions_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE experiment_records ADD COLUMN behavioral_results_json TEXT NOT NULL DEFAULT '{}';

-- New table for judge-human agreement tracking
CREATE TABLE IF NOT EXISTS judge_calibration (
    judge_id           TEXT NOT NULL,
    judge_version      TEXT NOT NULL,
    format             TEXT NOT NULL,
    dimension          TEXT NOT NULL,
    cohens_kappa       REAL NOT NULL,
    sample_size        INTEGER NOT NULL,
    measured_at        TEXT NOT NULL,
    PRIMARY KEY (judge_id, judge_version, format, dimension, measured_at)
);
```

---

## 9. Calibration Contamination Mitigation

The current system runs almost entirely on Ollama Cloud `kimi-k2.6:cloud`. If quality judges also run on the same model, the system will judge itself favorably and produce inflated metrics. This must be prevented structurally:

**Hard rules:**
1. **Judge models must come from a different model family** than `OLLAMA_MODEL` / `OLLAMA_VISION_MODEL` / `OLLAMA_ESCALATION_MODEL`. New config keys: `QUALITY_JUDGE_BACKEND`, `QUALITY_JUDGE_MODEL`. Defaults must not be `kimi-k2.6:cloud`.
2. **Gold-standard remediations in the corpus must be human-annotated**, not generated by any model used in production. If a model is used to seed candidate remediations for human review, that model is recorded in the annotation metadata for transparency, but the human verdict — not the model output — is the gold.
3. **Behavioral test LLMs** (the ones answering comprehension questions) should ideally be a third independent model. At minimum, they must differ from the model that generated the artifact under test.
4. **Same-model rejection at runtime**: `quality_judges/shared/base.py` checks the configured judge model against the production model and refuses to instantiate if they match. This is a hard error, not a warning.

**Pragmatic note:** the project is Ollama-native; that's fine. The constraint is just that the judge model can't be the production model. Options: a different Ollama-hosted model, an OpenAI-compatible endpoint, an Anthropic API endpoint, or local models via Ollama. The `OllamaClient` is already abstracted enough to support multiple endpoints — extend that abstraction rather than building parallel client code.

---

## 10. Calibration Sampling Loop (Human-in-the-Loop)

The existing evolution loop is fully automated. Add a parallel calibration pathway:

1. **Stratified sampling.** Daily/weekly job samples documents from production traffic (across all formats), prioritizing: high inter-judge variance, low behavioral-proxy confidence, and a baseline random stratum.
2. **Specialist queue.** Sampled documents land in a queue exposed via `/v1/quality/review/queue`. Specialists can claim, annotate, and submit verdicts. Verdicts are written to `corpus_annotations/v{n}/` and to the `judge_calibration` table.
3. **Drift alerting.** When `cohens_kappa` for any judge × dimension × format drops below threshold over a rolling window, the system emits a structured alert. Don't auto-retrain; surface for human action.
4. **Corpus growth.** Specialist verdicts on novel document classes or edge cases automatically expand the reference corpus.

Implementation note: keep the queue minimal in v1 — JSON-backed, no UI. The annotation CLI from §7.3 is the interface. UI comes later.

---

## 11. Test Coverage Hardening

The repo currently ships `tests/test_smoke.py` only. Test coverage must materially improve before any of this layer is trusted.

**Required test additions:**
- `tests/quality_judges/{pdf,office/docx,office/pptx,office/xlsx}/test_<dimension>_judge.py`
- `tests/behavioral_proxies/{pdf,office/docx,office/pptx,office/xlsx}/test_<test_name>.py`
- `tests/corpus/test_{pdf,office}_corpus_integration.py`
- `tests/api/test_quality_routes.py`
- `tests/vision_planner/test_proposer_dimension_aware.py` (Phase G)
- Backward-compatibility regression: full `/v1/remediate` and `/v1/office/remediate` flows produce byte-identical output on the corpus when `quality=false` (default)

**CI extension:** new `quality-checks` job that runs the calibration suite against the bundled annotation set on every PR, per format.

---

## 12. New Endpoints

Additive only. Existing endpoints unchanged.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/quality/audit/pdf` | Upload PDF → run PDF judges + behavioral proxies → return `QualityResult` |
| `POST` | `/v1/quality/audit/office` | Upload Office doc → run format-appropriate judges + proxies → return `QualityResult` |
| `POST` | `/v1/remediate?quality=true` | Existing remediation, with quality results attached to the report |
| `POST` | `/v1/office/remediate?quality=true` | Same for Office |
| `GET`  | `/v1/quality/calibration` | Current judge × dimension × format calibration metrics |
| `GET`  | `/v1/quality/review/queue` | Specialist review queue (paginated, filterable by format) |
| `POST` | `/v1/quality/review/submit` | Submit specialist verdict on a queued document |
| `GET`  | `/v1/quality/dimensions` | Returns the per-format dimension applicability matrix (Section 5.1) |

All gated by existing `X-API-Key` auth. Specialist endpoints further gated by a role flag (`APP_REVIEWER_KEYS` env var).

---

## 13. Phased Build Plan

This plan assumes the agent is working **on the existing codebase**. Each phase ships independently and is reviewable on its own.

**Phase A — Annotated reference corpus (foundation, all formats).**
Build the format-aware annotation schema, the annotation CLI, and seed 50–80 documents across PDF + Office with specialist-vetted annotations. *Exit criterion:* schema validates, CLI works end-to-end, ≥ 30 PDF + ≥ 20 Office documents annotated and committed under `tools/corpus_annotations/v1/`.

**Phase B — Behavioral proxy module (PDF).**
Implement Sections 6.1–6.5, 6.7 for PDF as a standalone module wired to but not blocking `pdf_acceptance`. Use the `behavioral_proxies/shared/` + `behavioral_proxies/pdf/` structure from the start. *Exit criterion:* each behavioral test correctly distinguishes gold from known-bad on the PDF corpus, with regression tests in `tests/behavioral_proxies/pdf/`.

**Phase C — Quality judge ensemble (PDF).**
Implement narrow judges per Section 5 for PDF, in the `quality_judges/pdf/` namespace. Calibrate against the annotated corpus. Enforce model-separation rules from Section 9. *Exit criterion:* each PDF judge × dimension exceeds Cohen's κ ≥ 0.7 against specialist annotations on the calibration set.

**Phase D — Per-dimension metrics extension.**
Extend `scorer.py` and `experiment_store.py` per Section 8, additively. `ExperimentRecord` gains `quality_dimensions` and `behavioral_results` fields. Update `compliance_report.py` to surface per-dimension scores when a `QualityResult` is present. *Exit criterion:* `ScoringResultV2` is populated; existing dashboards/reports unchanged when no `QualityResult` is attached.

**Phase E — Endpoints + opt-in integration (PDF).**
Add `quality_routes.py` with `/v1/quality/audit/pdf` and the `quality=true` flag on `/v1/remediate`. *Exit criterion:* `/v1/quality/audit/pdf` returns valid `QualityResult`; `/v1/remediate` default flow byte-identical to pre-change.

**Phase F — Calibration sampling loop.**
Implement Section 10. Stratified sampling job, specialist queue, drift alerting. *Exit criterion:* loop runs end-to-end on staging; one round of specialist verdicts feeds back into `judge_calibration` table.

**Phase G — Dimension-aware evolution.**
Extend `proposer.py` and `analyze_failures` to surface weak quality dimensions (per format, per document class) and generate targeted strategies. See Section 17 for full spec. *Exit criterion:* on the corpus, dimension-aware proposer produces strategies that target the correct dimension for known-weak harness configurations; new strategies achieve measurable lift on the targeted dimension in a controlled A/B (Section 17.4).

**Phase H — Office quality layer.**
Extend judges and behavioral proxies to DOCX, PPTX, XLSX in their respective `quality_judges/office/{format}/` and `behavioral_proxies/office/{format}/` namespaces. Add Office endpoints. See Section 18 for full spec. *Exit criterion:* per-format judge × dimension Cohen's κ ≥ 0.7; behavioral proxies pass corpus regression tests; `/v1/office/remediate` byte-identical when `quality=false`.

**Phase I — Test hardening + CI integration.**
Section 11 in full. CI quality-checks job runs on every PR, per format. *Exit criterion:* test coverage ≥ 70% on new modules; CI green across all phases' test suites.

---

## 14. Success Criteria

The extension is successful when:
- Each quality dimension's judge exceeds Cohen's κ ≥ 0.8 with specialist verdicts on the calibration set, **per format**
- Behavioral proxies correctly distinguish gold from known-bad on ≥ 95% of corpus entries, per format
- `/v1/remediate` and `/v1/office/remediate` default behavior byte-identical pre/post-change on the full corpus
- New endpoints are documented in `/openapi.json` and have endpoint tests
- The calibration loop has captured ≥ 1 round of specialist verdicts and fed them back into the system
- No quality-judge model overlaps with any production remediation model
- **Phase G specific**: dimension-aware proposer demonstrates measurable lift (≥ 5 percentage points improvement on the targeted dimension) in at least 3 controlled A/B experiments without regression on other dimensions
- **Phase H specific**: Office quality layer covers all dimensions in the applicability matrix (Section 5.1) with judges meeting the κ threshold

---

## 15. Risks and Mitigations

**Risk: Calibration contamination despite the rule.** Even with model-family separation, sibling models can share blind spots. *Mitigation:* gold standards remain human-annotated; pairwise comparison preferred over absolute scoring; track per-judge agreement over time and alert on drift.

**Risk: Existing system regressions from new code paths.** *Mitigation:* every extension is additive; byte-identical regression test on `/v1/remediate` and `/v1/office/remediate` runs before each merge.

**Risk: Behavioral test LLM cost.** *Mitigation:* cache by document hash; gate behavioral tests behind opt-in flag; sample rather than running on every job.

**Risk: Specialist annotation bottleneck.** *Mitigation:* start with 50–80 documents; grow incrementally via the calibration loop; use existing model output as a starting draft for specialists to correct (recorded in metadata, never used as gold).

**Risk: Ollama-only architecture limits judge model choice.** *Mitigation:* extend `OllamaClient` rather than build parallel client code; document at least two viable non-kimi judge backends.

**Risk: Phase G dimension-aware proposer over-fits to corpus.** *Mitigation:* hold out a portion of the annotated corpus from proposal generation; require A/B improvement on held-out documents before any new strategy is promoted.

**Risk: Phase G strategies target wrong harness component.** A "fix alt text" strategy might modify a prompt that doesn't actually generate alt text. *Mitigation:* strategy → harness-component mapping is explicit and version-controlled (Section 17.3); regression tests verify each strategy actually changes the intended component.

**Risk: Phase H Office formats don't have a counterpart to vision_planner.** Office remediator is deterministic; there's no agentic loop for evolution to drive. *Mitigation:* Phase H is judges + proxies + corpus + endpoints only. Office evolution is explicitly out of scope for v1; Phase H produces the *signal* (per-dimension scores) that a future Office evolution loop could consume.

**Risk: Phase H format-specific edge cases (e.g., XLSX has no real "reading order").** *Mitigation:* dimension applicability matrix in Section 5.1 is authoritative; judges/proxies for inapplicable dimensions are not implemented; the score schema marks them as `n/a` rather than 0.0 or 1.0.

---

## 16. Definition of Done (per phase)

A phase is "done" only when:
- Phase exit criteria pass on the full annotated corpus (per format where applicable)
- No regression in existing endpoint behavior (byte-identical snapshot test)
- New tests are in place and passing in CI
- The phase summary report documents metrics, outstanding risks, and next steps
- Code, prompts, schemas, and corpus version are tagged together as a coherent release point
- Backward compatibility verified: any client written against pre-change endpoints continues to work

---

## 17. Dimension-Aware Evolution (Phase G detail)

The existing `proposer.py` analyzes failures by veraPDF rule ID and document type, producing strategies like `table_structure_focus` (when 7.2/7.5 violations dominate) or `untagged_content_tagging` (when 7.1 dominates). This is **compliance-driven** — it can only see failures that veraPDF flags. It is blind to the most interesting class of failures: documents that pass compliance but fail quality (e.g., alt text exists but is "image of dog" instead of "guide dog leading person across busy intersection").

Phase G extends the proposer to be **dimension-aware**: it analyzes per-dimension quality scores (now tracked in `ExperimentRecord` per Section 8.1) and proposes strategies targeting weak dimensions, optionally sliced by document class.

### 17.1 Failure pattern extension

`ExperimentStore.get_failure_patterns(harness_id)` returns the existing patterns plus new ones:

```python
{
    # existing
    "failing_doc_types": {...},
    "failing_violation_types": {...},
    "destructive_docs": [...],
    "common_errors": {...},

    # new in Phase G
    "weak_dimensions_overall": {"alt_text": 0.61, "reading_order": 0.78, ...},
    "weak_dimensions_by_doc_type": {
        "scientific_paper": {"alt_text": 0.45, "table_structure": 0.62, ...},
        "marketing_collateral": {"alt_text": 0.92, "reading_order": 0.71, ...},
    },
    "compliance_passes_quality_fails": [
        # documents where verapdf passed but quality dimensions failed
        {"doc_hash": "...", "weak_dims": ["alt_text", "complex_content"]}, ...
    ],
    "behavioral_proxy_failures_by_dim": {
        "alt_text": 12,        # number of docs failing alt_text image-substitution test
        "reading_order": 4,
    },
}
```

The `compliance_passes_quality_fails` bucket is the most valuable signal — it surfaces failures the existing proposer cannot see.

### 17.2 New strategy generators

Each new strategy targets a specific quality dimension and a specific harness component. `_recommend_strategies()` is extended (not replaced) with these strategies:

| Strategy name | Trigger | Target harness component | Modification |
|---|---|---|---|
| `improve_alt_text_<doc_class>` | alt_text dim < 0.7 in doc class | vision_planner planner's `set_alt_text` action prompt + `vision.py` alt text prompt | Add doc-class-specific examples and informativeness guidance |
| `tighten_reading_order_<doc_class>` | reading_order dim < 0.7 in doc class | grounder region detection prompt + planner `fix_reading_order` action | Add multi-column / sidebar handling guidance |
| `improve_heading_semantics_<doc_class>` | heading dim < 0.7 in doc class | planner's `set_tag` action for heading levels | Add semantic-vs-visual distinction examples |
| `tighten_decorative_classification` | decorative dim < 0.7 globally | grounder's region type classification | Stricter "decorative" criteria, examples of borderline cases |
| `improve_complex_content_description` | complex_content dim < 0.7 | `vision.py` chart/equation prompt | Require data-not-just-type descriptions |
| `improve_table_structure_<doc_class>` | table dim < 0.7 AND not already firing on veraPDF | planner's `reconstruct_table` action | Distinguish data tables from layout; header inference |
| `improve_link_text` | link dim < 0.7 | new planner action for link text rewriting | Replace "click here" / "read more" with context-aware text |

Strategies are **additive** to the existing veraPDF-driven ones. When both fire (e.g., 7.2 violations dominate AND table dim is weak), they're combined into a single proposal.

### 17.3 Strategy → harness-component mapping

The mapping above is encoded in a version-controlled file: `src/project_remedy/vision_planner/dimension_strategy_map.yaml`. This file is the single source of truth for which prompt or action gets modified by which strategy. Regression tests verify that each strategy actually modifies the declared component (and only the declared component).

```yaml
# Example
improve_alt_text_scientific_paper:
  dimension: alt_text
  doc_class: scientific_paper
  targets:
    - file: quality_judges/pdf/prompts/alt_text_judge_v3.md   # not modified
    - file: vision_planner/harness.py
      method: build_planner_prompt
      hook: alt_text_action_examples
    - file: vision.py
      function: generate_alt_text
      hook: scientific_paper_examples
  modifications:
    add_examples: true
    examples_source: corpus_annotations/v1/by_doc_class/scientific_paper/alt_text_examples.json
    informativeness_emphasis: true
```

### 17.4 Held-out evaluation

A new strategy is **not promoted** until it demonstrates lift in a controlled A/B:

1. The annotated corpus is split into `proposal_set` (used for failure analysis) and `holdout_set` (used for evaluation only).
2. When a new strategy is generated, its proposal variant runs against the holdout set.
3. Lift is measured **on the targeted dimension** (e.g., alt_text strategy is judged on alt_text scores, not overall conformance).
4. Promotion criteria: ≥ 5 percentage points improvement on the targeted dimension AND no regression > 2 percentage points on any other dimension.
5. If a strategy regresses on a non-targeted dimension, it's logged but not promoted.

This prevents the proposer from learning to game one dimension at the expense of others.

### 17.5 Backward compatibility

`HarnessProposer` keeps its existing public API. New strategies register via the same `ProposalStrategy` dataclass. `analyze_failures()` returns a superset of its current dict (existing keys unchanged). Existing behavior — proposing strategies based on veraPDF rule IDs — runs unchanged when `quality_dimensions` is empty in `ExperimentRecord` (i.e., when quality judges haven't been run).

---

## 18. Office Quality Layer (Phase H detail)

PDF was first because its compliance layer is the most mature in this repo, but Office formats (DOCX, PPTX, XLSX) account for a substantial share of accessibility remediation work. Phase H extends the quality layer — judges, behavioral proxies, corpus annotations, endpoints — to Office. It does **not** add an agentic remediation loop to Office; the existing `office_remediator.py` is deterministic and stays so. Phase H produces per-dimension quality signals that a future Office evolution loop could consume.

### 18.1 Format-specific implementation notes

**DOCX** (operates on `python-docx` document tree):
- Alt text judge: per-image inline shapes and floating shapes; reads from `wp:docPr.descr` and `pic:cNvPr.descr`
- Heading semantics judge: reads Word styles applied to paragraphs (Heading 1, Heading 2, etc.); compares to visual layout via PDF rendering for cross-check
- Table structure judge: reads `w:tbl.tblHeader` for header row designation; checks for repeated header rows on multi-page tables
- Link text judge: reads hyperlink display text and target URL; flags non-descriptive text
- Decorative judge: reads `wp:cNvPicPr.picLocks` and the new `decorative` attribute available in modern Word

**PPTX** (operates on `python-pptx` slide tree):
- Alt text judge: per-shape; reads from shape's `nvSpPr.cNvPr.descr`
- Slide reading order judge: PowerPoint's slide-level reading order is set via the Selection Pane; reads from XML; this is the most quality-divergent dimension since PowerPoint's default visual order rarely matches semantic order
- Slide title judge: title placeholder presence and content quality
- Decorative judge: per-shape `decorative` flag (newer PPTX schema)
- Table judge: tables-as-shapes with header row attributes

**XLSX** (operates on `openpyxl` workbook):
- Alt text judge: charts, embedded images, drawings
- Table structure judge: detects Excel Tables (`worksheet.tables`) vs ad-hoc cell ranges; checks for header row, total row, banded rows
- Sheet organization judge: tab names ("Sheet1" vs "Q3 Revenue"), purpose clarity, sheet ordering
- Reading order: not applicable (sheets are inherently 2D; rows/columns aren't read serially in the same way)

### 18.2 Behavioral proxies per format

| Test | DOCX | PPTX | XLSX |
|---|---|---|---|
| Alt text image-substitution | ✓ | ✓ | ✓ (charts/images) |
| Heading/title navigation | ✓ | ✓ (slide titles) | n/a |
| Table cell lookup | ✓ | ✓ | ✓ (especially valuable here) |
| Reading order comprehension | partial (mostly linear) | ✓ (per-slide) | n/a |
| Decorative skip | ✓ | ✓ | sparse |
| Sheet navigation | n/a | n/a | ✓ |

PPTX reading order is its own beast: each slide is an independent reading-order context, and PowerPoint's default tab order is generally not the semantically correct order. The PPTX comprehension test runs per-slide and aggregates.

### 18.3 Corpus annotation extensions

Office documents in the corpus carry format-specific annotation fields under `format_specific`:

```json
{
  "format": "pptx",
  "format_specific": {
    "pptx": {
      "slide_count": 18,
      "per_slide": [
        {
          "slide_index": 1,
          "title": "Quarterly Results",
          "applicable_dimensions": ["alt_text", "reading_order", "table_structure"],
          "dimensions": { ... }
        }
      ]
    }
  }
}
```

XLSX uses `per_sheet` instead. DOCX is mostly flat (no per-section breakdown by default).

### 18.4 Office evolution: explicitly deferred

Office remediation in `office_remediator.py` is deterministic (rule-based via `python-docx`/`python-pptx`/`openpyxl`). There's no Grounder/Planner/Executor loop to evolve. Phase H does **not** introduce one. What Phase H produces is the per-dimension quality signal — `QualityResult` for Office documents — that a hypothetical future Office vision-planner could consume to drive evolution. The dimension-aware proposer architecture from Phase G is designed to be format-agnostic so it can be extended to Office when (and if) that loop is built.

### 18.5 Backward compatibility

`office_acceptance.py` gains an optional `quality_result` field on its result type, mirroring the PDF pattern. Existing `/v1/office/check`, `/v1/office/remediate`, and `/v1/convert/office-to-html` flows are unchanged when `quality=false` (default). The `OfficeRemediator` class signature is preserved; only the acceptance result is extended.
