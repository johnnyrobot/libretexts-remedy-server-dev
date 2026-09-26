# Agent Prompt: Build the Quality Layer Extension on Remedy Server

You are an autonomous coding agent working on the **existing** remedy-server-v2` repository. Your task is to implement the Quality Layer Extension specified in `document-remediation-prd.md`. You are augmenting a substantial existing system, not building one from scratch.

The PRD is the source of truth. If anything in this prompt conflicts with it, the PRD wins.

---

## Pre-flight: Read the codebase before writing anything

Before any code change, do the following in order, and confirm with the human:

1. Read `README.md`. Then read `CLAUDE.md` if it exists.
2. List the contents of `src/project_remedy/` and `backend/app/` and confirm you understand the existing architecture.
3. Open and read these specific files in full — they are the integration surfaces:
   - `src/project_remedy/pdf_acceptance.py` (you will extend `PDFAcceptanceResult`)
   - `src/project_remedy/office_acceptance.py` (you will extend the Office acceptance result in Phase H)
   - `src/project_remedy/office_remediator.py` (you will NOT modify; you need to know its outputs)
   - `src/project_remedy/compliance_report.py` (you will extend rendering)
   - `src/project_remedy/vision_planner/scorer.py` (you will extend `ScoringResult`)
   - `src/project_remedy/vision_planner/experiment_store.py` (you will add columns + a new table)
   - `src/project_remedy/vision_planner/proposer.py` (Phase G — you will extend with dimension-aware strategies)
   - `src/project_remedy/vision_planner/harness.py` (Phase G — strategies modify hooks here)
   - `src/project_remedy/tag_tree_reader.py` (you will use the serialization output)
   - `src/project_remedy/pdf_wcag_verifier.py` (it does compliance triage; do NOT duplicate its work in your judges)
   - `src/project_remedy/ollama_client.py` (extend this for non-default model families; do not build a parallel client)
   - `src/project_remedy/vision.py` (Phase G — alt text strategies modify hooks here)
   - `tools/remediate_pdf_corpus.py` (your annotation tool will live alongside)
4. Run `pytest -q` to confirm the existing test suite passes on your machine before you change anything.
5. Restate, in your own words: what already exists, what is missing per the PRD, where each new component will plug in, and which phase you'll start with.

Do not write a single line of new code until step 5 is confirmed by the human.

---

## Operating principles (non-negotiable)

1. **Augment, don't rebuild.** The existing compliance layer (`pdf_checker.py`, `pdf_acceptance.py`, `pdf_wcag_verifier.py`) and remediation layer (`pdf_fixer.py`, `vision_planner/`, `office_remediator.py`) work. Do not modify them except via the additive extensions defined in the PRD. If you find yourself wanting to refactor or rewrite an existing module, stop and ask first.

2. **Backward compatibility is a hard constraint.** Existing endpoints (`/v1/remediate`, `/v1/office/remediate`, `/v1/pdf/check`, etc.) must produce byte-identical output on the corpus pre-and-post-change unless the client explicitly opts in to the new layer with `quality=true`. A regression test enforcing this runs on every commit.

3. **Calibration before deployment.** No quality judge ships into the active path until it has been calibrated against the annotated corpus and meets the Cohen's κ threshold from the PRD. Skipping calibration is forbidden.

4. **Model separation enforced in code.** The quality judges must use a different model family from the production remediation model (`kimi-k2.6:cloud`). `quality_judges/shared/base.py` performs a runtime check and refuses to instantiate a judge that uses any model present in `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, or `OLLAMA_ESCALATION_MODEL`. This is not advisory — it is a hard error.

5. **Per-dimension always.** When extending `scorer.py` or any reporting code, always produce a vector of per-dimension scores. Aggregate scores are kept for backward compatibility but de-emphasized.

6. **Behavioral over judgmental.** Where the PRD defines a behavioral test for a dimension, that test takes precedence over the judge's verdict when they disagree.

7. **Format-namespaced from Phase B onward.** Even though Phase B and C only build PDF, the `quality_judges/` and `behavioral_proxies/` directories use the format-namespaced structure (`pdf/`, `office/{docx,pptx,xlsx}/`, `shared/`) from the start, so Phase H is purely additive rather than requiring a refactor.

8. **Loops have stopping criteria.** Any iterative process you build (calibration, regression bisection, judge prompt tuning, dimension-aware A/B evaluation) has explicit stopping conditions: threshold met, no improvement over N iterations, or max iteration budget. Document the criteria; do not improvise.

9. **Existing patterns over new ones.** This codebase has conventions: dataclass-based result types, async route handlers in `backend/app/`, SQLite-backed stores via context managers, version-controlled YAML config files. Match those patterns.

---

## Working mode

Work through the PRD's phased build plan (Section 13: Phases A through I). Within each phase:

1. **State the phase goal and exit criteria** in your own words at the start.
2. **List the specific existing files you will touch** and how your changes preserve backward compatibility.
3. **List the new files you will create** and where they live in the directory structure (per PRD Section 4).
4. **Build incrementally, with tests.** No batch implementation followed by batch testing. Each new module gets its tests at the same time.
5. **After each component, run the full existing test suite plus any new tests.** Do not proceed if existing tests regress.
6. **When phase exit criteria are met**, generate a phase summary report (`phase-{A-I}-summary.md`) and pause for human confirmation before proceeding.

After every iteration, append a brief log entry to `BUILD_LOG.md` capturing: which file(s) changed, which tests passed or moved, what metric shifted, what you'll do next. Keep entries terse.

---

## The iteration loop (inside each phase)

```
1. Pick the smallest reviewable change for the current phase
2. Make the change, write/update tests
3. Run: pytest -q (full suite) + the new specific tests
4. If existing tests regress → revert, bisect, fix root cause, re-attempt
5. If new tests fail → iterate on the change
6. If both pass → run the regression snapshot test (byte-identical /v1/remediate AND /v1/office/remediate on corpus)
7. If snapshot regresses without explicit opt-in → revert, fix
8. If snapshot stable → commit with descriptive message
9. Append to BUILD_LOG.md and continue
```

Termination conditions:
- Phase exit criteria met → write phase summary, stop, ask for review
- Three consecutive iterations with no progress on a single component → stop, ask for guidance
- Test coverage drops on existing modules → stop, fix immediately
- A regression in any byte-identical snapshot → stop, treat as P0

---

## Phase-specific guidance

### Phase A — Annotated reference corpus
The schema must be **format-aware** from day one. PDF + DOCX + PPTX + XLSX all use the same top-level structure with a `format` discriminator and a `format_specific` block. Don't build a PDF-only schema and retrofit Office later.

### Phases B and C — PDF behavioral proxies and judges
Build into the format-namespaced structure (`behavioral_proxies/pdf/`, `quality_judges/pdf/`) with the `shared/` framework code. Do not put PDF code at the top level of either directory — that creates ambiguity when Phase H lands. The `shared/base.py` defines the protocol; format-specific subdirectories implement it.

### Phase D — Per-dimension metrics extension
The schema migration on `experiment_records` (adding `quality_dimensions_json` and `behavioral_results_json` columns) must be additive and backfill-safe. Existing rows get default empty JSON. The `judge_calibration` table is purely new.

When extending `ScoringResult` to `ScoringResultV2`, use Python inheritance — don't create a parallel class. `HarnessScorer.score_variant()` returns the v2 type; existing callers reading only v1 fields keep working.

### Phase E — Endpoints
Use `backend/app/quality_routes.py` as a new file; do not edit `routes.py`. Mount the new router from `main.py`. The `quality=true` flag on `/v1/remediate` is a query param; the default flow when the flag is absent or false is preserved exactly.

### Phase F — Calibration sampling loop
Keep the v1 implementation minimal: JSON-backed queue, no UI, CLI-driven verdicts via `tools/annotate_corpus.py`. The drift alerting is a structured log entry plus an optional webhook; don't build alerting infrastructure.

### Phase G — Dimension-aware evolution

This is the most architecturally consequential phase. Read PRD Section 17 in full before starting.

**Read first:** `proposer.py` (the existing strategy generators), `experiment_store.py` (failure pattern computation), `harness.py` (which methods are extension points), `vision.py` (where alt text generation lives outside vision_planner).

**The key insight:** the existing proposer keys on veraPDF rule IDs and document types. Your extension keys on per-dimension quality scores. Both should fire side-by-side; they are not alternatives.

**Critical mechanism: `dimension_strategy_map.yaml`.** This file is the version-controlled source of truth for which strategy modifies which harness component. Every new strategy must:
1. Be declared in the map with explicit target file/method/hook
2. Have a regression test that verifies it modifies the declared component **and only the declared component**
3. Have a test that verifies it does NOT modify hooks claimed by other strategies (no cross-contamination)

**Held-out evaluation is mandatory.** Split the annotated corpus into `proposal_set` and `holdout_set` once, deterministically (hash-based). Every new strategy is evaluated only on holdout. Promotion requires ≥ 5pp lift on the targeted dimension AND no regression > 2pp on any other dimension. If a strategy fails this bar, it's recorded but not promoted; do not iterate the strategy on the holdout (that's holdout contamination).

**The `compliance_passes_quality_fails` bucket.** When you compute failure patterns, the documents that pass veraPDF but fail one or more quality dimensions are the most valuable training signal. Surface them prominently in the analysis output. Strategies generated from this bucket are typically the ones that produce real lift, because they target failures the existing proposer cannot see.

**Don't break existing strategies.** `_recommend_strategies` returns a list. Append your dimension-aware strategies to the existing returns. Both kinds fire when both apply.

### Phase H — Office quality layer

Read PRD Section 18 in full before starting. Read `office_remediator.py`, `office_acceptance.py`, and `office_routes.py` to understand the existing Office surface.

**The dimension applicability matrix (PRD Section 5.1) is authoritative.** XLSX has no reading order. DOCX heading navigation is mostly trivial. PPTX has slide-title-quality as a unique dimension. Don't implement judges/proxies for inapplicable dimensions; mark them `n/a` in the score schema rather than zero.

**Format-specific libraries:** DOCX uses `python-docx`, PPTX uses `python-pptx`, XLSX uses `openpyxl`. These are likely already in the dependency set (verify); the existing `office_remediator.py` uses them. Reuse the same parsing patterns.

**No Office evolution loop in v1.** `office_remediator.py` is deterministic. Phase H produces per-dimension quality signals; an Office vision-planner is a future phase. If you find yourself building one, stop — that's out of scope.

**PPTX reading order is the most quality-divergent dimension.** PowerPoint's default tab order rarely matches semantic order. The slide-reading-order judge runs per-slide; the comprehension behavioral test also runs per-slide and aggregates. Build the per-slide structure into both judge and proxy from the start.

**Backward compat for Office endpoints:** `/v1/office/remediate?quality=true` is the opt-in. Default behavior of all existing Office endpoints is unchanged.

### Phase I — Test hardening
This phase is partially ongoing — every prior phase ships its own tests. Phase I is the formalization: coverage report, CI integration, cross-phase integration tests. Don't treat it as a place to write tests you skipped earlier.

---

## When to ask for human input

**Ask before proceeding when:**
- You need to introduce a new external dependency (model API, library, service)
- The annotated corpus needs a document class not yet covered, and you need specialist judgment
- A judge's calibration falls below the PRD threshold and prompt iteration hasn't recovered it after 3 attempts
- You discover an ambiguity or apparent conflict in the PRD
- You're considering modifying any existing file beyond the additive extensions in PRD Section 4
- A phase exit criterion appears achievable only by relaxing the criterion
- The model-separation rule (Section 9) appears to block you (e.g., no alternative model is configured) — surface this rather than silently disabling the rule
- **Phase G specific:** a new strategy fails held-out evaluation; do NOT iterate the strategy on the holdout — escalate
- **Phase G specific:** strategies are firing but no lift is observed across multiple holdout runs — the harness extension points may be wrong; surface for review
- **Phase H specific:** a dimension applies to a format per the matrix but the format's parsing library doesn't expose what's needed — surface, don't substitute weaker signals

**Do NOT ask permission to:**
- Read or list any file in the repo
- Run tests, linters, or type-checkers
- Iterate on a judge prompt or rubric within the established framework
- Add or modify tests for new modules
- Add reference corpus annotations using the established schema
- Tune thresholds within the ranges suggested by the PRD
- Iterate on a Phase G strategy on the proposal_set (NOT the holdout)

---

## Reporting cadence

After each phase, produce a phase summary report (`phase-{A-I}-summary.md`) with:
- Phase goal restated
- Exit criteria, with concrete evidence each was met (test outputs, metric tables, file listings)
- Per-dimension metrics where applicable (per format from Phase H onward)
- Judge × dimension Cohen's κ values where applicable, per format
- The byte-identical snapshot test result for `/v1/remediate` and `/v1/office/remediate`
- **Phase G specific:** held-out A/B results for any new strategies, with per-dimension lift numbers
- **Phase H specific:** per-format applicability check (which dimensions implemented, which marked n/a, which deferred)
- Outstanding risks and known limitations
- Specific recommendations for the next phase

Do not proceed to the next phase until the human reviews and confirms.

---

## Failure handling

**When existing tests regress:**
1. Stop forward progress immediately
2. Identify the change that introduced the regression (last commit is usually the answer)
3. If the regression is genuine, revert; do not paper over with test changes
4. Fix root cause, then re-apply the change correctly
5. Add a regression test specifically guarding the case that broke

**When the byte-identical snapshot test fails on `/v1/remediate` or `/v1/office/remediate`:**
P0. The default flow must remain byte-identical unless the client opts in. If your change unintentionally affects the default flow, revert immediately.

**When a judge's calibration is below threshold:**
1. Run it on known-good and known-bad reference annotations
2. If it can't distinguish them, the rubric is wrong — rewrite the rubric, not the prompt wrapper
3. If it distinguishes them but disagrees with humans on edge cases, expand the calibration set in those edge regions and iterate
4. After 3 unsuccessful prompt iterations, escalate to human

**When a Phase G strategy fails held-out evaluation:**
1. Record the failure in the strategy's metadata; do not delete the strategy
2. Do NOT iterate on the holdout — that's contamination
3. Examine the proposal_set analysis for hypotheses about why the strategy didn't generalize
4. If you can construct a refined hypothesis, generate a *new* strategy with a different name and target; the original stays recorded but unpromoted
5. After 2 unsuccessful refinements, escalate to human

**When you're uncertain:**
- Prefer running an experiment over speculating
- Behavioral test verdict beats judge verdict when they disagree
- Two narrow judges in the same dimension disagreeing significantly is a calibration problem; do not aggregate over the disagreement
- Read the existing code before writing new code — chances are the pattern already exists

---

## Anti-patterns (do not do these)

- Re-implementing what `pdf_checker.py`, `pdf_wcag_verifier.py`, `pdf_acceptance.py`, or `office_acceptance.py` already do (compliance is solved; you are adding *quality*)
- Modifying the default `/v1/remediate` or `/v1/office/remediate` flow's behavior
- Adding aggregate "overall quality" metrics as primary KPIs
- Using `kimi-k2.6:cloud` (or any model in `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, `OLLAMA_ESCALATION_MODEL`) as a judge model
- Generating gold-standard remediations from any model used in production and treating them as ground truth
- Skipping calibration "to ship faster"
- Building a parallel HTTP client when `OllamaClient` can be extended
- Building a parallel experiment store when `experiment_store.py` can be extended
- Writing broad rubrics like "rate this 1–10 for quality"
- Using non-versioned judge prompts inlined in code instead of files in `quality_judges/{format}/prompts/`
- Putting PDF judges or proxies at the top level of `quality_judges/` or `behavioral_proxies/` instead of in `pdf/` (Phase H assumes namespacing from the start)
- Adding new tests only for new code while leaving the existing `test_smoke.py` as the only existing-code test
- Calling `pip install` outside the existing `pyproject.toml` dependency declarations
- Bypassing `APP_ENV=production` startup checks "just for testing"
- **Phase G specific:** iterating on a strategy using holdout evaluation results
- **Phase G specific:** modifying harness components not declared in `dimension_strategy_map.yaml` for a given strategy
- **Phase G specific:** replacing existing veraPDF-driven strategies with dimension-aware ones (they coexist; both fire when both apply)
- **Phase H specific:** building an Office vision_planner (out of scope for v1)
- **Phase H specific:** implementing judges for dimensions marked n/a in the applicability matrix
- **Phase H specific:** flattening per-slide PPTX structure into a single document-level score (it must be per-slide aggregated)

---

## Engineering hygiene

- Match the existing code style (Python 3.13, dataclasses, type hints, async where the codebase uses async)
- Run `python -m compileall -q backend src tests` after any change, matching CI
- Match the existing `pyproject.toml` dependency conventions; new deps go in `[project.optional-dependencies]`
- Judge prompts, rubrics, behavioral test prompts, JSON schemas, and the `dimension_strategy_map.yaml` are version-controlled files, not strings buried in code
- The reference corpus and its annotations are first-class artifacts: versioned, immutable per release, schema-validated in CI
- Configuration: extend `backend/app/config.py` and `src/project_remedy/config.py` rather than introducing new config files
- Logging: use the existing `logging_config.py` / `logging_setup.py` conventions
- All new endpoints respect the existing `X-API-Key` auth pattern via `backend/app/auth.py`
- Office parsing: reuse `python-docx`, `python-pptx`, `openpyxl` patterns already in `office_remediator.py`; do not introduce alternative libraries

---

## Beginning

Start with **Phase A — Annotated reference corpus** of the PRD's phased build plan.

1. Restate Phase A's goal and exit criteria in your own words.
2. Confirm you've completed the pre-flight steps above.
3. Propose:
   - The exact files you'll create (paths under `tools/corpus_annotations/`, `tools/annotate_corpus.py`)
   - The exact files you'll modify (likely none in Phase A — the corpus is mostly net-new)
   - The format-aware schema you'll use for annotations (a draft of `schema.json` covering PDF + DOCX + PPTX + XLSX)
   - How you'll seed the initial 50–80 documents (which document classes per format, which edge cases, what specialist process you assume)
4. Wait for human confirmation before writing implementation code.
5. After confirmation, proceed autonomously through Phase A's build-and-test loop until exit criteria are met.
6. Generate `phase-A-summary.md` and pause for next-phase confirmation.

If anything in the PRD is ambiguous or appears to conflict with this prompt or with patterns in the existing code, surface the question before starting. Do not paper over ambiguity with assumptions.
