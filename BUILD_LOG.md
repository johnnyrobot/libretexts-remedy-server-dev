# Build Log

## 2026-05-08 - Phase A foundation slice

- Added format-aware corpus annotation schema under `tools/corpus_annotations/schema.json`.
- Added versioned v1 corpus layout placeholders and manifest.
- Added `tools/annotate_corpus.py` with `init`, `annotate`, `validate`, and `dimensions` commands.
- Added focused corpus annotation tests.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_annotate_corpus.py`: 3 passed.
- Verified `./.venv/bin/python -m pytest -q`: 104 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: no byte-identical remediation snapshot test exists yet; Phase A also still needs specialist-vetted corpus annotations.
- Next: add manifest validation and corpus coverage checks so Phase A can prove when the required document mix is present.

## 2026-05-08 - Phase A coverage gate

- Added corpus manifest loading, validation summary, and `coverage` command to `tools/annotate_corpus.py`.
- Added tests proving low-threshold coverage success and PRD-threshold coverage failure.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_annotate_corpus.py`: 4 passed.
- Verified actual corpus gate: `phase_a_ready=false` because there are 0 annotations, 0 PDF, 0 Office, and no document classes.
- Verified `./.venv/bin/python -m pytest -q`: 105 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Next: Phase A needs real specialist-vetted documents or a human-approved seed set; implementation can continue only on infrastructure until that input exists.

## 2026-05-08 - Shared quality infrastructure

- Added `quality_judges/shared/base.py` with `QualityDimensionScore`, `QualityResult`, judge protocol, and hard model-family separation checks.
- Added `behavioral_proxies/shared/base.py` with behavioral proxy protocol and result type.
- Extended `PipelineConfig.api`, `.env.example`, and `config.example.yaml` with quality judge and behavioral test model settings.
- Extended `PDFAcceptanceResult` and `OfficeAcceptanceResult` with optional `quality_result=None` fields.
- Added model-separation and backward-compatibility tests.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/shared/test_base.py`: 6 passed.
- Verified `./.venv/bin/python -m pytest -q`: 111 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Next: build PDF behavioral proxy scaffolding without activating it in default remediation.

## 2026-05-08 - PDF behavioral proxy scaffolding

- Added `behavioral_proxies/shared/question_generator.py` for deterministic dry-run question scaffolding.
- Added PDF behavioral proxy modules for reading order, alt text substitution, heading navigation, table cell lookup, decorative skip, and transcript analysis.
- Added deterministic unit tests for the PDF proxy scoring helpers.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py`: 6 passed.
- Verified `./.venv/bin/python -m pytest -q`: 117 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: these are deterministic scaffolds, not calibrated LLM behavioral tests; Phase B exit criteria still require known-good/known-bad corpus discrimination.
- Next: add PDF quality judge scaffolding with version-controlled prompts and keep it inactive until calibration exists.

## 2026-05-08 - PDF quality judge scaffolding

- Added `quality_judges/shared/ensemble.py` for per-dimension aggregation.
- Added PDF narrow judge modules for alt text, reading order, heading semantics, table structure, link text, decorative classification, and complex content.
- Added versioned prompt files under `quality_judges/pdf/prompts/`.
- Added tests for model-separation enforcement, prompt file presence, judge scoring, and ensemble aggregation.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/pdf/test_pdf_judges.py`: 4 passed.
- Verified `./.venv/bin/python -m pytest -q`: 121 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: judges are heuristic scaffolds and are not calibrated against specialist annotations; they must remain inactive until kappa thresholds are met.
- Next: add per-dimension experiment/scorer storage extensions for quality metrics.

## 2026-05-08 - Per-dimension experiment metrics

- Extended `ExperimentRecord` with `quality_dimensions` and `behavioral_results`.
- Added additive SQLite columns, migration handling, and `judge_calibration` table support.
- Extended failure patterns with weak quality dimensions, quality-fail/compliance-pass records, and behavioral failures by dimension.
- Added `DimensionMetrics` and `ScoringResultV2`; `HarnessScorer.score_variant()` now returns v2 while preserving aggregate fields.
- Added tests for JSON round-trip, additive migration, calibration records, failure patterns, and scorer v2 metrics.
- Verified `./.venv/bin/python -m pytest -q tests/vision_planner/test_quality_metrics_extension.py`: 6 passed.
- Verified `./.venv/bin/python -m pytest -q`: 127 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Next: extend proposer with dimension-aware strategies and a version-controlled strategy map.

## 2026-05-08 - Dimension-aware proposer scaffolding

- Added `vision_planner/dimension_strategy_map.yaml` as the source of truth for quality-dimension strategy hooks.
- Extended `analyze_failures()` output with weak dimensions, compliance-pass/quality-fail records, and behavioral failures by dimension.
- Extended `_recommend_strategies()` to append dimension-aware strategies alongside existing veraPDF-driven strategies.
- Added strategy application support for planner/grounder quality dimension guidance without cross-contaminating unrelated hooks.
- Added Phase G tests for quality-fail strategy generation, veraPDF coexistence, map declaration, and declared-hook-only config mutation.
- Verified `./.venv/bin/python -m pytest -q tests/vision_planner/test_proposer_dimension_aware.py`: 4 passed.
- Verified `./.venv/bin/python -m pytest -q`: 131 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: held-out A/B evaluation and promotion criteria are not implemented; corpus holdout is also unavailable.
- Next: add quality audit API endpoints that expose inactive PDF quality results without changing default remediation.

## 2026-05-08 - Quality API PDF audit surface

- Added `quality_judges/shared/dimensions.py` for the format applicability matrix.
- Added `quality_judges/pdf/audit.py` to run the inactive PDF quality judge ensemble.
- Added `backend/app/quality_routes.py` with `/v1/quality/dimensions` and `/v1/quality/audit/pdf`.
- Mounted the quality router from `backend/app/main.py` without changing existing remediation routes.
- Added API tests for dimensions and PDF audit serialization/cleanup.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 2 passed.
- Verified `./.venv/bin/python -m pytest -q`: 133 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: Office audit endpoints, review/calibration endpoints, and `quality=true` remediation integration are still pending.
- Next: add Office quality scaffolding for DOCX/PPTX/XLSX.

## 2026-05-08 - Office quality audit surface

- Added `quality_judges/office/audit.py` for deterministic DOCX/PPTX/XLSX quality scaffolding over existing Office acceptance checks.
- Added `/v1/quality/audit/office` for opt-in Office quality audit uploads.
- Added route tests for mocked Office quality audit serialization and staged-file cleanup.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 3 passed.
- Verified `./.venv/bin/python -m pytest -q`: 134 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: Office format-specific judge/proxy modules are not fully built; this is endpoint scaffolding, not calibrated Phase H completion.
- Next: add calibration and review queue endpoints backed by minimal JSON/SQLite surfaces.

## 2026-05-08 - Calibration and review endpoints

- Added backend quality settings for calibration store path, JSONL review queue, JSONL submissions, and reviewer keys.
- Added `/v1/quality/calibration` backed by `ExperimentStore.list_judge_calibration()`.
- Added `/v1/quality/review/queue` and `/v1/quality/review/submit` with optional `APP_REVIEWER_KEYS` gating.
- Added tests for calibration reads and JSONL queue/submission flow.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 5 passed.
- Verified `./.venv/bin/python -m pytest -q`: 136 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: review submissions are recorded as JSONL verdicts but are not yet converted into immutable corpus annotation snapshots.
- Next: add `quality=true` opt-in metadata plumbing for existing remediation enqueue routes without affecting defaults.

## 2026-05-08 - Quality opt-in enqueue metadata

- Added `quality` query parameter to `/v1/remediate` and `/v1/office/remediate`.
- Preserved default `/v1/remediate` metadata shape when `quality` is absent or false.
- Added tests proving `quality=true` is recorded as job metadata for generic and Office-specific remediation routes.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_opt_in_routes.py`: 3 passed.
- Verified `./.venv/bin/python -m pytest -q`: 139 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: the job worker does not yet attach `QualityResult` to generated reports when `quality=true`.
- Next: run a completion audit against the PRD/prompt before deciding whether to continue or stop for missing external inputs.

## 2026-05-08 - Compliance report quality section

- Extended `DocumentReport` with optional `quality_result`.
- Preserved default report JSON shape by omitting `quality_result` when absent.
- Added opt-in HTML rendering for per-dimension quality scores when present.
- Added tests for omission/presence behavior.
- Verified `./.venv/bin/python -m pytest -q tests/test_compliance_report_quality.py`: 2 passed.
- Verified `./.venv/bin/python -m pytest -q`: 141 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: `quality=true` jobs still do not compute and attach quality results during worker execution.
- Next: completion audit against the PRD/prompt.

## 2026-05-08 - Worker quality opt-in integration

- Wired PDF `quality=true` jobs to run `audit_pdf_quality()` and attach the result to `PDFAcceptanceResult` before report generation.
- Fixed the PDF worker to pass cached `acceptance` into `generate_document_report()`, allowing opt-in quality results to render without rerunning acceptance.
- Wired Office `quality=true` jobs to run `audit_office_quality()` and persist `quality_result` in job metadata.
- Added worker tests for PDF report attachment and Office metadata persistence.
- Verified `./.venv/bin/python -m pytest -q tests/test_engine_quality_opt_in.py`: 2 passed.
- Verified `./.venv/bin/python -m pytest -q`: 143 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: quality implementations are still uncalibrated scaffolds and do not satisfy PRD deployment thresholds.
- Next: completion audit against the PRD/prompt.

## 2026-05-08 - Default worker regression guard

- Added worker tests proving PDF and Office quality audits are not called when `quality` is absent.
- Verified default PDF reports receive `acceptance.quality_result is None`.
- Verified default Office remediation does not write quality metadata.
- Verified `./.venv/bin/python -m pytest -q tests/test_engine_quality_opt_in.py`: 4 passed.
- Verified `./.venv/bin/python -m pytest -q`: 145 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: this is a unit-level default-flow guard, not a corpus byte-identical snapshot suite.
- Next: add an explicit snapshot test scaffold/gate for corpus availability.

## 2026-05-08 - Office behavioral proxy scaffolding

- Added Office behavioral proxy namespace under `behavioral_proxies/office/{docx,pptx,xlsx}`.
- Added DOCX proxies for alt text substitution, heading navigation, and table lookup.
- Added PPTX proxies for alt text substitution, slide title navigation, and slide reading-order scaffold.
- Added XLSX proxies for table lookup, sheet navigation, and alt text scaffold.
- Added tests for DOCX/PPTX/XLSX proxy behavior over existing Office checker reports.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 3 passed.
- Verified `./.venv/bin/python -m pytest -q`: 148 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: several Office proxies are scaffolds with low confidence, not calibrated behavioral LLM tests.
- Next: add Office quality judge namespace wrappers for DOCX/PPTX/XLSX.

## 2026-05-08 - Office quality judge namespace wrappers

- Added `quality_judges/office/{docx,pptx,xlsx}` format namespaces with dimension-specific judge classes and versioned prompt files.
- Added shared Office heuristic judge base over existing Office checker reports.
- Refactored `audit_office_quality()` to delegate to format-specific judge classes while preserving opt-in result shape.
- Added tests for DOCX/PPTX/XLSX dimension coverage, prompt-file presence, model separation, and audit delegation.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 6 passed.
- Verified `./.venv/bin/python -m pytest -q`: 154 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py`.
- Gap: Office judges remain deterministic scaffolds with no specialist corpus calibration or Cohen's kappa.
- Next: add a minimal calibration CLI and corpus-backed gates without claiming Phase C/H completion.

## 2026-05-08 - Calibration CLI

- Added `tools/calibrate_judges.py` to compute Cohen's kappa per judge/version/format/dimension from corpus annotations.
- Supported offline JSONL judge results for deterministic calibration gates and live audit mode for source artifacts that exist locally.
- Persisted metrics to the existing `judge_calibration` table and emitted structured drift alerts when kappa falls below threshold.
- Added corpus tests for score labels, kappa computation, metric grouping, and SQLite persistence.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_calibrate_judges.py`: 3 passed.
- Verified `./.venv/bin/python -m pytest -q`: 157 passed, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py tools/calibrate_judges.py`.
- Gap: no specialist annotations or real judge result set exist, so the CLI cannot produce PRD-compliant calibration metrics yet.
- Next: add corpus integration/snapshot gates that skip or fail clearly based on corpus availability.

## 2026-05-08 - Corpus snapshot gate scaffold

- Added `tools/verify_corpus_snapshots.py` to verify committed `quality=false` default-flow snapshot records for annotated corpus items.
- Extended corpus layout initialization with `snapshots/{pdf,docx,pptx,xlsx}` directories.
- Added PDF and Office corpus integration tests that skip only while the real annotated corpus is absent, then require matching default-flow snapshots.
- Added snapshot-gate unit tests for missing snapshot failure and valid hash snapshot acceptance.
- Verified `./.venv/bin/python -m pytest -q tests/corpus`: 9 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest -q`: 159 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools/annotate_corpus.py tools/calibrate_judges.py tools/verify_corpus_snapshots.py`.
- Gap: this validates committed snapshot evidence; it does not yet generate or compare live endpoint outputs because the real corpus artifacts are absent.
- Next: add CI `quality-checks` scaffolding for corpus/schema/calibration commands without hiding missing Phase A data.

## 2026-05-08 - CI quality-checks scaffold

- Added `.github/workflows/ci.yml` `quality-checks` job for quality routes, judges, behavioral proxies, corpus tests, and quality vision-planner tests.
- Extended CI compile command to include `tools`.
- Added advisory CI readiness reports for corpus coverage, snapshot records, and calibration dry-runs; these expose missing Phase A data without blocking unrelated unit coverage.
- Fixed script-mode imports for `tools/calibrate_judges.py` and `tools/verify_corpus_snapshots.py`.
- Verified local quality-focused CI command: 58 passed, 2 skipped.
- Verified readiness commands report `phase_a_ready=false`, snapshot `ready=false`, and missing calibration annotations.
- Verified `./.venv/bin/python -m pytest -q`: 159 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: `quality-checks` cannot enforce kappa or byte-identical corpus snapshots until specialist annotations and snapshot artifacts exist.
- Next: run a PRD completion audit and identify any remaining code-only slices that are feasible without external corpus data.

## 2026-05-08 - Held-out promotion criteria helper

- Added `vision_planner/quality_evaluation.py` with deterministic hash-based proposal/holdout corpus splitting.
- Added `evaluate_strategy_promotion()` implementing Phase G promotion criteria: at least 5pp target-dimension lift and no non-target regression beyond 2pp.
- Added tests for stable disjoint splits, successful promotion, insufficient lift rejection, and non-target regression rejection.
- Verified `./.venv/bin/python -m pytest -q tests/vision_planner`: 14 passed.
- Verified `./.venv/bin/python -m pytest -q`: 163 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: no real holdout A/B experiments have run because the annotated corpus and proposal/holdout artifacts are absent.
- Next: run a PRD completion audit and stop short of claiming completion where specialist data is required.

## 2026-05-08 - Review queue sampler CLI

- Added `tools/sample_quality_reviews.py` for JSONL-driven stratified sampling into the specialist review queue.
- Prioritized weak quality dimensions, high inter-judge variance, low behavioral confidence, and deterministic random coverage.
- Added tests for priority ordering, random stratum labeling, JSONL loading, and queue writes.
- Included the sampler in the CI quality-layer compile list.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_sample_quality_reviews.py`: 4 passed.
- Verified `./.venv/bin/python -m pytest -q`: 167 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: production traffic is not feeding candidates automatically; this is the minimal file-backed sampler required before a scheduled job exists.
- Next: final PRD completion audit.

## 2026-05-08 - Review submission corpus feedback

- Extended review submissions to optionally persist a full specialist annotation under `QUALITY_CORPUS_ROOT_PATH`.
- Added optional calibration row persistence from `/v1/quality/review/submit` into `judge_calibration`.
- Added `QUALITY_CORPUS_ROOT_PATH` backend setting and `.env.example` entry.
- Added route tests for annotation materialization, calibration persistence, and invalid annotation rejection.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 7 passed.
- Verified `./.venv/bin/python -m pytest -q`: 169 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: no actual specialist verdicts exist yet, so the feedback path has not ingested real annotations.
- Next: continue PRD audit for any remaining implementable code-only gaps.

## 2026-05-08 - Ollama quality client routing

- Extended `OllamaClient` with `for_quality_judge()` to route judge calls through `QUALITY_JUDGE_MODEL` and optional `QUALITY_JUDGE_BASE_URL`.
- Added `for_behavioral_test()` to route behavioral answerers through `BEHAVIORAL_TEST_MODEL`.
- Added read-only client properties for route/model verification without duplicating HTTP clients.
- Added tests for quality judge base URL override, fallback base URL, and behavioral-test model selection.
- Verified `./.venv/bin/python -m pytest -q tests/test_ollama_client_quality.py`: 3 passed.
- Verified `./.venv/bin/python -m pytest -q`: 172 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: deterministic judge scaffolds still do not call LLM rubrics until calibrated corpus data exists.
- Next: continue PRD audit for any remaining implementable code-only gaps.

## 2026-05-08 - Behavioral results in quality audits

- Wired PDF behavioral proxies into `audit_pdf_quality()` so `QualityResult.behavioral` includes reading order, alt text substitution, heading navigation, table lookup, decorative skip, and transcript analysis.
- Wired Office behavioral proxies into `audit_office_quality()` for DOCX/PPTX/XLSX format-specific tests.
- Added audit tests proving behavioral result maps are populated with expected dimensions.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py`: 11 passed.
- Verified `./.venv/bin/python -m pytest -q`: 173 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: behavioral proxies are still deterministic scaffolds and not calibrated LLM answer-retention tests.
- Next: continue PRD audit for any remaining implementable code-only gaps.

## 2026-05-08 - Dimension strategy map coverage

- Expanded proposer regression tests to cover every declared dimension-aware strategy in `dimension_strategy_map.yaml`.
- Verified each generated strategy records exactly its declared hook and modifies only the declared planner or grounder target.
- Verified veraPDF-driven strategies still coexist with quality-dimension strategies.
- Verified `./.venv/bin/python -m pytest -q tests/vision_planner/test_proposer_dimension_aware.py`: 11 passed.
- Verified `./.venv/bin/python -m pytest -q`: 180 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: strategy promotion still awaits real held-out A/B corpus experiments.
- Next: completion audit against PRD requirements and current evidence.

## 2026-05-08 - Behavioral precedence over judges

- Added `apply_behavioral_precedence()` so applicable behavioral proxy results override judge-only dimension verdicts.
- Wired precedence into PDF and Office quality audits after behavioral proxy execution.
- Ignored advisory-only transcript analysis and non-applicable behavioral tests when applying precedence.
- Added tests for failing behavioral overriding passing judges, passing behavioral overriding failing judges, and neutral advisory/inapplicable results.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/shared tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py`: 20 passed.
- Verified `./.venv/bin/python -m pytest -q`: 183 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: behavioral proxy verdicts still need calibration against specialist corpus examples.
- Next: continue audit for remaining implementable requirements.

## 2026-05-08 - Behavioral model separation

- Added `BehavioralTestConfig` and hard separation checks for `BEHAVIORAL_TEST_MODEL` against production remediation model families.
- Wired `OllamaClient.for_behavioral_test()` to validate model separation before creating the client.
- Added tests for family normalization, rejection of production-family answerers, config extraction, and client-level rejection.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/shared/test_behavioral_model_separation.py tests/test_ollama_client_quality.py`: 9 passed.
- Verified `./.venv/bin/python -m pytest -q`: 189 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: behavioral tests remain deterministic until LLM answer-retention prompts are calibrated against corpus data.
- Next: completion audit for remaining requirements.

## 2026-05-08 - OpenAPI quality endpoint coverage

- Added an API test proving `/openapi.json` documents all quality-layer endpoints.
- Covered `/v1/quality/audit/pdf`, `/v1/quality/audit/office`, `/v1/quality/calibration`, `/v1/quality/review/queue`, `/v1/quality/review/submit`, and `/v1/quality/dimensions`.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 8 passed.
- Verified `./.venv/bin/python -m pytest -q`: 190 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: OpenAPI exposure is covered, but the endpoint schemas remain generic dataclass JSON because the quality layer uses internal dataclasses rather than Pydantic response models.
- Next: completion audit for remaining requirements.

## 2026-05-08 - Structured calibration drift alerts

- Extended `tools/calibrate_judges.py` with structured `quality_judge_drift` alert payloads.
- Added optional `--alert-log` JSONL output and `--alert-webhook` POST support for drift alerts.
- Added tests for alert payload shape and CLI JSONL alert logging.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_calibrate_judges.py`: 5 passed.
- Verified `./.venv/bin/python -m pytest -q`: 192 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: drift alerts cannot operate on real judge metrics until specialist annotations and judge-result rows exist.
- Next: completion audit for remaining requirements.

## 2026-05-08 - Pairwise judge comparison inputs

- Updated PDF and Office heuristic judge `compare()` helpers to accept separate in-memory artifacts for A and B (`tag_tree_report_a/b`, `checker_report_a/b`).
- Added PDF and Office tests proving pairwise comparison can distinguish a better report from a worse one without reading files from disk.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py`: 13 passed.
- Verified `./.venv/bin/python -m pytest -q`: 194 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: pairwise calibration cannot run against real better/worse annotations until the specialist corpus includes those pairs.
- Next: completion audit for remaining requirements.

## 2026-05-08 - CI corpus schema validation

- Added `tools/annotate_corpus.py validate --allow-empty` so CI can validate schema/layout before specialist annotations are committed.
- Added a `quality-checks` CI step that explicitly runs corpus annotation validation.
- Added tests proving default validation remains strict while `--allow-empty` is CI-friendly.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_annotate_corpus.py`: 5 passed.
- Verified `./.venv/bin/python tools/annotate_corpus.py validate --root tools/corpus_annotations/v1 --allow-empty`.
- Verified `./.venv/bin/python -m pytest -q`: 195 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: CI schema validation does not satisfy Phase A coverage until the required specialist annotations exist.
- Next: completion audit for remaining requirements.

## 2026-05-08 - PPTX per-slide reading-order scaffold

- Added per-slide metadata to `PPTXSlideReadingOrderComprehensionTest` instead of returning only document-level results.
- Added per-slide sample findings to `PPTXSlideReadingOrderJudge`.
- Added tests proving PPTX reading-order proxy and judge expose per-slide structures.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 10 passed.
- Verified `./.venv/bin/python -m pytest -q`: 195 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: per-slide values are scaffolds until real PPTX reading-order parsing and LLM comprehension evaluation are calibrated.
- Next: completion audit for remaining requirements.

## 2026-05-08 - XLSX sheet organization signal

- Replaced placeholder XLSX sheet navigation proxy with a sheet-name descriptiveness heuristic using `openpyxl` or test-provided sheet names.
- Replaced placeholder XLSX sheet organization judge with the same deterministic signal.
- Added tests for non-descriptive default sheet names producing findings and failing sheet-organization scores.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 10 passed.
- Verified `./.venv/bin/python -m pytest -q`: 195 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: XLSX sheet organization still needs calibration against specialist annotations.
- Next: completion audit for remaining requirements.

## 2026-05-08 - Reviewer key gate coverage

- Added API tests proving `/v1/quality/review/queue` and `/v1/quality/review/submit` reject requests without `X-Reviewer-Key` when `APP_REVIEWER_KEYS` is configured.
- Verified the same endpoints accept the configured reviewer key.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 9 passed.
- Verified `./.venv/bin/python -m pytest -q`: 196 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: reviewer authorization is key-based only; role-aware user identity is still out of scope for the minimal v1 queue.
- Next: completion audit for remaining requirements.

## 2026-05-08 - Corpus snapshot capture CLI

- Added `tools/capture_corpus_snapshots.py` to submit annotated corpus artifacts to a running Remedy API with default `quality=false`.
- The tool polls job completion, downloads `/v1/jobs/{id}/result`, hashes the initial job response and output bytes, and writes verifier-compatible snapshot records.
- Supports format-specific endpoint selection so Office records use `/v1/office/remediate` while PDFs use `/v1/remediate`.
- Added tests for endpoint selection, verifier-compatible snapshot payloads, and expected snapshot paths.
- Included the capture tool in the CI quality compile list.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_capture_corpus_snapshots.py`: 3 passed.
- Verified `./.venv/bin/python -m pytest -q`: 199 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: capture cannot run until real annotated corpus artifacts and a live API are available.
- Next: completion audit for remaining requirements.

## 2026-05-08 - Quality API schema hardening

- Added Pydantic response models for quality audit, calibration, dimensions, review queue, and review submit endpoints so `/openapi.json` documents concrete response bodies.
- Documented the `quality=true` query parameter on both `/v1/remediate` and `/v1/office/remediate`.
- Added explicit `not_applicable_dimensions` to `QualityResult` and dimensions metadata so skipped Office/PDF dimensions are represented as n/a rather than implied by absence.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py tests/api/test_quality_opt_in_routes.py`: 12 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py`: 13 passed.
- Verified `./.venv/bin/python -m pytest -q`: 199 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: concrete schema docs do not satisfy calibration/corpus gates without specialist annotations.
- Next: completion audit for remaining requirements.

## 2026-05-08 - Active quality calibration gate

- Added `backend/app/quality_calibration.py` to compute per-format calibration readiness from latest `judge_calibration` rows.
- Added deployment settings `QUALITY_REQUIRE_CALIBRATION`, `QUALITY_MIN_COHENS_KAPPA`, and `QUALITY_MIN_CALIBRATION_SAMPLES`; production defaults require calibration when unset.
- Wired the gate into `/v1/quality/audit/{pdf,office}` and the `quality=true` worker paths so active opt-in quality execution can be blocked until calibration passes.
- Added readiness metadata to `/v1/quality/calibration?format=...`.
- Added API and worker tests for missing-calibration blocking and calibrated execution.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py tests/api/test_quality_opt_in_routes.py`: 14 passed.
- Verified `./.venv/bin/python -m pytest -q tests/test_engine_quality_opt_in.py`: 5 passed.
- Verified `./.venv/bin/python -m pytest -q`: 202 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: the gate currently reports not ready because the specialist corpus and calibration rows do not exist yet.
- Next: completion audit for remaining requirements.

## 2026-05-08 - Completion audit artifact

- Added `v2_docs/quality-layer-completion-audit.md` mapping prompt/PRD requirements to concrete repository evidence.
- Recorded current verification outputs: 202 passed / 2 skipped / 5 warnings, compile pass, Phase A coverage failure, snapshot readiness failure, and calibration dry-run failure due no annotations.
- Gap: audit confirms the objective is not complete until specialist annotations, source/gold artifacts, snapshots, calibration metrics, held-out A/B results, and coverage evidence exist.
- Next: wait for corpus artifacts or continue closing code-only gaps that do not require fabricating specialist data.

## 2026-05-08 - Phase I quality coverage gate

- Added `tools/quality_coverage.py`, a stdlib-only coverage gate for quality-layer Python modules and tools.
- Wired the CI `quality-checks` job to enforce `tools/quality_coverage.py check --threshold 70` without adding a new dependency.
- Added tests for executable-line detection, summary calculation, threshold failure, and target discovery.
- Updated `v2_docs/quality-layer-completion-audit.md` to mark the >=70% quality-module coverage requirement as satisfied by the new gate.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_quality_coverage.py`: 4 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 101 passed, 2 skipped; quality coverage 81.08% (1933/2384).
- Verified `./.venv/bin/python -m pytest -q`: 206 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: coverage enforcement does not resolve missing specialist corpus, snapshots, calibration, or held-out A/B evidence.
- Next: continue closing code-only gaps that do not require fabricating corpus data.

## 2026-05-08 - Behavioral proxy cache and separation wiring

- Added optional `BEHAVIORAL_TEST_CACHE_PATH` / `behavioral_test_cache_path` configuration.
- Added a shared JSON-backed behavioral result cache keyed by artifact SHA-256, format, test name, and proxy class.
- Wired PDF and Office quality audits to use the cache when configured and to enforce behavioral answerer model separation at audit time.
- Added tests for artifact hashing, cache reuse, missing-artifact cache bypass, and audit-level behavioral model separation.
- Updated the completion audit to record behavioral proxy cost mitigation as implemented.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/shared/test_behavioral_model_separation.py tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py`: 22 passed.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 11 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 105 passed, 2 skipped; quality coverage 81.23% (1991/2451).
- Verified `./.venv/bin/python -m pytest -q`: 210 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: cached proxy outputs are still deterministic scaffolds until calibrated LLM-backed behavioral tests can run against the specialist corpus.
- Next: continue closing code-only gaps that do not require fabricating corpus data.

## 2026-05-08 - Specialist review claim flow

- Added `POST /v1/quality/review/claim` to claim JSONL queue items with `doc_id`, optional `format`, and `reviewer_id`.
- Claiming marks queue rows with `status=claimed`, `claimed_by`, and `claimed_at`; conflicting reviewer claims return 409.
- Review submit now marks a matching queue row `status=completed` with `completed_at` and reports `queue_item_completed`.
- Extended reviewer-key tests to cover claim authorization, OpenAPI exposure, conflict handling, and submit completion mutation.
- Updated the completion audit to record the review queue/claim/submit loop as implemented.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 14 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 108 passed, 2 skipped; quality coverage 81.41% (2045/2512).
- Verified `./.venv/bin/python -m pytest -q`: 213 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: claim/submit infrastructure cannot feed real calibration until specialist annotations are submitted.
- Next: continue closing code-only gaps that do not require fabricating corpus data.

## 2026-05-08 - Pairwise calibration rows

- Extended `tools/calibrate_judges.py` with `JudgeComparisonRow` and `--judge-comparisons` JSONL input.
- Pairwise calibration now matches judge comparisons against annotation `pairwise_comparisons` and computes Cohen's kappa over `a` / `b` / `tied` labels.
- Added tests for pairwise summary metrics and CLI persistence into `judge_calibration`.
- Updated the completion audit to record pairwise calibration support as implemented.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_calibrate_judges.py`: 7 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 110 passed, 2 skipped; quality coverage 81.84% (2113/2582).
- Verified `./.venv/bin/python -m pytest -q`: 215 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: no real pairwise specialist annotations or judge comparison rows exist yet in `tools/corpus_annotations/v1`.
- Next: continue closing code-only gaps that do not require fabricating corpus data.

## 2026-05-08 - Experiment-store review sampler

- Added `sample-experiments` mode to `tools/sample_quality_reviews.py` so the review sampler can read quality-dimension experiment records directly from `ExperimentStore`.
- Added `candidates_from_experiments()` to convert stored quality scores and behavioral results into review candidates for the specialist queue.
- Added tests for experiment-derived candidates and queue writing from a SQLite experiment store.
- Updated the completion audit to record experiment-store sampling support.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_sample_quality_reviews.py`: 6 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 112 passed, 2 skipped; quality coverage 81.98% (2138/2608).
- Verified `./.venv/bin/python -m pytest -q`: 217 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: production sampling still needs real quality experiment records from traffic.
- Next: continue closing code-only gaps that do not require fabricating corpus data.

## 2026-05-08 - Interactive annotation walkthrough

- Added `tools/annotate_corpus.py annotate --interactive` so specialists can be prompted through each applicable dimension for score and notes.
- Added `--pairwise-json` and `pairwise_comparisons` support to capture better/worse/tied annotation pairs in the corpus record.
- Added tests for interactive prompt flow, invalid-score reprompting, and pairwise comparison validation.
- Updated the completion audit to record the annotation walkthrough requirement as implemented.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_annotate_corpus.py`: 8 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 115 passed, 2 skipped; quality coverage 81.92% (2189/2672).
- Verified `./.venv/bin/python -m pytest -q`: 220 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: the walkthrough is ready, but no specialist has used it to create the required v1 corpus annotations.
- Next: continue closing code-only gaps that do not require fabricating corpus data.

## 2026-05-08 - DOCX partial reading-order coverage

- Updated the shared and annotation dimension matrices so DOCX treats `reading_order` as a partial applicable dimension instead of n/a.
- Added `DOCXReadingOrderJudge`, a versioned prompt file, and `DOCXReadingOrderComprehensionTest` scaffold.
- Wired the DOCX judge/proxy into Office quality audits and updated n/a reporting expectations.
- Added tests for DOCX partial reading-order judge/proxy coverage and prompt-file presence.
- Updated the completion audit to record DOCX partial reading-order coverage.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 10 passed.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_annotate_corpus.py tests/api/test_quality_routes.py`: 22 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 115 passed, 2 skipped; quality coverage 82.08% (2217/2701).
- Verified `./.venv/bin/python -m pytest -q`: 220 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: DOCX reading-order signal remains a scaffold until calibrated parser/LLM checks can run on specialist annotations.
- Next: continue closing code-only gaps that do not require fabricating corpus data.

## 2026-05-08 - Office behavioral proxy coverage

- Added DOCX and PPTX decorative-skip proxies backed by OOXML decorative flags.
- Added a PPTX table-cell lookup proxy that inspects PowerPoint table shapes for non-empty header cells.
- Replaced the XLSX alt-text no-op proxy with an OOXML drawing parser for chart/image title and description text.
- Wired the new DOCX/PPTX proxies into `audit_office_quality()` and updated Office behavioral tests.
- Updated the completion audit to record DOCX/PPTX decorative-skip, PPTX table-cell, and XLSX drawing alt-text proxy coverage.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 14 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 119 passed, 2 skipped; quality coverage 82.58% (2403/2910).
- Verified `./.venv/bin/python -m pytest -q`: 224 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: decorative-skip remains a deterministic OOXML signal until transcript-based behavioral comparisons are calibrated against specialist annotations.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Office transcript-analysis advisory proxy

- Added best-effort Office screen-reader transcript analyzers for DOCX, PPTX, and XLSX, backed by existing `office_acceptance` screen-reader checks.
- Wired the advisory transcript analyzers into `audit_office_quality()` without letting them override judge/proxy precedence.
- Added tests proving Office transcript analysis emits advisory findings and appears in Office audit behavioral output.
- Updated the completion audit to record PDF + Office transcript-analysis coverage.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 15 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 120 passed, 2 skipped; quality coverage 82.76% (2438/2946).
- Verified `./.venv/bin/python -m pytest -q`: 225 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: Office transcript analysis is still a best-effort simulation, not a calibrated actual TTS transcript.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Snapshot capture test hardening

- Added tests for `tools/capture_corpus_snapshots.py` covering capture orchestration, missing-source failures, and CLI snapshot writing from valid annotations.
- Improved quality-layer coverage and removed the previous low-file warning for the snapshot capture tool.
- Updated the completion audit with the latest coverage and full-suite counts.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_capture_corpus_snapshots.py`: 6 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 123 passed, 2 skipped; quality coverage 84.49% (2489/2946).
- Verified `./.venv/bin/python -m pytest -q`: 228 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Gap: snapshot capture still cannot satisfy byte-identical regression gates until annotated corpus artifacts exist.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Quality endpoint auth hardening

- Added a quality-route test proving the shared `X-API-Key` dependency rejects missing/wrong keys and allows the configured key.
- Updated the completion audit to record endpoint auth coverage.
- Verified `./.venv/bin/python -m pytest -q tests/api/test_quality_routes.py`: 15 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 124 passed, 2 skipped; quality coverage 84.49% (2489/2946).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 229 passed, 2 skipped, 5 warnings.
- Gap: endpoint auth coverage does not resolve corpus/calibration/snapshot phase-exit blockers.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Office link-text judge signals

- Added shared OOXML link extraction for DOCX, PPTX, and XLSX quality judges.
- Replaced inert Office link-text judge scaffolds with deterministic scoring that flags generic or raw-URL link text.
- Added minimal DOCX/PPTX/XLSX relationship fixtures proving link text and targets are resolved correctly.
- Updated the completion audit to record Office OOXML link-text signal coverage.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 10 passed.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 18 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 127 passed, 2 skipped; quality coverage 84.57% (2626/3105).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 232 passed, 2 skipped, 5 warnings.
- Gap: Office link-text scoring is deterministic and still requires specialist-calibrated judge agreement before active deployment.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Office decorative judge signals

- Added shared OOXML decorative-flag scoring for DOCX and PPTX quality judges.
- Replaced inert DOCX/PPTX decorative judge scaffolds with deterministic checks that flag decorative objects carrying accessible text.
- Added DOCX/PPTX decorative OOXML fixtures for quality-judge coverage.
- Updated the completion audit to record Office decorative-flag judge signals.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 12 passed.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 20 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 129 passed, 2 skipped; quality coverage 84.65% (2659/3141).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 234 passed, 2 skipped, 5 warnings.
- Gap: decorative scoring is still deterministic and requires specialist-calibrated agreement before active deployment.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - XLSX alt-text judge signal

- Replaced the inert XLSX alt-text quality judge with scoring over drawing OOXML title/description fields.
- Added a worksheet drawing fixture proving missing image/chart text is surfaced as an `alt_text` quality finding.
- Updated the completion audit to distinguish XLSX drawing alt-text judge/proxy coverage.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 13 passed.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 21 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 130 passed, 2 skipped; quality coverage 84.71% (2670/3152).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 235 passed, 2 skipped, 5 warnings.
- Gap: XLSX alt-text scoring still needs specialist calibration before it can satisfy Phase H exit criteria.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PPTX table-structure judge signal

- Replaced the inert PPTX table-structure judge with scoring over PowerPoint table shapes.
- Reused the table-cell lookup parser to flag data columns whose header cells are empty.
- Added a generated PPTX fixture proving empty table headers surface as `table_structure` quality findings.
- Updated the completion audit to record PPTX table-shape quality judge coverage.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 14 passed.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 22 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 131 passed, 2 skipped; quality coverage 84.79% (2682/3163).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 236 passed, 2 skipped, 5 warnings.
- Gap: PPTX table scoring still needs specialist calibration and corpus regression before Phase H can exit.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Office complex-content judge signals

- Added shared OOXML complex-content scoring for DOCX, PPTX, and XLSX objects that look like charts, graphs, diagrams, equations, plots, models, or tables.
- Replaced inert Office complex-content judge scaffolds with a conservative data-level-description check.
- Added DOCX/PPTX/XLSX fixtures proving thin chart/diagram descriptions are surfaced as `complex_content` findings.
- Updated the completion audit to record Office complex-content judge signals.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 17 passed.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 25 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 134 passed, 2 skipped; quality coverage 85.00% (2771/3260).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 239 passed, 2 skipped, 5 warnings.
- Gap: complex-content scoring remains heuristic and still requires specialist calibration and corpus regression.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - DOCX/PPTX OOXML alt-text judge signals

- Added shared OOXML alt-text extraction for DOCX and PPTX drawing metadata.
- Updated DOCX/PPTX alt-text judges to use OOXML title/description scoring when available and fall back to existing checker reports otherwise.
- Added DOCX/PPTX fixtures proving missing drawing alt text surfaces as `alt_text` quality findings.
- Updated the completion audit to record OOXML/checker alt-text judge coverage for DOCX and PPTX.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 19 passed.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 27 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 136 passed, 2 skipped; quality coverage 85.14% (2859/3358).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 241 passed, 2 skipped, 5 warnings.
- Gap: DOCX/PPTX alt-text scoring still needs specialist calibration before it can satisfy Phase H exit criteria.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PPTX shape-order reading-order signal

- Added shared PPTX reading-order signal extraction over `python-pptx` shape order.
- Updated the PPTX reading-order judge and behavioral proxy to flag slides where the title is not the first semantic object.
- Added generated PPTX fixtures proving title-after-body ordering surfaces as `reading_order` findings while parser-unavailable fallback remains advisory.
- Updated the completion audit with the parser-backed PPTX shape-order signal and current verification results.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 29 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 138 passed, 2 skipped; quality coverage 85.44% (2916/3413).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 243 passed, 2 skipped, 5 warnings.
- Gap: PPTX shape-order scoring is still a deterministic partial signal and needs specialist calibration and corpus regression before Phase H can exit.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - XLSX Excel Table structure signal

- Added an `openpyxl`-backed XLSX table-structure signal for data ranges, Excel Tables, header cells, banded rows, and total rows.
- Updated the XLSX table-cell behavioral proxy to prefer parser-backed workbook signals while preserving the existing checker fallback for synthetic reports.
- Updated the XLSX table-structure judge to surface per-criterion table presence, header-row, banding, and total-row signals.
- Added XLSX workbook fixtures proving plain data ranges and empty table headers produce `table_structure` findings.
- Updated the completion audit with the parser-backed XLSX table signal and current verification results.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 33 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 142 passed, 2 skipped; quality coverage 85.43% (3014/3528).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 247 passed, 2 skipped, 5 warnings.
- Gap: XLSX table scoring still needs specialist calibration and corpus regression before Phase H can exit.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - XLSX sheet organization content signal

- Added workbook-content-aware XLSX sheet-navigation signals over `openpyxl` tabs and sampled sheet content terms.
- Updated the XLSX sheet-navigation behavioral proxy and sheet-organization judge to flag default sheet names, hidden data sheets, and names whose purpose does not align with sheet contents.
- Added XLSX workbook fixtures proving content-aware sheet-purpose findings are surfaced.
- Updated the completion audit with the strengthened XLSX sheet organization signal and current verification results.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 35 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 144 passed, 2 skipped; quality coverage 85.63% (3076/3592).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 249 passed, 2 skipped, 5 warnings.
- Gap: XLSX sheet organization still needs specialist calibration and corpus regression before Phase H can exit.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Behavioral failure dimension normalization

- Fixed dimension-aware failure analysis to normalize Office-style behavioral test names back to quality dimensions.
- Covered `slide_reading_order_comprehension`, `slide_title_navigation`, `sheet_navigation`, and `screen_reader_transcript_analysis` in proposer regression tests.
- Updated the completion audit to record normalized behavioral failure evidence.
- Verified `./.venv/bin/python -m pytest -q tests/vision_planner/test_proposer_dimension_aware.py tests/vision_planner/test_quality_evaluation.py`: 16 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 145 passed, 2 skipped; quality coverage 85.63% (3076/3592).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 250 passed, 2 skipped, 5 warnings.
- Gap: Phase G still needs annotated corpus holdout runs and controlled A/B lift before it can exit.
- Next: rerun corpus, snapshot, and calibration readiness gates; remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Non-Kimi quality model configuration docs

- Documented two viable separated quality-layer model setups in README configuration notes.
- Updated the completion audit to include the non-Kimi judge and behavioral model setup evidence.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 145 passed, 2 skipped; quality coverage 85.63% (3076/3592).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 250 passed, 2 skipped, 5 warnings.
- Gap: runtime calibration gates still require specialist corpus annotations and judge agreement measurements.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Review queue deduplication

- Hardened `tools/sample_quality_reviews.py` so repeated sampling does not append duplicate open review items for the same format/doc_id.
- Preserved completed items as eligible for future resampling rounds.
- Added sampler regression coverage for open-item deduplication.
- Updated the completion audit with deduplicated queue evidence.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_sample_quality_reviews.py`: 7 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 146 passed, 2 skipped; quality coverage 85.66% (3099/3618).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 251 passed, 2 skipped, 5 warnings.
- Gap: the sampling loop still cannot satisfy its Phase F exit criterion without an actual specialist verdict round.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Rolling calibration drift alerts

- Added `--rolling-window` support to `tools/calibrate_judges.py` so drift alerts can evaluate recent stored calibration rows plus the current run.
- Emitted weighted rolling-window kappa alerts with window start/end and measurement counts.
- Added calibration tests for rolling-window alert construction, store-row round trips, and CLI alert output.
- Updated the completion audit with rolling drift alert evidence.
- Verified `./.venv/bin/python -m pytest -q tests/corpus/test_calibrate_judges.py`: 10 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 149 passed, 2 skipped; quality coverage 85.66% (3125/3648).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 254 passed, 2 skipped, 5 warnings.
- Gap: calibration still cannot pass or prove judge agreement until specialist annotations and judge-result rows exist.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Held-out A/B aggregation guard

- Added `evaluate_holdout_ab()` to aggregate per-document holdout quality scores before applying Phase G promotion criteria.
- Added a guard that rejects baseline or candidate result rows outside the declared holdout set to prevent holdout contamination.
- Added Phase G tests for common-document aggregation and non-holdout result rejection.
- Updated the completion audit with held-out A/B aggregation evidence.
- Verified `./.venv/bin/python -m pytest -q tests/vision_planner/test_quality_evaluation.py tests/vision_planner/test_proposer_dimension_aware.py`: 18 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 149 passed, 2 skipped; quality coverage 85.66% (3125/3648).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 256 passed, 2 skipped, 5 warnings.
- Gap: Phase G still needs real annotated holdout runs and at least three controlled A/B lifts before success criteria can pass.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Shared link-text descriptiveness helper

- Added `quality_judges/shared/link_text.py` for common generic/raw-URL link text detection.
- Updated Office link scoring to use the shared predicate.
- Updated the PDF link-text judge to flag raw URL text and generic labels instead of relying on length alone.
- Added PDF judge regression coverage for raw URL and generic link text.
- Updated the completion audit with the shared PDF/Office link-text evidence.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py`: 31 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 150 passed, 2 skipped; quality coverage 85.70% (3129/3651).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 257 passed, 2 skipped, 5 warnings.
- Gap: PDF link-text scoring remains deterministic and still needs specialist calibration before Phase C can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - DOCX table-structure parser signal

- Added `python-docx` table summaries for DOCX table-cell lookup and table-structure judging.
- Flagged missing repeated header rows, empty header cells, and undersized tables with parser-backed findings.
- Preserved the existing checker fallback for synthetic/nonexistent artifact paths.
- Added generated DOCX table fixtures for missing repeated headers and empty header cells.
- Updated the completion audit with the parser-backed DOCX table signal.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 38 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 153 passed, 2 skipped; quality coverage 85.68% (3194/3728).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 260 passed, 2 skipped, 5 warnings.
- Gap: DOCX table scoring still needs specialist calibration and corpus regression before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - DOCX heading-outline parser signal

- Added `python-docx` heading outline extraction for DOCX heading-navigation behavioral tests.
- Updated the DOCX heading-semantics judge to score skipped heading levels from Word styles and outline levels.
- Preserved the existing checker fallback for synthetic/nonexistent artifact paths.
- Added generated DOCX heading fixtures proving skipped Word heading levels surface as `heading_semantics` findings.
- Updated the completion audit with the parser-backed DOCX heading signal.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 40 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 155 passed, 2 skipped; quality coverage 85.39% (3244/3799).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 262 passed, 2 skipped, 5 warnings.
- Gap: DOCX heading scoring still needs specialist calibration and corpus regression before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PPTX slide-title parser signal

- Added shared `python-pptx` slide-title signals for missing title placeholders, empty/non-descriptive titles, and duplicate slide titles.
- Updated the PPTX slide-title behavioral proxy and quality judge to use parser-backed per-slide title quality when artifacts exist.
- Preserved the existing checker fallback for synthetic/nonexistent artifact paths.
- Added generated PPTX fixtures proving duplicate and generic slide titles surface as `slide_title` findings.
- Updated the completion audit with the parser-backed PPTX slide-title signal.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 42 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 157 passed, 2 skipped; quality coverage 85.37% (3320/3889).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 264 passed, 2 skipped, 5 warnings.
- Gap: PPTX slide-title scoring still needs specialist calibration and corpus regression before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PPTX heading semantics parser signal

- Updated the PPTX heading-semantics judge to use shared `python-pptx` slide-title signals for real artifacts.
- Scored missing/empty/non-descriptive title placeholders as heading navigation failures while preserving checker fallback for synthetic reports.
- Added a generated PPTX fixture proving missing slide-title placeholders surface as `heading_semantics` findings.
- Updated the completion audit with parser-backed PPTX heading/title semantics evidence.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 43 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 158 passed, 2 skipped; quality coverage 85.45% (3337/3905).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 265 passed, 2 skipped, 5 warnings.
- Gap: PPTX heading semantics still needs specialist calibration and corpus regression before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - DOCX/PPTX alt-text behavioral OOXML signal

- Added OOXML alt-text helpers for Office behavioral proxies.
- Updated DOCX and PPTX alt-text substitution proxies to read drawing metadata when artifacts exist and keep checker fallback for synthetic reports.
- Added DOCX/PPTX OOXML fixtures proving missing drawing alt text surfaces as behavioral `alt_text` findings.
- Updated the completion audit with parser-backed DOCX/PPTX alt-text proxy evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py`: 45 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 160 passed, 2 skipped; quality coverage 85.52% (3409/3986).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 267 passed, 2 skipped, 5 warnings.
- Gap: Office alt-text behavioral scoring still needs specialist corpus regression before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PDF behavioral proxy tightening

- Tightened deterministic PDF proxy signals for duplicate figure alt text, empty headings, table structures with no data cells, and page-order backtracking in screen-reader traversal.
- PDF quality judges inherit these stricter proxy scores for alt text, heading semantics, table structure, and reading order.
- Added focused PDF behavioral regression tests for each new signal.
- Updated the completion audit with the tightened PDF proxy evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py`: 18 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 164 passed, 2 skipped; quality coverage 85.60% (3430/4007).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 271 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: PDF behavioral and judge scoring remains deterministic and still needs specialist corpus calibration before Phase B/C can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Judge-version calibration gate hardening

- Added `quality_judges/shared/registry.py` as the current judge-version registry for PDF, DOCX, PPTX, and XLSX calibration requirements.
- Updated `backend/app/quality_calibration.py` so active quality execution requires every current judge ID and judge version for the requested format, not just one row per dimension.
- Added route and registry tests proving stale judge versions do not satisfy the quality audit gate.
- Updated the completion audit with the stricter per-judge calibration evidence.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/shared/test_registry.py tests/api/test_quality_routes.py`: 18 passed.
- Verified `./.venv/bin/python -m pytest -q tests/test_engine_quality_opt_in.py`: 5 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 167 passed, 2 skipped; quality coverage 85.50% (3473/4062).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 274 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: calibration cannot pass until specialist annotation artifacts and judge-result rows exist.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PDF answer-retention proxy hook

- Added `behavioral_proxies/shared/llm_answering.py` for injectable independent-answerer retention scoring over baseline and candidate contexts.
- Updated the PDF reading-order comprehension proxy to use answer-retention scoring when an answerer is supplied, while preserving deterministic fallback when no answerer is configured.
- Added PDF behavioral tests for successful answer retention and retained-answer loss findings.
- Updated the completion audit with the injectable PDF answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py`: 20 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 169 passed, 2 skipped; quality coverage 85.59% (3522/4115).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 276 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the answer-retention path still needs real independent-model execution and corpus calibration before Phase B can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PPTX per-slide answer-retention proxy hook

- Extended PPTX slide reading-order signals with serialized per-slide text.
- Updated `PPTXSlideReadingOrderComprehensionTest` to run injected answer-retention scoring per slide when an independent answerer is supplied, while preserving parser-only fallback by default.
- Added generated PPTX behavioral tests for retained per-slide answers and answer-retention loss findings.
- Updated the completion audit with the per-slide PPTX answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 20 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_registry.py tests/api/test_quality_routes.py`: 45 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 171 passed, 2 skipped; quality coverage 85.52% (3560/4163).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 278 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the per-slide answer-retention path still needs real independent-model execution and corpus calibration before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - DOCX linear answer-retention proxy hook

- Updated `DOCXReadingOrderComprehensionTest` to run injected answer-retention scoring over linear Word paragraph/table text when an independent answerer is supplied.
- Preserved the existing partial DOCX reading-order scaffold when no answerer is supplied.
- Added generated DOCX behavioral tests for retained linear text answers and answer-retention loss findings.
- Updated the completion audit with DOCX answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 22 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 49 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 173 passed, 2 skipped; quality coverage 85.36% (3585/4200).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 280 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: DOCX answer retention still needs real independent-model execution and corpus calibration before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PDF table lookup answer-retention proxy hook

- Added simple PDF tag-tree table serialization and deterministic lookup-question generation for row/column cell values.
- Updated the PDF table-cell lookup proxy to run injected answer-retention scoring when an independent answerer is supplied, while preserving structural fallback by default.
- Added PDF behavioral tests for retained table-cell answers and answer-retention loss findings.
- Updated the completion audit with PDF table answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py`: 22 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 175 passed, 2 skipped; quality coverage 85.42% (3637/4258).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 282 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: PDF table lookup answer retention still needs real independent-model execution and corpus calibration before Phase B can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PDF alt-text answer-retention proxy hook

- Updated the PDF alt-text substitution proxy to run injected answer-retention scoring when baseline visual-context text and an independent answerer are supplied.
- Preserved the existing deterministic alt-text quality fallback when no answerer is supplied.
- Added PDF behavioral tests for retained alt-text answers and answer-retention loss despite meaningful-looking alt text.
- Updated the completion audit with PDF alt-text answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py`: 24 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 177 passed, 2 skipped; quality coverage 85.45% (3648/4269).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 284 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: PDF alt-text answer retention still needs real independent-model execution and corpus calibration before Phase B can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Office alt-text answer-retention proxy hooks

- Updated shared DOCX/PPTX OOXML alt-text behavioral scoring to run injected answer-retention checks when baseline visual-context text and an independent answerer are supplied.
- Updated XLSX drawing alt-text behavioral scoring with the same optional answer-retention path.
- Preserved default deterministic alt-text fallback behavior for Office audits without an injected answerer.
- Added Office behavioral tests for DOCX retained alt-text answers, PPTX answer-retention loss, and XLSX retained alt-text answers.
- Updated the completion audit with Office alt-text answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 25 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 27 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 180 passed, 2 skipped; quality coverage 85.54% (3673/4294).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 287 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: Office alt-text answer retention still needs real independent-model execution and corpus calibration before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - DOCX table lookup answer-retention proxy hook

- Extended DOCX table summaries with parsed cell text.
- Updated the DOCX table-cell lookup proxy to generate row/column lookup questions and run injected answer-retention scoring when an independent answerer is supplied.
- Preserved existing parser-backed structural table scoring when no answerer is supplied.
- Added generated DOCX behavioral tests for retained table-cell answers and answer-retention loss findings.
- Updated the completion audit with DOCX table-cell answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 27 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 27 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 182 passed, 2 skipped; quality coverage 85.58% (3709/4334).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 289 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: DOCX table lookup answer retention still needs real independent-model execution and corpus calibration before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PPTX table lookup answer-retention proxy hook

- Extended PPTX table summaries with parsed table cell text.
- Updated the PPTX table-cell lookup proxy to generate slide/table row-column lookup questions and run injected answer-retention scoring when an independent answerer is supplied.
- Preserved existing parser-backed table-shape structural scoring when no answerer is supplied.
- Added generated PPTX behavioral tests for retained table-cell answers and answer-retention loss findings.
- Updated the completion audit with PPTX table-cell answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 29 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 27 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 184 passed, 2 skipped; quality coverage 85.60% (3744/4374).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 291 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: PPTX table lookup answer retention still needs real independent-model execution and corpus calibration before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - XLSX table lookup answer-retention proxy hook

- Extended XLSX table/data-region signals with parsed worksheet cell text.
- Updated the XLSX table-cell lookup proxy to generate table row-column lookup questions and run injected answer-retention scoring when an independent answerer is supplied.
- Preserved existing openpyxl structural table scoring when no answerer is supplied.
- Added generated XLSX behavioral tests for retained table-cell answers and answer-retention loss findings.
- Updated the completion audit with XLSX table-cell answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 31 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 27 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 186 passed, 2 skipped; quality coverage 85.69% (3785/4417).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 293 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: XLSX table lookup answer retention still needs real independent-model execution and corpus calibration before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PDF heading-navigation answer-retention proxy hook

- Updated the PDF heading navigation proxy to generate heading-location questions from body content and run injected answer-retention scoring against the heading outline when an independent answerer is supplied.
- Preserved existing deterministic heading outline scoring when no answerer is supplied.
- Added PDF behavioral tests for retained heading-location answers and answer-retention loss findings.
- Updated the completion audit with PDF heading-navigation answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py`: 26 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 188 passed, 2 skipped; quality coverage 85.77% (3816/4449).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 295 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: PDF heading-navigation answer retention still needs real independent-model execution and corpus calibration before Phase B can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Office heading/title answer-retention proxy hooks

- Updated DOCX heading navigation to generate body-content-to-heading questions and run injected answer-retention scoring against the Word heading outline.
- Updated PPTX slide-title navigation to generate body-content-to-slide-title questions and run injected answer-retention scoring against the title list.
- Preserved existing parser-only heading/title scoring when no answerer is supplied.
- Added generated DOCX/PPTX behavioral tests for retained navigation answers and answer-retention loss findings.
- Updated the completion audit with Office heading/title answer-retention evidence.
- Verified `./.venv/bin/python -m pytest -q tests/behavioral_proxies/office/test_office_behavioral_proxies.py`: 35 passed.
- Verified `./.venv/bin/python -m pytest -q tests/quality_judges/office/test_office_judges.py`: 27 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 192 passed, 2 skipped; quality coverage 85.79% (3887/4531).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 299 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: Office heading/title answer retention still needs real independent-model execution and corpus calibration before Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Decorative-skip answer-retention proxy hooks

- Updated PDF decorative-skip scoring to support injected answer-retention checks comparing baseline visual context against the candidate transcript after skipped decorative figures are removed.
- Updated shared DOCX/PPTX decorative-skip scoring to support injected information-equivalence answer-retention checks while preserving the OOXML decorative-flag fallback.
- Added PDF, DOCX, and PPTX behavioral tests for retained decorative-context answers and answer-retention loss findings.
- Updated the completion audit with decorative-skip answer-retention evidence.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py -q`: 20 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 37 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 196 passed, 2 skipped; quality coverage 85.95% (3920/4561).
- Verified `./.venv/bin/python -m pytest -q`: 303 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: decorative-skip answer retention still needs real independent-model execution and corpus calibration before Phase B/Phase H can exit.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Judge prompt artifact tracking guard

- Updated `.gitignore` to unignore `BUILD_LOG.md`, `v2_docs/*.md`, and `src/project_remedy/quality_judges/**/prompts/*.md` so quality docs and judge prompts can be committed as versioned artifacts.
- Added a shared quality-judge registry test that verifies prompt Markdown files are not ignored by Git, closing the gap where prompt existence tests passed even though the files were not trackable.
- Updated the completion audit with prompt trackability evidence.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_registry.py tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py -q`: 38 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 197 passed, 2 skipped; quality coverage 85.95% (3920/4561).
- Verified `./.venv/bin/python -m pytest -q`: 304 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: prompt trackability is fixed, but judge calibration still requires specialist annotation artifacts and judge-result rows.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Behavioral prompt artifact scaffolding

- Added shared behavioral prompt artifacts for question generation, answer-retention scoring, navigation accuracy, table lookup, and decorative transcript equivalence under `src/project_remedy/behavioral_proxies/shared/prompts/`.
- Updated `.gitignore` to unignore behavioral prompt Markdown so the prompt/rubric surface can be committed alongside code.
- Added a behavioral shared test that verifies the prompt set exists, includes JSON-return instructions, and is not ignored by Git.
- Updated the completion audit with behavioral prompt artifact evidence.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_behavioral_model_separation.py tests/quality_judges/shared/test_registry.py -q`: 12 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 198 passed, 2 skipped; quality coverage 85.95% (3920/4561).
- Verified `./.venv/bin/python -m pytest -q`: 305 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: behavioral prompt artifacts are trackable, but behavioral proxy corpus discrimination still cannot be proven without known-good/known-bad specialist corpus entries.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Source artifact ignore guard

- Updated `.gitignore` to unignore Python source files under `src/`, `backend/`, and `tools/` so source modules are not hidden by broad seed-repo `test_*.py` or `*_test.py` ignore rules.
- Added a behavioral shared test guarding the PRD-named `src/project_remedy/behavioral_proxies/pdf/decorative_skip_test.py` source module against being ignored by Git.
- Confirmed `rg --files src/project_remedy/behavioral_proxies/pdf` now includes `decorative_skip_test.py`.
- Updated the completion audit with source-file trackability evidence.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_behavioral_model_separation.py tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py -q`: 30 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 199 passed, 2 skipped; quality coverage 85.95% (3920/4561).
- Verified `./.venv/bin/python -m pytest -q`: 306 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: source trackability is fixed, but Phase A/B/C/H exit criteria still require specialist corpus artifacts and calibration data.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Quality artifact tracking coverage

- Added `tests/corpus/test_quality_artifact_tracking.py` to verify that quality-layer source files, prompt Markdown, corpus schema/manifest, v2 docs, build log, quality route files, tools, and dimension strategy map are not ignored by Git.
- Verified a direct ignored-artifact scan across the quality-layer paths produces no ignored source artifacts beyond expected cache directories.
- Updated the completion audit with artifact-tracking test evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_artifact_tracking.py tests/behavioral_proxies/shared/test_behavioral_model_separation.py tests/quality_judges/shared/test_registry.py -q`: 14 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 200 passed, 2 skipped; quality coverage 85.95% (3920/4561).
- Verified `./.venv/bin/python -m pytest -q`: 307 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: artifact tracking is now guarded, but phase exit criteria still require real specialist corpus, snapshots, calibration, and held-out A/B evidence.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Calibration threshold aligned to final success criterion

- Updated the active quality calibration gate default from Cohen's kappa 0.7 to 0.8 to match the PRD's final success criterion per judge x dimension x format.
- Updated `.env.example` and `tools/calibrate_judges.py --kappa-threshold` default to 0.8 so deployment gating and drift alerting use the same threshold.
- Updated route/calibration tests to seed passing calibration rows at kappa 0.8 and assert the shared CLI threshold constant.
- Updated the completion audit to distinguish the phase floor from the final active success threshold.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py tests/api/test_quality_routes.py -q`: 26 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 200 passed, 2 skipped; quality coverage 85.95% (3921/4562).
- Verified `./.venv/bin/python -m pytest -q`: 307 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the stricter threshold is enforced by default, but there are still no specialist calibration rows to satisfy it.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Office nested annotation schema and CLI support

- Tightened `tools/corpus_annotations/schema.json` so PPTX `per_slide` and XLSX `per_sheet` entries have structured annotation schemas instead of unconstrained objects.
- Added `tools/annotate_corpus.py` parsing for repeated `--per-slide-json` and `--per-sheet-json` arguments.
- Extended annotation validation to enforce nested Office applicable dimensions, dimension score presence, score range, and format applicability.
- Added corpus tests for PPTX per-slide CLI annotations and XLSX per-sheet applicability validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 10 passed.
- Verified `./.venv/bin/python -m json.tool tools/corpus_annotations/schema.json`.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 202 passed, 2 skipped; quality coverage 85.75% (3970/4630).
- Verified `./.venv/bin/python -m pytest -q`: 309 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: Office annotation structure is ready, but no specialist has populated the required v1 corpus.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Corpus source/gold artifact coverage gate

- Extended corpus coverage summaries with `artifact_errors` for annotation records whose `source_path` is missing or whose `gold_remediation_path` is empty/missing.
- Updated Phase A coverage evaluation to fail records that lack source or gold remediation artifacts, matching the PRD's requirement that corpus annotations reference first-class source/gold artifacts.
- Added tests proving Phase A can pass with existing source/gold artifacts and fails when those references are absent.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 11 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 203 passed, 2 skipped; quality coverage 85.74% (3994/4658).
- Verified `./.venv/bin/python -m pytest -q`: 310 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the coverage gate now enforces source/gold artifact references, but no specialist corpus artifacts exist yet.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Shared quality rubric artifacts

- Added version-controlled shared rubric YAML files under `src/project_remedy/quality_judges/shared/rubrics/` for every quality dimension.
- Added `quality_judges/shared/rubric_loader.py` for loading rubric criteria and format applicability.
- Added tests proving rubric coverage for all dimensions, applicability alignment with the dimension matrix, and Git trackability of rubric artifacts.
- Updated artifact tracking coverage to include shared rubric YAML files.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_rubrics.py tests/corpus/test_quality_artifact_tracking.py -q`: 4 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 206 passed, 2 skipped; quality coverage 85.75% (4021/4689).
- Verified `./.venv/bin/python -m pytest -q`: 313 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: rubric artifacts are present and trackable, but real calibration still requires specialist annotation and judge-result rows.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Rubric-backed criterion enforcement

- Added `QualityDimensionScore` validation so emitted `per_criterion` keys must exist in the corresponding versioned shared rubric.
- Extended shared rubrics with the current deterministic/proxy criterion IDs emitted by PDF and Office judges, including XLSX table and sheet-organization criteria.
- Added regression tests that reject unknown criterion keys and assert current proxy criterion IDs are rubric-backed.
- Updated the completion audit with rubric-backed criterion enforcement evidence.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_rubrics.py tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py -q`: 40 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 208 passed, 2 skipped; quality coverage 85.75% (4032/4702).
- Verified `./.venv/bin/python -m pytest -q`: 315 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: rubric emission is now guarded, but real calibration still requires specialist annotations, source/gold artifacts, snapshots, and judge-result rows.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Default-flow snapshot gate tightening

- Tightened `tools/verify_corpus_snapshots.py` so committed default-flow snapshots must include the annotated source path, the PRD-required endpoint for the format, a non-empty job id, and `final_job_status=done`.
- Added snapshot gate tests rejecting Office snapshots captured against the wrong default endpoint and incomplete job snapshots.
- Updated snapshot capture tests so generated payloads carry the stricter verifier metadata.
- Updated the completion audit with stronger byte-identical snapshot evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py tests/corpus/test_capture_corpus_snapshots.py -q`: 10 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 43 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 210 passed, 2 skipped; quality coverage 85.79% (4039/4708).
- Verified `./.venv/bin/python -m pytest -q`: 317 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the snapshot verifier now checks stronger default-flow evidence, but no specialist corpus entries or live snapshots exist to satisfy the PRD's corpus-wide byte-identical requirement.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Behavioral cloze question generation

- Replaced generic deterministic "source sentence" behavioral questions with answer-targeted cloze questions in `behavioral_proxies/shared/question_generator.py`.
- Added shared question-generator tests for numeric/timeframe answer spans and fallback detail spans.
- Verified PDF and Office behavioral proxies still pass with the stricter shared question output.
- Updated the completion audit with cloze-style behavioral question evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_question_generator.py tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 59 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 212 passed, 2 skipped; quality coverage 85.80% (4059/4731).
- Verified `./.venv/bin/python -m pytest -q`: 319 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: deterministic question generation is stronger, but PRD behavioral proxy success still requires specialist corpus gold/known-bad discrimination and independent-model runs.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Judge prompt registry guard

- Added a registry test that maps every required judge calibration entry to its exact versioned prompt Markdown file.
- The guard also rejects extra prompt files that are not represented in the active calibration registry, keeping prompt artifacts aligned with deployed judge versions.
- Updated the completion audit with prompt-to-registry evidence.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_registry.py tests/quality_judges/shared/test_rubrics.py -q`: 9 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 213 passed, 2 skipped; quality coverage 85.80% (4059/4731).
- Verified `./.venv/bin/python -m pytest -q`: 320 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: prompt artifacts are now tightly registry-backed, but judge calibration still requires specialist annotation and judge-result rows.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Holdout promotion completeness guard

- Tightened Phase G promotion evaluation so a strategy cannot be promoted if candidate holdout results omit any non-target dimension present in baseline scores.
- Added regression coverage for missing non-target scores, preventing incomplete holdout results from satisfying the no-regression rule.
- Updated the completion audit with the stricter promotion-criteria evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py tests/vision_planner/test_proposer_dimension_aware.py -q`: 19 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 213 passed, 2 skipped; quality coverage 85.80% (4059/4731).
- Verified `./.venv/bin/python -m pytest -q`: 321 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: Phase G promotion criteria are guarded locally, but the PRD still requires real held-out A/B lift evidence on annotated corpus documents.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Review sampler queued status

- Added explicit `status=queued` to review items emitted by `tools/sample_quality_reviews.py` so JSONL queue lifecycle state is present before claim/submit mutation.
- Updated sampler tests to assert queued status and verified existing review route tests still pass.
- Updated the completion audit with explicit queue lifecycle evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py tests/api/test_quality_routes.py -q`: 23 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 213 passed, 2 skipped; quality coverage 85.80% (4059/4731).
- Verified `./.venv/bin/python -m pytest -q`: 321 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: queue items now have an explicit lifecycle start state, but Phase F still needs a real staging/specialist verdict round.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Raw transcript analysis hooks

- Added `behavioral_proxies/shared/transcript_analysis.py` for structured raw screen-reader transcript findings, including empty transcript, repeated line, and unlabeled object announcements.
- Wired provided raw transcript text into PDF and Office transcript analyzers while preserving tag-tree and Office checker analysis.
- Added PDF, Office, and shared behavioral tests proving provided transcripts generate advisory structured findings.
- Updated the completion audit with raw transcript-analysis evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_transcript_analysis.py tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 61 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 217 passed, 2 skipped; quality coverage 85.89% (4089/4761).
- Verified `./.venv/bin/python -m pytest -q`: 325 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: transcript analyzers can now consume raw transcripts, but PRD success still requires real captured transcripts/corpus runs.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - PPTX per-slide reading-order metadata

- Improved shared PPTX reading-order signals so table shapes serialize row/cell text instead of the generic word `table`.
- Exposed per-slide object counts and serialized text in `PPTXSlideReadingOrderComprehensionTest` metadata.
- Added/finished PPTX behavioral tests for table serialization and answer-retention loss on a specific slide.
- Updated the completion audit with stronger PPTX per-slide reading-order evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py -q`: 66 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 218 passed, 2 skipped; quality coverage 85.94% (4100/4771).
- Verified `./.venv/bin/python -m pytest -q`: 326 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: PPTX per-slide structures are richer locally, but Phase H still requires corpus regression and calibration evidence.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - XLSX sheet-navigation answer retention

- Added optional injected-answerer scoring to `XLSXSheetNavigationTest`, generating sheet-selection questions from sampled workbook content terms.
- Added retained-answer and answer-retention-loss tests for XLSX sheet navigation.
- Updated the completion audit with the stronger sheet-organization behavioral proxy evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py -q`: 68 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 220 passed, 2 skipped; quality coverage 85.99% (4126/4798).
- Verified `./.venv/bin/python -m pytest -q`: 328 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: XLSX sheet-navigation behavior is now testable with an independent answerer, but Phase H still requires Office corpus regression and calibration evidence.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Conditional CI readiness enforcement

- Added a non-advisory `quality-checks` workflow step that exits cleanly while no annotations are committed, but hard-fails corpus coverage, snapshot, and calibration gates as soon as annotation JSON files exist.
- Added a corpus artifact test that verifies the workflow contains the conditional hard readiness step and that it is not marked `continue-on-error`.
- Updated the completion audit with the conditional CI gate evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_artifact_tracking.py -q`: 2 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 221 passed, 2 skipped; quality coverage 85.99% (4126/4798).
- Verified `./.venv/bin/python -m pytest -q`: 329 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: CI will now enforce readiness once corpus annotations exist, but the current workspace still has no annotations to enforce.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Phase A dimension completeness gate

- Extended corpus coverage summaries with `dimension_errors` for annotation records that omit dimensions applicable to their format.
- Updated Phase A readiness evaluation to fail records with incomplete top-level dimension coverage, preventing partial annotation rows from satisfying corpus readiness.
- Added a corpus regression test proving partial PDF annotations fail Phase A coverage even when source and gold artifacts exist.
- Updated the completion audit with the stronger Phase A annotation coverage evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py tests/corpus/test_snapshot_gate.py tests/corpus/test_capture_corpus_snapshots.py -q`: 22 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 222 passed, 2 skipped; quality coverage 86.03% (4146/4819).
- Verified `./.venv/bin/python -m pytest -q`: 330 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the corpus gate now rejects partial annotation rows, but no specialist annotation rows exist yet.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Phase G CI coverage guard

- Added `tests/vision_planner/test_quality_evaluation.py` to the quality-focused CI test list so holdout split/promotion criteria run in the quality-checks job.
- Extended the CI artifact test to guard that both Phase G proposer and holdout evaluation tests remain in the workflow.
- Updated the completion audit with the expanded CI evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_artifact_tracking.py tests/vision_planner/test_quality_evaluation.py -q`: 10 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 223 passed, 2 skipped; quality coverage 86.03% (4146/4819).
- Verified `./.venv/bin/python -m pytest -q`: 331 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: CI now runs the local Phase G holdout tests, but real held-out A/B lift still requires annotated corpus runs.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Review calibration row validation

- Tightened `POST /v1/quality/review/submit` calibration persistence so rows must use applicable format/dimension pairs, numeric kappa in range, positive sample sizes, and active judge-registry judge/version entries.
- Added API tests rejecting unregistered calibration rows and invalid calibration values before they can enter the experiment store.
- Updated the completion audit with the stricter specialist calibration submission evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 18 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 225 passed, 2 skipped; quality coverage 85.95% (4165/4846).
- Verified `./.venv/bin/python -m pytest -q`: 333 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: calibration submission is now guarded, but Phase F still needs a real specialist verdict round and generated calibration rows.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Shared result range validation

- Added internal range validation to `QualityDimensionScore` for score, variance, and confidence values.
- Added internal range validation to `BehavioralTestResult` for score, threshold, and confidence values.
- Added regression tests proving invalid quality and behavioral result values are rejected before API serialization.
- Updated the completion audit with shared result-contract evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_rubrics.py tests/behavioral_proxies/shared/test_behavioral_model_separation.py tests/quality_judges tests/behavioral_proxies -q`: 131 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 227 passed, 2 skipped; quality coverage 85.94% (4180/4864).
- Verified `./.venv/bin/python -m pytest -q`: 335 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: shared result contracts are stricter, but corpus calibration and held-out A/B evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Pairwise annotation validation hardening

- Tightened `tools/annotate_corpus.py` validation so `pairwise_comparisons` entries must include `a_path`, `b_path`, `winner`, `dimension`, and `rationale`.
- Added validation for non-empty pairwise artifact paths and string rationale values before pairwise rows can feed calibration.
- Added corpus regression coverage for incomplete pairwise comparison rows.
- Updated the completion audit with pairwise annotation validator evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py tests/corpus/test_calibrate_judges.py -q`: 23 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 228 passed, 2 skipped; quality coverage 85.98% (4189/4872).
- Verified `./.venv/bin/python -m pytest -q`: 336 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: pairwise rows are now schema-hardened, but real pairwise specialist annotations and judge comparison rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Annotation gold provenance contract

- Extended `tools/corpus_annotations/schema.json` with required annotation provenance for human-specialist gold verification.
- Updated `tools/annotate_corpus.py` so every annotation records `gold_standard_source=human_specialist`, `human_verified=true`, and optional model candidate seed metadata.
- Added corpus tests proving model-seeded candidates are only recorded as provenance and invalid non-human gold provenance is rejected.
- Tightened CLI validation to reject unknown top-level and provenance fields, matching the schema strictness that CI actually runs.
- Updated the completion audit with the provenance evidence and current verification counts.
- Verified `./.venv/bin/python -m json.tool tools/corpus_annotations/schema.json`.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 14 passed.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py tests/corpus/test_annotate_corpus.py -q`: 34 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 48 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 231 passed, 2 skipped; quality coverage 86.02% (4210/4894).
- Verified `./.venv/bin/python -m pytest -q`: 339 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the corpus now encodes human gold provenance, but no specialist annotations or gold artifacts exist yet.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Phase G controlled A/B series guard

- Added `ControlledABSuccess` and `evaluate_controlled_ab_success()` to require the PRD's three successful controlled A/B experiments before Phase G success can be claimed.
- Rejected mixed strategy/dimension series and any series with non-target regressions.
- Added Phase G tests for insufficient runs, three-run success, regression rejection, and mixed-series rejection.
- Updated the completion audit with the stricter Phase G success-criteria evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py tests/vision_planner/test_proposer_dimension_aware.py -q`: 23 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 231 passed, 2 skipped; quality coverage 86.02% (4210/4894).
- Verified `./.venv/bin/python -m pytest -q`: 343 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: Phase G success is now guarded in code, but no real held-out A/B runs exist yet.
- Next: remaining completion depends on specialist corpus artifacts and held-out run evidence.

## 2026-05-08 - Annotation format-specific strictness

- Constrained `format_specific` schema records to exactly one active format block.
- Tightened `tools/annotate_corpus.py` validation for extra format-specific blocks, duplicate/empty edge-case flags, timezone-less `annotated_at` values, and PPTX per-slide title/index requirements.
- Added corpus tests for strict format-specific metadata and PPTX per-slide annotation shape.
- Updated the completion audit with stricter schema/validator evidence.
- Verified `./.venv/bin/python -m json.tool tools/corpus_annotations/schema.json`.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py tests/api/test_quality_routes.py -q`: 36 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 51 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 233 passed, 2 skipped; quality coverage 86.02% (4241/4930).
- Verified `./.venv/bin/python -m pytest -q`: 345 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; calibration dry run reports no annotation JSON files.
- Gap: the schema is stricter, but the specialist corpus artifacts are still absent.
- Next: remaining completion depends on specialist corpus artifacts.

## 2026-05-08 - Behavioral corpus discrimination gate

- Added `tools/verify_behavioral_corpus.py` to verify the PRD's gold-vs-known-bad behavioral proxy discrimination criterion.
- The gate checks annotation records against behavioral JSONL result rows and requires gold rows to pass and known-bad rows to fail comparable behavioral tests on at least 95% of corpus entries per format.
- Wired the tool into the `quality-checks` CI compile list, advisory readiness report, and conditional hard readiness step once annotation JSON exists.
- Added corpus tests for passing discrimination, missing/non-distinguishing rows, score-threshold payloads, CLI success, and empty-corpus failure.
- Updated artifact tracking tests and the completion audit with behavioral-gate evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py tests/corpus/test_quality_artifact_tracking.py -q`: 8 passed.
- Verified `./.venv/bin/python tools/verify_behavioral_corpus.py check --root tools/corpus_annotations/v1 --results tools/corpus_annotations/v1/behavioral_results.jsonl --json` reports `ready=false` because there are no annotations or behavioral result rows.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 56 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 238 passed, 2 skipped; quality coverage 86.02% (4241/4930).
- Verified `./.venv/bin/python -m pytest -q`: 350 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: behavioral discrimination is now enforceable, but the real specialist corpus and behavioral result rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts and behavioral run evidence.

## 2026-05-08 - Enforced calibration readiness gate

- Added `calibration_readiness_errors()` and `tools/calibrate_judges.py --enforce-readiness`.
- The enforced mode fails unless every registered judge/version for annotated formats has a calibration metric meeting the configured kappa and sample thresholds.
- Updated the conditional CI readiness step to use enforced calibration readiness once annotation JSON exists.
- Added calibration tests for missing registered judge metrics, below-threshold kappa, insufficient samples, and CI workflow coverage.
- Fixed script-mode import bootstrapping so the calibration CLI can import uncommitted `src/project_remedy/quality_judges` modules directly from the source tree.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py tests/corpus/test_quality_artifact_tracking.py -q`: 15 passed.
- Verified `./.venv/bin/python tools/calibrate_judges.py calibrate --root tools/corpus_annotations/v1 --store /tmp/remedy-quality-experiments.db --dry-run --enforce-readiness --json` still reports no annotation JSON files.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 58 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 240 passed, 2 skipped; quality coverage 86.00% (4270/4965).
- Verified `./.venv/bin/python -m pytest -q`: 352 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: calibration readiness is now enforced, but no real specialist annotation or judge-result rows exist yet.
- Next: remaining completion depends on specialist corpus artifacts and calibration evidence.

## 2026-05-08 - Snapshot source hash binding

- Added `source_sha256` to default-flow snapshot capture payloads so snapshot records are bound to the annotated source artifact bytes.
- Tightened `tools/verify_corpus_snapshots.py` to require a SHA-256 source hash and compare it with `source_path` when the artifact exists.
- Added snapshot-gate coverage for source hash mismatch and updated capture fixtures to emit verifier-compatible source hashes.
- Updated the completion audit with the stronger snapshot evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py tests/corpus/test_capture_corpus_snapshots.py -q`: 11 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 59 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 241 passed, 2 skipped; quality coverage 86.02% (4284/4980).
- Verified `./.venv/bin/python -m pytest -q`: 353 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports missing annotations/results; calibration dry run reports no annotation JSON files.
- Gap: snapshot evidence is stricter, but no specialist corpus entries or live default-flow snapshots exist yet.
- Next: remaining completion depends on specialist corpus artifacts and snapshot evidence.

## 2026-05-08 - Known-bad corpus artifact traceability

- Added `known_bad_artifact_paths` to the corpus annotation schema and annotation builder/CLI, with validation for list shape, duplicate paths, and empty path values.
- Tightened `tools/verify_behavioral_corpus.py` so root-backed behavioral checks require annotation-linked known-bad artifact references to resolve before accepting gold-vs-known-bad discrimination rows.
- Added corpus tests for known-bad annotation validation, missing known-bad artifact references, existing known-bad artifact references, and CLI behavioral-gate success with known-bad artifacts.
- Updated the completion audit with the stronger known-bad evidence requirement.
- Verified `./.venv/bin/python -m json.tool tools/corpus_annotations/schema.json`.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py tests/corpus/test_behavioral_corpus_gate.py -q`: 25 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 62 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 244 passed, 2 skipped; quality coverage 86.06% (4296/4992).
- Verified `./.venv/bin/python -m pytest -q`: 356 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral discrimination evidence is now artifact-traceable, but the real specialist corpus, known-bad artifacts, and behavioral result rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts and behavioral run evidence.

## 2026-05-08 - Corpus annotation artifact hash binding

- Added required `artifact_hashes` metadata to corpus annotations for source, gold remediation, and known-bad artifacts.
- Updated `tools/annotate_corpus.py` to auto-compute artifact hashes for existing paths and to reject malformed hash metadata.
- Made `write_annotation_record()` validate records before creating annotation files or manifest rows, so callers cannot bypass the schema contract by skipping the builder.
- Tightened Phase A corpus coverage so existing source/gold artifacts must match their recorded annotation hashes.
- Tightened `tools/verify_behavioral_corpus.py` so known-bad artifact references must match recorded `known_bad_sha256` values before behavioral discrimination rows can pass.
- Added corpus tests for automatic artifact-hash capture, source/gold hash mismatch coverage failures, and known-bad hash mismatch behavioral failures.
- Updated the completion audit with hash-bound corpus evidence requirements.
- Verified `./.venv/bin/python -m json.tool tools/corpus_annotations/schema.json`.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py tests/corpus/test_behavioral_corpus_gate.py -q`: 29 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 66 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 19 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 248 passed, 2 skipped; quality coverage 86.02% (4339/5044).
- Verified `./.venv/bin/python -m pytest -q`: 360 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: corpus references are now hash-bound, but the real specialist corpus artifacts and result rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Corpus manifest integrity binding

- Added annotation-file SHA-256 and artifact hash metadata to manifest rows written by `write_annotation_record()`.
- Tightened corpus coverage to report manifest rows that are missing, stale, duplicated, or drifted from their annotation file metadata.
- Added a regression test that mutates a manifest artifact hash and verifies Phase A coverage fails with `manifest_mismatch_entries`.
- Updated the completion audit with manifest drift evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 22 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 67 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 19 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 249 passed, 2 skipped; quality coverage 86.00% (4368/5079).
- Verified `./.venv/bin/python -m pytest -q`: 361 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: manifest integrity is now enforced, but the real specialist corpus artifacts and result rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Behavioral result artifact binding

- Tightened `tools/verify_behavioral_corpus.py` so root-backed behavioral result rows must include an artifact path and SHA-256 hash matching the annotation's gold remediation or known-bad artifact metadata.
- Added `result_artifact_errors` to the behavioral corpus summary for result rows that are detached from the artifact they claim to measure.
- Added regression coverage for missing gold result artifact binding and mismatched known-bad result hashes; updated the CLI success fixture to include artifact-bound result rows.
- Updated the completion audit with behavioral result row hash-binding evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 9 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 68 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 250 passed, 2 skipped; quality coverage 86.00% (4368/5079).
- Verified `./.venv/bin/python -m pytest -q`: 362 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral result rows are now hash-bound, but the real specialist corpus artifacts and result rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Judge-result artifact binding

- Added optional artifact path/hash fields to `JudgeResultRow` and required external `--judge-results` rows to bind to the annotated source artifact path and `source_sha256`.
- Added `judge_result_binding_errors()` and CLI rejection for unbound or mismatched judge-result rows before kappa metrics are computed or persisted.
- Added calibration tests for missing artifact binding, source hash mismatches, and CLI rejection without writing metrics.
- Updated the completion audit with judge-result hash-binding evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 14 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 70 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 19 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 252 passed, 2 skipped; quality coverage 86.01% (4395/5110).
- Verified `./.venv/bin/python -m pytest -q`: 364 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: judge-result rows are now hash-bound, but the real specialist corpus, live judge runs, and calibration metrics are still absent.
- Next: remaining completion depends on specialist corpus artifacts, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Pairwise calibration artifact binding

- Added required `a_sha256` and `b_sha256` fields to pairwise annotation rows, auto-filled when candidate artifacts exist and allowed empty when candidate files are absent.
- Tightened pairwise annotation validation to reject unknown comparison fields and malformed candidate hashes.
- Added `judge_comparison_binding_errors()` and CLI rejection for external `--judge-comparisons` rows whose candidate hashes are missing or mismatched when annotation hashes are present.
- Added corpus tests for pairwise candidate hash capture and pairwise judge-comparison binding failures.
- Updated the completion audit with pairwise artifact-binding evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py tests/corpus/test_calibrate_judges.py -q`: 39 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 73 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 19 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 255 passed, 2 skipped; quality coverage 86.23% (4452/5163).
- Verified `./.venv/bin/python -m pytest -q`: 367 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: pairwise calibration rows are now hash-bound, but the real specialist corpus, live judge runs, and calibration metrics are still absent.
- Next: remaining completion depends on specialist corpus artifacts, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Review sampler source hash binding

- Added `source_sha256` to `ReviewCandidate` and sampled review queue items.
- Updated candidate JSONL loading to auto-compute source hashes when `source_path` exists, accept precomputed hashes for missing/offline artifacts, and reject malformed or mismatched source hashes.
- Added sampler tests for queue source hashes, hash-bound candidate loading, and mismatch rejection.
- Updated the completion audit with review sampler source-hash evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 9 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 75 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 19 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 257 passed, 2 skipped; quality coverage 86.25% (4466/5178).
- Verified `./.venv/bin/python -m pytest -q`: 369 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review queue candidates are now source-hash-bound, but the real specialist corpus and review verdicts are still absent.
- Next: remaining completion depends on specialist corpus artifacts, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Review submit queue binding

- Tightened `/v1/quality/review/submit` so a submitted annotation must match a queued review item's `source_path` and `source_sha256` when a queue item for the same document and format exists.
- Added an API regression test proving mismatched queued source hashes reject the submitted annotation before any corpus file is written.
- Updated the completion audit with queue-to-annotation source binding evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 20 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 75 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 258 passed, 2 skipped; quality coverage 86.26% (4489/5204).
- Verified `./.venv/bin/python -m pytest -q`: 370 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review submission is now source-hash-bound to queued work, but the real specialist corpus and review verdicts are still absent.
- Next: remaining completion depends on specialist corpus artifacts, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Snapshot annotation hash binding

- Added `annotation_sha256` to default-flow snapshot payloads captured from annotated corpus records.
- Tightened `tools/verify_corpus_snapshots.py` so committed snapshots must bind to the current annotation JSON bytes, catching stale snapshot evidence after label or path edits.
- Added snapshot gate regression coverage for stale annotation hashes and updated capture tests to pass annotation digests through the CLI flow.
- Updated the completion audit with annotation-hash-bound snapshot evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py tests/corpus/test_capture_corpus_snapshots.py -q`: 12 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 76 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 259 passed, 2 skipped; quality coverage 86.26% (4496/5212).
- Verified `./.venv/bin/python -m pytest -q`: 371 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot records are now annotation-hash-bound, but the real specialist corpus artifacts and live default-flow snapshots are still absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, and calibration evidence.

## 2026-05-08 - Phase G holdout result source binding

- Tightened `evaluate_holdout_ab()` so baseline and candidate holdout result rows must match the annotated source hash when holdout records provide `source_sha256` metadata.
- Added duplicate-result rejection inside the holdout result loader to prevent later rows from silently replacing earlier held-out evidence.
- Added Phase G regression coverage for candidate result source-hash mismatches.
- Updated the completion audit with source-hash-bound holdout result evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 12 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 30 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 259 passed, 2 skipped; quality coverage 86.26% (4496/5212).
- Verified `./.venv/bin/python -m pytest -q`: 372 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: Phase G holdout result rows are now source-hash-bound, but no real controlled held-out A/B runs exist yet.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration row uniqueness and live source binding

- Tightened live calibration audits so generated `JudgeResultRow` entries carry the audited source artifact path and SHA-256 hash.
- Added a source-hash drift check before live audits; annotations whose source artifact bytes no longer match metadata are skipped instead of being used for kappa evidence.
- Rejected duplicate external judge-result rows and duplicate pairwise judge-comparison rows so repeated rows cannot inflate calibration sample sizes.
- Added calibration regression coverage for live audit source binding, source drift skips, duplicate scalar rows, and duplicate pairwise rows.
- Updated the completion audit with the stricter calibration evidence requirements.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 19 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 79 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 262 passed, 2 skipped; quality coverage 86.53% (4529/5234).
- Verified `./.venv/bin/python -m pytest -q`: 375 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: calibration evidence is now harder to spoof locally, but real specialist corpus rows and live/external judge results are still absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Explicit quality=false route regression coverage

- Added route tests proving `/v1/remediate?quality=false` preserves the default metadata shape without adding quality opt-in state.
- Added route tests proving `/v1/office/remediate?quality=false` preserves empty Office remediation metadata.
- Updated the completion audit with explicit `quality=false` metadata-level regression evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_opt_in_routes.py -q`: 5 passed.
- Verified `./.venv/bin/python -m pytest tests/api -q`: 25 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 264 passed, 2 skipped; quality coverage 86.53% (4529/5234).
- Verified `./.venv/bin/python -m pytest -q`: 377 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: explicit false metadata is covered locally, but corpus-wide byte-identical default-flow snapshots still require real corpus artifacts and live captures.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration store invariant guard

- Tightened `ExperimentStore.record_judge_calibration()` so invalid kappa values, non-positive sample sizes, and timezone-less `measured_at` values cannot be persisted through direct store calls.
- Added store-level regression coverage proving invalid calibration metrics leave the `judge_calibration` table empty.
- Updated the completion audit with persistence-bound calibration metric validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py tests/corpus/test_calibrate_judges.py tests/api/test_quality_routes.py -q`: 46 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 265 passed, 2 skipped; quality coverage 86.53% (4529/5234).
- Verified `./.venv/bin/python -m pytest -q`: 378 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: calibration metric storage is now guarded, but real specialist annotations and live calibration results remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review calibration submission atomicity

- Tightened `/v1/quality/review/submit` so calibration rows are validated as a complete batch before any metric is persisted.
- Rejected duplicate judge/version/format/dimension calibration slices within one review submission.
- Added API validation for timezone-aware `measured_at` values before handing rows to the shared experiment store.
- Added regression coverage proving duplicate calibration submissions are rejected without partial writes.
- Updated the completion audit with atomic review-calibration submission evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 22 passed.
- Verified `./.venv/bin/python -m pytest tests/api -q`: 27 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 267 passed, 2 skipped; quality coverage 86.53% (4543/5250).
- Verified `./.venv/bin/python -m pytest -q`: 380 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review-submitted calibration rows are now validated atomically, but real specialist verdict rounds and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral result duplicate-row guard

- Tightened `tools/verify_behavioral_corpus.py` so duplicate gold/reference or known-bad behavioral result rows for the same document and format are rejected instead of allowing later rows to replace earlier evidence.
- Added behavioral corpus regression coverage for duplicate gold-role result rows.
- Updated the completion audit with the unique-row behavioral evidence rule.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 10 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 80 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 268 passed, 2 skipped; quality coverage 86.53% (4543/5250).
- Verified `./.venv/bin/python -m pytest -q`: 381 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral result rows are now uniqueness-guarded, but real gold/known-bad artifacts and behavioral result rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Snapshot source metadata and stale-file guard

- Tightened `tools/verify_corpus_snapshots.py` so snapshot `source_sha256` must match both the annotation's `artifact_hashes.source_sha256` metadata and the current source artifact bytes when present.
- Added stale snapshot detection for extra committed snapshot JSON files that do not correspond to any current annotation.
- Added snapshot-gate regression coverage for annotation source-hash drift and stale snapshot files.
- Updated the completion audit with stricter snapshot source binding and stale-file evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py tests/corpus/test_capture_corpus_snapshots.py -q`: 14 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 82 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 270 passed, 2 skipped; quality coverage 86.53% (4555/5264).
- Verified `./.venv/bin/python -m pytest -q`: 383 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot evidence is stricter, but real corpus artifacts and live default-flow captures are still absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Snapshot capture CLI validation guard

- Tightened `tools/capture_corpus_snapshots.py` so captured payloads are validated with the snapshot verifier before they are written to disk.
- Made filtered snapshot capture fail when no annotation records match the requested format instead of exiting successfully with zero captured records.
- Added capture CLI regression coverage for zero-selection filters and invalid payload rejection without writing a snapshot file.
- Updated the completion audit with the stricter snapshot capture evidence path.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_capture_corpus_snapshots.py tests/corpus/test_snapshot_gate.py -q`: 16 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 84 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 272 passed, 2 skipped; quality coverage 86.59% (4566/5273).
- Verified `./.venv/bin/python -m pytest -q`: 385 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot capture now refuses weak local evidence, but no real specialist corpus or live default-flow captures exist yet.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Phase A known-bad artifact coverage guard

- Tightened `tools/annotate_corpus.py` Phase A coverage so annotations must include resolvable, hash-bound known-bad artifact references in addition to source and gold remediation artifacts.
- Updated coverage error messaging to refer to source/gold/known-bad artifact references and hashes.
- Added corpus coverage regression tests for missing known-bad paths and known-bad hash drift.
- Updated the completion audit with the stricter Phase A artifact requirement.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 24 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 85 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 273 passed, 2 skipped; quality coverage 86.53% (4580/5293).
- Verified `./.venv/bin/python -m pytest -q`: 386 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: Phase A coverage now requires known-bad artifacts, but the real specialist corpus and referenced artifacts are still absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Runtime calibration freshness gate

- Added `QUALITY_MAX_CALIBRATION_AGE_DAYS` to backend settings and `.env.example`; `0` keeps the age check disabled for compatibility.
- Tightened `backend/app/quality_calibration.py` so active quality readiness rejects calibration rows older than the configured age limit.
- Added API regression coverage proving stale but otherwise valid calibration rows block `/v1/quality/audit/pdf` when the freshness gate is configured.
- Updated the completion audit with the optional runtime calibration freshness guard.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 23 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 33 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 274 passed, 2 skipped; quality coverage 86.42% (4602/5325).
- Verified `./.venv/bin/python -m pytest -q`: 387 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: runtime freshness can now be enforced, but real calibration rows from specialist corpus runs remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral gate coverage target guard

- Added `tools/verify_behavioral_corpus.py` to the default quality coverage target set so the behavioral discrimination readiness gate is measured by `tools/quality_coverage.py`.
- Added regression coverage proving the behavioral verifier remains in the measured target list.
- Updated the completion audit with the current verification snapshot.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_coverage.py -q`: 5 passed.
- Verified `./.venv/bin/python -m compileall -q tools/quality_coverage.py tests/corpus/test_quality_coverage.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 275 passed, 2 skipped; quality coverage 86.21% (4837/5611).
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 86 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 388 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: the behavioral gate is now counted in local coverage, but real gold/known-bad artifacts and behavioral result rows are still absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review submission preflight atomicity

- Tightened `/v1/quality/review/submit` so calibration rows and existing-store conflicts are validated before annotation artifacts are written.
- Added regression coverage proving invalid or duplicate calibration rows with a valid annotation leave no annotation file, calibration row, submission log, or queue completion side effect.
- Updated the completion audit with the stronger specialist-verdict persistence guarantees.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 25 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 277 passed, 2 skipped; quality coverage 86.18% (4851/5629).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 35 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 390 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review verdict persistence is now safer, but the real specialist verdict round and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review claim ownership guard

- Tightened `/v1/quality/review/submit` so a claimed review item can only be completed by the matching `reviewer_id`.
- Recorded `completed_by` on successful queue completion and added regression coverage proving a different reviewer cannot complete a claimed item or write annotation/submission side effects.
- Updated the completion audit with the stricter claim-and-submit evidence rule.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 26 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 278 passed, 2 skipped; quality coverage 86.15% (4870/5653).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 36 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 391 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review item ownership is now guarded, but the real specialist verdict round and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Completed review claim guard

- Tightened `/v1/quality/review/claim` so completed review items cannot be moved back to `claimed`.
- Added regression coverage proving completed items keep their terminal status and completion metadata when a reviewer attempts to claim them again.
- Updated the completion audit with the completed-item immutability guard.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 27 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 279 passed, 2 skipped; quality coverage 86.15% (4872/5655).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 37 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 392 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: completed queue items are now immutable through the claim endpoint, but the real specialist verdict round and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Queued review durable-evidence guard

- Tightened `/v1/quality/review/submit` so queued review work cannot be completed by a bare verdict that lacks annotation or calibration rows.
- Updated review-route tests to submit durable annotation/calibration evidence for successful queued completion and added a rejection test for bare queued verdicts.
- Updated the completion audit with the queued-verdict evidence requirement.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 28 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 280 passed, 2 skipped; quality coverage 86.18% (4875/5657).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 38 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 393 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: queued specialist work now requires durable evidence to complete, but the real specialist verdict round and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review evidence binding guard

- Tightened `/v1/quality/review/submit` so annotation evidence must match the submitted review `doc_id`/format and calibration evidence must match the submitted review format before queued work can complete.
- Added regression coverage proving mismatched annotation or calibration evidence leaves the queue unchanged and writes no annotation, calibration, or submission-log side effects.
- Updated the completion audit with the same-document and same-format evidence-binding rule.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 30 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 282 passed, 2 skipped; quality coverage 86.19% (4891/5675).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 40 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 395 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: queued review evidence is now bound to the submitted document/format, but the real specialist verdict round and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Queue-format calibration binding guard

- Tightened `/v1/quality/review/submit` so calibration-only evidence must also match the matched queue item's format when the submission omits an explicit `format`.
- Added regression coverage proving a DOCX calibration row cannot complete a PDF queue item by matching only `doc_id`.
- Updated the completion audit with the queue-item format binding rule.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 31 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 283 passed, 2 skipped; quality coverage 86.19% (4895/5679).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 41 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 396 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: queued review evidence is now bound to the queue-item format, but the real specialist verdict round and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Queued review annotation completion guard

- Tightened `/v1/quality/review/submit` so queued document review work requires annotation evidence to complete; calibration rows alone can be submitted, but cannot complete a queued document item.
- Updated review-route tests so successful queue completion submits an annotation and calibration-only queued submissions are rejected without queue or submission-log side effects.
- Updated the completion audit with the annotation-required queued completion rule.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 31 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 283 passed, 2 skipped; quality coverage 86.14% (4892/5679).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 41 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 396 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: queued document review completion now requires annotation evidence, but the real specialist verdict round and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Annotation overwrite manifest replacement

- Tightened `tools/annotate_corpus.py` so `write_annotation_record(..., overwrite=True)` replaces the existing manifest row for that annotation instead of appending duplicate manifest evidence.
- Added corpus regression coverage proving overwrite keeps a single current manifest row bound to the overwritten annotation hash.
- Updated the completion audit with overwrite-safe manifest behavior.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 25 passed.
- Verified `./.venv/bin/python -m compileall -q tools/annotate_corpus.py tests/corpus/test_annotate_corpus.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 87 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 284 passed, 2 skipped; quality coverage 86.06% (4907/5702).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 397 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: annotation overwrites now keep manifest evidence coherent, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Cross-format review sampling identity

- Tightened `tools/sample_quality_reviews.py` so sampling treats `format + doc_id` as the candidate identity instead of suppressing cross-format documents that share a `doc_id`.
- Added sampler regression coverage proving PDF and DOCX candidates with the same `doc_id` can both be sampled.
- Updated the completion audit with the format-aware sampling evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 10 passed.
- Verified `./.venv/bin/python -m compileall -q tools/sample_quality_reviews.py tests/corpus/test_sample_quality_reviews.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 88 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 285 passed, 2 skipped; quality coverage 86.06% (4909/5704).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 398 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review sampling now respects cross-format identity, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Cross-format sampler tie-breaker

- Tightened `tools/sample_quality_reviews.py` so deterministic priority/random sampling tie-breakers use `format:doc_id`, not only `doc_id`.
- Added regression coverage proving same-`doc_id` cross-format candidate selection is stable when input order changes.
- Updated the completion audit with deterministic format-aware sampling evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 11 passed.
- Verified `./.venv/bin/python -m compileall -q tools/sample_quality_reviews.py tests/corpus/test_sample_quality_reviews.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 89 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 286 passed, 2 skipped; quality coverage 86.07% (4911/5706).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 399 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review sampling is now deterministic across same-id formats, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Same-doc queue format binding guard

- Tightened `/v1/quality/review/submit` so an annotation with the same `doc_id` but a different format from an existing queued review item is rejected instead of bypassing the queued item.
- Added regression coverage proving the mismatched-format annotation leaves the queue unchanged and writes no annotation or submission-log side effects.
- Updated the completion audit with the same-doc queued-format binding rule.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 32 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 287 passed, 2 skipped; quality coverage 86.09% (4916/5710).
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 42 passed.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 400 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: same-doc queued review submissions are now format-bound, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Sampler dimension applicability guard

- Tightened `tools/sample_quality_reviews.py` so candidate JSONL and `ExperimentStore` quality records reject `quality_dimensions` or `dimension_variance` keys that are not applicable to the candidate format, and direct queue appends reject inapplicable `weak_dimensions`.
- Added sampler coverage proving XLSX accepts `sheet_organization`, rejects XLSX `reading_order`, rejects non-object dimension maps, rejects inapplicable stored experiment dimensions, and rejects invalid appended queue rows before writing.
- Updated the completion audit with the sampler applicability rule and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 18 passed.
- Verified `./.venv/bin/python -m compileall -q tools/sample_quality_reviews.py tests/corpus/test_sample_quality_reviews.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 96 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 294 passed, 2 skipped; quality coverage 86.09% (4945/5744).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 407 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: queued review candidates now honor the format applicability matrix, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration row applicability guard

- Tightened `tools/calibrate_judges.py` so external judge result rows and pairwise comparison rows reject unsupported formats and inapplicable dimensions at JSONL load time.
- Added calibration coverage proving XLSX `reading_order` is rejected for both absolute judge-result rows and pairwise comparison rows.
- Updated the completion audit with external calibration-row applicability evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 21 passed.
- Verified `./.venv/bin/python -m compileall -q tools/calibrate_judges.py tests/corpus/test_calibrate_judges.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 98 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 296 passed, 2 skipped; quality coverage 86.10% (4956/5756).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 409 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: external calibration evidence now honors the format applicability matrix, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Shared annotation dimension matrix

- Replaced the duplicated annotation-tool dimension matrix with the shared `project_remedy.quality_judges.shared.dimensions.DIMENSIONS_BY_FORMAT` source used by the API, sampler, and calibration tools.
- Updated the completion audit to call out the single applicability matrix path.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 25 passed.
- Verified `./.venv/bin/python -m compileall -q tools/annotate_corpus.py tests/corpus/test_annotate_corpus.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 98 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 296 passed, 2 skipped; quality coverage 86.09% (4959/5760).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 409 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: annotation, API, sampler, and calibration tools now share one applicability matrix, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Sampler CLI import path guard

- Added repo-root and `src` path bootstrapping to `tools/sample_quality_reviews.py` so direct script execution can import the shared quality dimension matrix.
- Verified `./.venv/bin/python tools/sample_quality_reviews.py --help`.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 18 passed.
- Verified `./.venv/bin/python -m compileall -q tools/sample_quality_reviews.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 98 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 296 passed, 2 skipped; quality coverage 86.09% (4963/5765).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 409 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: sampler direct execution is restored, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality tool CLI regression guard

- Added `tests/corpus/test_quality_artifact_tracking.py` coverage that runs every quality tool with `--help` directly from the repo root.
- Updated the completion audit with the direct quality-tool CLI coverage guard.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_artifact_tracking.py -q`: 4 passed.
- Verified `./.venv/bin/python -m compileall -q tests/corpus/test_quality_artifact_tracking.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 99 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 297 passed, 2 skipped; quality coverage 86.09% (4963/5765).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 410 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct quality-tool execution is now guarded, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality API evidence validation guard

- Tightened quality API filters so unsupported calibration formats/dimensions, review queue formats, review claim formats, and review submission formats fail with explicit 422 errors.
- Tightened `/v1/quality/review/submit` so unqueued submissions still require durable annotation or calibration evidence instead of accepting a bare verdict.
- Added route regression coverage for invalid filters, unsupported submission formats, and bare unqueued verdicts without side effects.
- Updated the completion audit with the stricter review evidence validation.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 37 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_routes.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python -m pytest tests/api tests/test_engine_quality_opt_in.py -q`: 47 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 302 passed, 2 skipped; quality coverage 86.12% (4984/5787).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 415 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: API submissions now require durable evidence, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration store applicability guard

- Tightened `ExperimentStore.record_judge_calibration()` so unsupported formats and inapplicable format/dimension pairs are rejected at the persistence boundary.
- Extended quality metrics tests to cover invalid calibration format and XLSX `reading_order` rejection.
- Updated the completion audit with store-level calibration format/dimension validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py tests/corpus/test_calibrate_judges.py tests/api/test_quality_routes.py -q`: 65 passed.
- Verified `./.venv/bin/python -m compileall -q src/project_remedy/vision_planner/experiment_store.py tests/vision_planner/test_quality_metrics_extension.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 302 passed, 2 skipped; quality coverage 86.12% (4984/5787).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 415 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: calibration persistence now enforces the applicability matrix, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality score applicability guard

- Tightened `QualityDimensionScore` so unsupported formats and inapplicable format/dimension pairs cannot be constructed by PDF or Office audit paths.
- Added shared judge tests proving XLSX `reading_order` and unsupported `txt` score formats are rejected.
- Updated the completion audit with quality-result boundary validation for n/a dimensions.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared tests/quality_judges/pdf tests/quality_judges/office -q`: 55 passed.
- Verified `./.venv/bin/python -m compileall -q src/project_remedy/quality_judges/shared/base.py tests/quality_judges/shared/test_rubrics.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 303 passed, 2 skipped; quality coverage 86.14% (4989/5792).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 416 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: quality scores now enforce n/a dimensions at construction time, but the real specialist corpus and calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral result applicability guard

- Tightened `BehavioralTestResult` so unsupported formats and inapplicable format/dimension pairs cannot be constructed, using a lazy shared matrix lookup to avoid import cycles.
- Added behavioral shared tests proving XLSX `reading_order` and unsupported `txt` behavioral results are rejected.
- Updated the completion audit with behavioral result boundary validation.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies tests/quality_judges/shared/test_behavioral_precedence.py -q`: 81 passed.
- Verified `./.venv/bin/python -m compileall -q src/project_remedy/behavioral_proxies/shared/base.py tests/behavioral_proxies/shared/test_behavioral_model_separation.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 304 passed, 2 skipped; quality coverage 86.16% (4997/5800).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 417 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral results now enforce n/a dimensions at construction time, but the real specialist corpus and behavioral evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality result aggregate consistency guard

- Tightened `QualityResult` so nested dimension and behavioral keys must match their payloads, nested result formats must match the aggregate format, failing dimensions must be applicable, and applicable dimensions cannot be marked `n/a`.
- Added shared judge tests covering mismatched dimension keys, mismatched nested formats, mismatched behavioral keys, and invalid failing/not-applicable dimensions.
- Updated the completion audit with aggregate quality-result validation.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared tests/quality_judges/pdf tests/quality_judges/office tests/api/test_quality_routes.py tests/test_engine_quality_opt_in.py -q`: 101 passed.
- Verified `./.venv/bin/python -m compileall -q src/project_remedy/quality_judges/shared/base.py tests/quality_judges/shared/test_behavioral_precedence.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 308 passed, 2 skipped; quality coverage 86.19% (5016/5820).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 421 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: aggregate quality results now enforce internal consistency, but the real specialist corpus and behavioral/calibration evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral corpus dimension applicability guard

- Tightened `tools/verify_behavioral_corpus.py` so behavioral result rows reject tests whose inferred or explicit dimension is not applicable to the row format.
- Added corpus gate coverage proving XLSX `reading_order_comprehension` and explicit `reading_order` dimensions are rejected in behavioral result rows.
- Updated the completion audit with behavioral-result row applicability evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 11 passed.
- Verified `./.venv/bin/python -m compileall -q tools/verify_behavioral_corpus.py tests/corpus/test_behavioral_corpus_gate.py`.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 100 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 309 passed, 2 skipped; quality coverage 86.07% (5047/5864).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 422 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral result rows now enforce the applicability matrix, but the real specialist corpus and behavioral evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Shared behavioral dimension mapping

- Moved behavioral-test-name-to-quality-dimension mapping into `quality_judges/shared/dimensions.py`.
- Updated `ExperimentStore.get_failure_patterns()` and `tools/verify_behavioral_corpus.py` to share the same mapper for behavioral failure normalization and corpus row applicability checks.
- Added shared rubric coverage for representative behavioral test-name mappings.
- Updated the completion audit with shared behavioral mapping evidence.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared tests/vision_planner/test_quality_metrics_extension.py tests/corpus/test_behavioral_corpus_gate.py -q`: 43 passed.
- Verified `./.venv/bin/python -m compileall -q src/project_remedy/quality_judges/shared/dimensions.py src/project_remedy/vision_planner/experiment_store.py tools/verify_behavioral_corpus.py tests/quality_judges/shared/test_rubrics.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 310 passed, 2 skipped; quality coverage 86.22% (5057/5865).
- Verified `./.venv/bin/python -m pytest -q`: 423 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false` with `stale_snapshots=[]`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral failure analysis and corpus verification now share one mapping, but the real specialist corpus and behavioral evidence remain absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Phase G strategy map schema guard

- Expanded `dimension_strategy_map.yaml` so each dimension-aware strategy declares concrete source file/method/hook targets.
- Tightened `load_dimension_strategy_map()` to reject non-PDF dimensions, invalid name patterns, duplicate hooks, unknown proposer targets, missing concrete targets, missing files, and missing source methods.
- Recorded concrete strategy-map targets in proposed harness configs so generated strategies remain traceable to their declared hook.
- Added proposer tests for concrete target declarations and malformed map rejection.
- Updated the completion audit with the stronger Phase G map validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_proposer_dimension_aware.py -q`: 17 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 36 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_artifact_tracking.py -q`: 4 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 315 passed, 2 skipped; quality coverage 86.22% (5057/5865).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 428 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: Phase G strategy declarations are now schema-guarded, but held-out lift evidence still requires the missing specialist corpus and A/B runs.
- Next: continue checking for code-level completion gaps that do not depend on external corpus evidence.

## 2026-05-08 - Held-out A/B evidence completeness guard

- Tightened `evaluate_holdout_ab()` so Phase G held-out evidence must include at least one holdout record, unique holdout document IDs, source SHA-256 metadata, complete baseline and candidate rows for every holdout document, and no non-holdout result rows.
- Added per-document validation that candidate rows include the target dimension and every non-target dimension present in the matching baseline row before aggregate lift/regression math runs.
- Added score validation for numeric 0.0-1.0 quality dimension values and explicit rejection of result rows without document identity.
- Added held-out A/B tests for empty holdouts, missing document IDs, missing source hashes, incomplete holdout rows, missing per-document dimensions, and out-of-range scores.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 19 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 43 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 315 passed, 2 skipped; quality coverage 86.22% (5057/5865).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 435 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: Phase G held-out evaluation is stricter, but real controlled A/B lift evidence still requires the missing specialist corpus and result rows.
- Next: stop at the external-evidence blocker unless new specialist corpus artifacts become available.

## 2026-05-08 - Shared transcript analysis findings

- Extended shared raw screen-reader transcript analysis to flag vague link announcements and heading-level jumps as structured advisory findings.
- Added shared transcript tests for non-descriptive link announcements and heading outline jumps.
- Verified PDF and Office transcript analyzer wrappers continue to propagate shared raw transcript findings.
- Updated the completion audit with the richer transcript-analysis coverage.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_transcript_analysis.py tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 66 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies -q`: 80 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 317 passed, 2 skipped; quality coverage 86.26% (5085/5895).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 437 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: transcript analysis has stronger deterministic findings, but real screen-reader transcript corpus evidence remains unavailable.
- Next: continue only if another code-side PRD gap is found; otherwise the remaining work depends on external corpus/evidence artifacts.

## 2026-05-08 - Calibration gate unsupported-format guard

- Tightened `quality_calibration_status()` so unsupported formats fail at the calibration-gate boundary instead of appearing ready with zero required dimensions.
- Added API regression coverage for unsupported format rejection in the active calibration status helper.
- Updated the completion audit with this active quality execution boundary guard.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 38 passed.
- Verified `./.venv/bin/python -m compileall -q backend/app/quality_calibration.py tests/api/test_quality_routes.py`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 318 passed, 2 skipped; quality coverage 86.26% (5087/5897).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 438 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: active quality execution is stricter, but deployment readiness still depends on real calibration rows from the missing specialist corpus.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral corpus explicit Office transcript dimension guard

- Added corpus verifier regression coverage proving XLSX `screen_reader_transcript_analysis` rows are accepted when they explicitly declare `dimension: sheet_organization`.
- Updated the completion audit to call out explicit format-specific dimensions for ambiguous Office transcript rows.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 12 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 101 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 319 passed, 2 skipped; quality coverage 86.26% (5087/5897).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 439 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral corpus validation now guards the Office transcript dimension case, but real gold-vs-known-bad behavioral result rows are still missing.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Registered judge pairwise mode guard

- Added registry coverage proving every required judge/version slice maps to a concrete judge class with callable `judge()` and `compare()` methods.
- Updated the completion audit's pairwise calibration evidence to include the registry-level guard.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_registry.py -q`: 5 passed.
- Verified `./.venv/bin/python -m pytest tests/quality_judges -q`: 61 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 320 passed, 2 skipped; quality coverage 86.26% (5087/5897).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 440 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: every registered judge has pairwise mode structurally, but real pairwise calibration evidence still requires specialist annotations and candidate artifacts.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review sampler score range validation

- Tightened `tools/sample_quality_reviews.py` so candidate `quality_dimensions`, `dimension_variance`, and `behavioral_confidence` values must be numeric 0.0-1.0 values.
- Added sampler tests for out-of-range quality scores, variance, and behavioral confidence values.
- Updated the completion audit with the stricter sampler input validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 21 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 104 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 323 passed, 2 skipped; quality coverage 86.24% (5100/5914).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 443 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review sampling is stricter, but an actual specialist verdict round still requires real queued corpus items and annotations.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral result payload validation

- Tightened `tools/verify_behavioral_corpus.py` so behavioral corpus result rows reject non-boolean `passed` values, nonnumeric score/threshold values, and score/threshold values outside 0.0-1.0 before pass/fail inference.
- Added corpus gate tests for malformed behavioral result payloads.
- Updated the completion audit with the stricter behavioral result row validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 13 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 105 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 324 passed, 2 skipped; quality coverage 86.22% (5117/5935).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 444 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral result row validation is stricter, but real gold-vs-known-bad behavioral evidence remains absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Snapshot captured_at timestamp guard

- Tightened `tools/verify_corpus_snapshots.py` so default-flow snapshot records require `captured_at` to be an ISO date-time with timezone.
- Added snapshot-gate coverage rejecting timezone-less capture timestamps.
- Updated the completion audit with timezone-aware snapshot evidence validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py -q`: 9 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 106 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 325 passed, 2 skipped; quality coverage 86.20% (5123/5943).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 445 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot records now require stronger evidence timestamps, but real default-flow snapshot records still require a live API run against the missing specialist corpus.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Default-flow snapshot metadata guard

- Extended default-flow snapshot capture to store parsed `default_response_metadata` alongside the default response/output hashes.
- Tightened `tools/verify_corpus_snapshots.py` so snapshot records must include metadata as an object, must not include `quality_result`, and must keep `quality_result_absent` consistent with the stored metadata.
- Tightened snapshot capture so malformed or non-object `metadata_json` fails instead of being treated as empty metadata.
- Added snapshot capture and gate tests for default metadata that leaks `quality_result`, plus malformed and non-object `metadata_json` capture tests.
- Updated the completion audit with the stricter default-flow metadata evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py tests/corpus/test_capture_corpus_snapshots.py -q`: 21 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 110 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 329 passed, 2 skipped; quality coverage 86.22% (5135/5956).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 449 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot tooling now validates the default response metadata itself, but real byte-identical default-flow evidence still requires live API snapshots against the missing specialist corpus.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral result object-shape guard

- Tightened `tools/verify_behavioral_corpus.py` so result rows with non-object `behavioral` / `behavioral_results` / `results` payloads fail row validation instead of falling through as incomparable tests.
- Added corpus-gate regression coverage for non-object behavioral result payloads.
- Updated the completion audit with the stricter behavioral result payload evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 14 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 111 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 330 passed, 2 skipped; quality coverage 86.23% (5136/5956).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 450 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral result row validation is stricter, but real gold-vs-known-bad behavioral evidence remains absent.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration JSONL input-shape guard

- Tightened `tools/calibrate_judges.py` so external judge-result rows reject boolean scores and empty required identifiers at load time.
- Tightened external pairwise comparison rows so empty required identifiers or candidate paths fail before binding/calibration.
- Added calibration tests for boolean judge scores, empty judge-result fields, and empty pairwise candidate paths.
- Updated the completion audit with the stricter calibration JSONL evidence validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 23 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 113 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 332 passed, 2 skipped; quality coverage 86.28% (5144/5962).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 452 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: calibration input validation is stricter, but real Cohen's kappa readiness still requires specialist annotations and judge result rows.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review sampler candidate input-shape guard

- Tightened `tools/sample_quality_reviews.py` so candidate JSONL rows must be objects.
- Rejected boolean `quality_dimensions`, `dimension_variance`, and `behavioral_confidence` values instead of coercing them to numeric scores.
- Added sampler tests for non-object candidate rows, boolean quality scores, and boolean behavioral confidence.
- Updated the completion audit with the stricter sampler input validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 24 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 116 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 335 passed, 2 skipped; quality coverage 86.36% (5154/5968).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 455 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review sampling validation is stricter, but a real specialist verdict round still requires corpus artifacts, queued source files, and reviewer submissions.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review submission calibration kappa bool guard

- Tightened `backend/app/quality_routes.py` so submitted calibration rows reject boolean `cohens_kappa` values instead of coercing them to `1.0`.
- Added API regression coverage proving boolean kappa rows fail without writing calibration records.
- Updated the completion audit with the stricter review-submission calibration validation.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 39 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 160 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 336 passed, 2 skipped; quality coverage 86.37% (5156/5970).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 456 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: route-level calibration submission is stricter, but real specialist verdict/calibration readiness still requires annotation and calibration evidence.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Finite numeric evidence guard

- Tightened annotation scoring so CLI, interactive prompts, top-level dimensions, and nested Office annotations reject non-finite scores such as `NaN`.
- Tightened behavioral corpus result rows so score/threshold payloads must be finite before pass/fail inference.
- Tightened review sampler candidate JSONL so quality scores, variance, and behavioral confidence must be finite.
- Tightened calibration inputs and review-submission kappa validation so judge scores and kappa values must be finite.
- Tightened `ExperimentStore.record_experiment()` so malformed quality dimensions and non-boolean behavioral results cannot be persisted for scorer/proposer evidence.
- Tightened held-out A/B quality evaluation so baseline/candidate dimension scores must be finite and non-boolean.
- Verified focused tests for annotations, behavioral corpus, sampler, calibration, quality routes, experiment metrics, and held-out evaluation: 121 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/vision_planner -q`: 212 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 344 passed, 2 skipped; quality coverage 86.39% (5184/6001).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 465 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: numeric evidence validation is stricter, but the PRD still requires real specialist corpus, snapshots, behavioral rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Shared quality result finite guard

- Tightened `QualityDimensionScore` so score, variance, confidence, and per-criterion values must be finite and valid before quality results can serialize.
- Tightened `BehavioralTestResult` so `passed` must be a real boolean and score/threshold/confidence must be finite.
- Updated `BehavioralResultCache` loading so malformed cached `passed` values are rejected instead of coerced.
- Added shared quality/behavioral tests for non-finite values, per-criterion values, and cached non-boolean pass flags.
- Updated the completion audit with the stricter shared result validation.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_rubrics.py tests/behavioral_proxies/shared/test_behavioral_model_separation.py -q`: 22 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/vision_planner tests/quality_judges tests/behavioral_proxies -q`: 355 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 346 passed, 2 skipped; quality coverage 86.44% (5201/6017).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 467 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: shared result objects now reject malformed numeric/pass values, but real quality-layer completion still requires the external corpus and calibration evidence.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Aggregate quality result status guard

- Tightened `QualityResult` so `overall_pass` must be boolean and dimension/status containers must have the expected object/list shapes.
- Rejected duplicate failing dimensions, duplicate not-applicable dimensions, and unknown not-applicable dimensions at result construction time.
- Added shared quality-result tests for unknown n/a dimensions, duplicate failing dimensions, non-boolean `overall_pass`, and malformed n/a containers.
- Updated the completion audit with the stricter aggregate result contract.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_behavioral_precedence.py tests/quality_judges/shared/test_rubrics.py tests/behavioral_proxies/shared/test_behavioral_model_separation.py -q`: 30 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/vision_planner tests/quality_judges tests/behavioral_proxies -q`: 356 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 347 passed, 2 skipped; quality coverage 86.39% (5219/6041).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 468 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: aggregate quality result validation is stricter, but real PRD completion still requires corpus, snapshot, behavioral, calibration, and held-out A/B evidence.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review queue JSONL strictness guard

- Tightened `backend/app/quality_routes.py` so malformed or non-object quality review queue JSONL rows fail explicitly instead of being silently skipped.
- Added API regression coverage for malformed JSONL and non-object queue rows.
- Updated the completion audit with the stricter review-queue evidence handling.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 42 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/vision_planner tests/quality_judges tests/behavioral_proxies -q`: 358 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 349 passed, 2 skipped; quality coverage 86.43% (5222/6042).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 470 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review queue state handling is stricter, but the actual specialist verdict round still requires real queued documents and submitted annotations/calibration rows.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review sampler queue JSONL strictness guard

- Tightened `tools/sample_quality_reviews.py` so malformed or non-object existing review queue JSONL rows fail explicitly instead of being silently skipped during sampler appends.
- Added sampler regression coverage for malformed existing queue JSONL and non-object existing queue rows.
- Updated the completion audit with the latest verification counts and strict existing-queue parsing evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 28 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 171 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 351 passed, 2 skipped; quality coverage 86.46% (5225/6043).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 472 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: sampler queue evidence handling is stricter, but the PRD still requires real specialist corpus artifacts, default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Review sampler direct append validation guard

- Tightened `tools/sample_quality_reviews.py` so direct queue appends reject non-object new items, non-`queued` statuses, malformed `source_sha256`, and non-string `weak_dimensions` before writing JSONL evidence.
- Added sampler regression coverage proving those malformed new queue rows leave the queue file untouched.
- Updated the completion audit with the latest verification counts and direct queue-write validation evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 32 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 175 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 355 passed, 2 skipped; quality coverage 86.49% (5236/6054).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 476 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct queue-write validation is stricter, but the PRD still requires real specialist corpus artifacts, default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality response schema numeric guard

- Tightened `backend/app/quality_routes.py` Pydantic response models so OpenAPI-facing quality, behavioral, and calibration payloads reject non-finite or out-of-range numeric evidence.
- Added per-criterion response-map validation and calibration response checks for finite kappa and positive sample sizes.
- Added API model regression coverage for malformed response numeric evidence.
- Updated the completion audit with the latest verification counts and response-schema evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 43 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 176 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 356 passed, 2 skipped; quality coverage 86.41% (5246/6071).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 477 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: OpenAPI response schemas are stricter, but the PRD still requires real specialist corpus artifacts, default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality response schema boolean numeric guard

- Tightened `backend/app/quality_routes.py` response models so boolean quality scores, behavioral scores, calibration kappa values, and calibration sample sizes are rejected instead of being coerced to numeric evidence.
- Added API model regression coverage for boolean numeric response fields across quality, behavioral, and calibration payloads.
- Updated the completion audit with the latest verification counts and boolean numeric response-schema evidence.
- Verified direct model construction now raises `ValidationError` for boolean numeric response evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 43 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 176 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 356 passed, 2 skipped; quality coverage 86.44% (5258/6083).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 477 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: OpenAPI response schemas are stricter, but the PRD still requires real specialist corpus artifacts, default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration CLI threshold argument guard

- Tightened `tools/calibrate_judges.py` so calibration score thresholds, kappa thresholds, minimum samples, and rolling drift windows are validated before calibration or alert generation runs.
- Added calibration tests rejecting boolean/non-finite scores, non-finite thresholds, out-of-range kappa thresholds, non-positive sample floors, and non-positive rolling windows.
- Updated the completion audit with the latest verification counts and CLI threshold validation evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 26 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 178 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 358 passed, 2 skipped; quality coverage 86.43% (5287/6117).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 479 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: calibration CLI argument validation is stricter, but the PRD still requires real specialist corpus artifacts, default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Snapshot payload object-shape guard

- Tightened `tools/verify_corpus_snapshots.py` so decoded snapshot JSON must be an object; non-object payloads are reported as invalid snapshot evidence instead of crashing the verifier.
- Added snapshot-gate regression coverage for non-object snapshot payloads.
- Updated the completion audit with the latest verification counts and object-shaped snapshot evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py -q`: 11 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 179 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 359 passed, 2 skipped; quality coverage 86.44% (5289/6119).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 480 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral corpus threshold argument guard

- Tightened `tools/verify_behavioral_corpus.py` so `min_pass_rate` must be numeric, finite, and between 0.0 and 1.0 before behavioral discrimination summaries run.
- Added behavioral gate regression coverage for non-finite, boolean, and out-of-range min-pass-rate settings.
- Updated the completion audit with the latest verification counts and behavioral threshold validation evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 16 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 180 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 360 passed, 2 skipped; quality coverage 86.48% (5301/6130).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 481 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral threshold validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Phase A coverage minimum argument guard

- Tightened `tools/annotate_corpus.py` so Phase A coverage minimums must be non-negative integers before readiness evaluation runs.
- Added annotation coverage regression tests for negative and boolean minimums plus CLI rejection of invalid coverage arguments.
- Updated the completion audit with the latest verification counts and coverage-threshold validation evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_annotate_corpus.py -q`: 28 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 181 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 361 passed, 2 skipped; quality coverage 86.59% (5319/6143).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 482 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: Phase A coverage argument validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality coverage threshold argument guard

- Tightened `tools/quality_coverage.py` so coverage thresholds must be numeric, finite, and between 0 and 100 before traced pytest execution begins.
- Added coverage-tool regression tests proving invalid thresholds fail before the expensive traced test run starts.
- Updated the completion audit with the latest verification counts and coverage-threshold validation evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_coverage.py -q`: 7 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus -q`: 183 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 363 passed, 2 skipped; quality coverage 86.59% (5319/6143).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 484 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: quality coverage threshold validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Phase G threshold argument guard

- Tightened `vision_planner/quality_evaluation.py` so holdout ratios, promotion lift/regression thresholds, and required controlled A/B experiment counts are validated before held-out evaluation decisions run.
- Added Phase G tests rejecting non-finite, boolean, and out-of-range holdout ratios and promotion thresholds plus non-positive, boolean, and non-integer required experiment counts.
- Updated the completion audit with the latest verification counts and Phase G threshold validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 24 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 49 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/vision_planner -q`: 232 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 363 passed, 2 skipped; quality coverage 86.59% (5319/6143).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 488 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: Phase G threshold validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral proxy threshold guard

- Added a shared behavioral proxy threshold validator and routed PDF proxy `run()` methods plus DOCX/PPTX decorative-skip proxy entry points through it.
- Added behavioral proxy tests proving caller-supplied boolean, non-finite, and out-of-range thresholds fail before proxy scoring.
- Updated the completion audit with latest verification counts and behavioral proxy threshold validation evidence.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 64 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies -q`: 83 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/vision_planner -q`: 315 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 365 passed, 2 skipped; quality coverage 86.59% (5322/6146).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 490 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral proxy argument validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral cache evidence guard

- Tightened `BehavioralResultCache.get()` so cached proxy evidence must already have valid field types instead of being coerced into a `BehavioralTestResult`.
- Added cache tests rejecting coerced numeric fields, malformed findings, and malformed metadata while preserving valid document-hash cache hits.
- Updated the completion audit with latest verification counts and behavioral cache validation evidence.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_behavioral_model_separation.py -q`: 15 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies -q`: 85 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/vision_planner -q`: 317 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 367 passed, 2 skipped; quality coverage 86.57% (5331/6158).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 492 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral cache validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality ensemble threshold guard

- Tightened `QualityJudgeEnsemble` so per-dimension thresholds are copied and validated before any judge aggregation decision can run.
- Added ensemble tests rejecting unknown threshold dimensions plus boolean, non-finite, and out-of-range threshold values.
- Updated the completion audit with latest verification counts and quality ensemble threshold validation evidence.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/shared -q`: 37 passed.
- Verified `./.venv/bin/python -m pytest tests/quality_judges -q`: 64 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 381 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 368 passed, 2 skipped; quality coverage 86.59% (5341/6168).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 493 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: quality ensemble threshold validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration sample-size integer guard

- Tightened calibration evidence validation so API response rows, review submission calibration rows, and `ExperimentStore.record_judge_calibration()` require real positive integer sample sizes instead of coercing floats with `int()`.
- Added API and experiment-store tests rejecting fractional calibration sample sizes before rows can be serialized or persisted.
- Updated the completion audit with latest verification counts and calibration sample-size validation evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py tests/vision_planner/test_quality_metrics_extension.py -q`: 52 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/vision_planner -q`: 98 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 382 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 369 passed, 2 skipped; quality coverage 86.63% (5346/6171).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 494 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: calibration sample-size validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Persisted calibration row guard

- Tightened `tools/calibrate_judges.py` so persisted calibration rows are revalidated before drift alert and readiness logic consumes them.
- Added calibration tests rejecting corrupted persisted rows with non-finite kappa, non-integer sample sizes, string sample sizes, and timezone-less measurement timestamps.
- Updated the completion audit with latest verification counts and persisted calibration row validation evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 27 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 383 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 370 passed, 2 skipped; quality coverage 86.64% (5352/6177).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 495 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: persisted calibration row validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Quality response model coercion guard

- Tightened quality API response models so numeric evidence fields and boolean pass fields must already have the correct JSON types instead of being coerced from strings.
- Added API model tests rejecting string-coerced quality scores, behavioral thresholds, calibration kappa values, and pass booleans.
- Updated the completion audit with latest verification counts and response-boundary validation evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 44 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 383 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 370 passed, 2 skipped; quality coverage 86.69% (5360/6183).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 495 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: quality response model validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Snapshot capture response object guard

- Tightened `tools/capture_corpus_snapshots.py` so live upload and job polling JSON responses must decode to objects before default-flow snapshot evidence is built.
- Added snapshot capture tests rejecting invalid and non-object job JSON responses.
- Updated the completion audit with latest verification counts and snapshot capture response-shape validation evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_capture_corpus_snapshots.py -q`: 12 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 137 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 384 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 371 passed, 2 skipped; quality coverage 86.71% (5368/6191).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 496 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot capture response-shape validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Snapshot verifier type guard

- Tightened `tools/verify_corpus_snapshots.py` so default-flow boolean flags must be real booleans, job IDs must be non-empty strings, and capture timestamps must be strings with timezones.
- Added snapshot gate tests rejecting integer-coerced booleans plus non-string job IDs and capture timestamps.
- Updated the completion audit with latest verification counts and stricter snapshot verifier evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py -q`: 12 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 138 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 385 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 372 passed, 2 skipped; quality coverage 86.73% (5373/6195).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 497 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`; snapshot check reports `ready=false`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot verifier validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Calibration response timestamp guard

- Tightened `CalibrationRowResponse` so calibration API rows must expose timezone-aware ISO measurement timestamps.
- Added response model tests rejecting timezone-less and non-string calibration `measured_at` values.
- Updated the completion audit with latest verification counts and calibration response timestamp validation evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 44 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 385 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 372 passed, 2 skipped; quality coverage 86.72% (5383/6207).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 497 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: calibration response timestamp validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral model-scoped cache evidence

- Tightened the shared behavioral proxy runner so cache keys include the configured behavioral answerer model and cached results with mismatched model metadata are ignored.
- Stamped PDF and Office quality audit behavioral results with `behavioral_model` metadata, and added a runtime guard for explicit artifact-generator model overlap before proxy execution.
- Added tests for artifact-generator model-family rejection, model-scoped behavioral cache reuse, and PDF/Office audit behavioral model metadata.
- Updated the completion audit with latest verification counts and model-scoped cache evidence.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_behavioral_model_separation.py -q`: 18 passed.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/office/test_office_judges.py -q`: 36 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies tests/quality_judges -q`: 152 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 388 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 375 passed, 2 skipped; quality coverage 86.71% (5397/6224).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 500 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral model-scoped cache evidence is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Behavioral corpus model metadata gate

- Tightened `tools/verify_behavioral_corpus.py` so artifact-bound behavioral result rows must include behavioral answerer model metadata once corpus context is available.
- Added behavioral corpus gate validation rejecting missing behavioral model evidence and same-family overlap with recorded artifact-generator models.
- Updated corpus gate fixtures and the completion audit with latest verification counts and behavioral model metadata readiness evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 17 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 139 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 389 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 376 passed, 2 skipped; quality coverage 86.65% (5454/6294).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 501 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: behavioral corpus model metadata validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Imported calibration model metadata gate

- Tightened `tools/calibrate_judges.py` so external `--judge-results` rows must carry `judge_model` metadata when bound to corpus annotations.
- Added calibration binding validation rejecting missing judge model evidence and same-family overlap with annotation or row-level artifact-generator models.
- Updated calibration fixtures and the completion audit with latest verification counts and imported calibration model metadata evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 28 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 140 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 390 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 377 passed, 2 skipped; quality coverage 86.67% (5482/6325).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 502 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: imported calibration model metadata validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Pairwise calibration model metadata gate

- Tightened `tools/calibrate_judges.py` so external `--judge-comparisons` rows also carry `judge_model` metadata when bound to annotation pairwise comparisons.
- Added pairwise calibration binding validation rejecting missing judge model evidence and same-family overlap with recorded artifact-generator models.
- Updated pairwise calibration fixtures and the completion audit with latest verification counts and pairwise model metadata evidence.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 29 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 141 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 391 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 378 passed, 2 skipped; quality coverage 86.68% (5488/6331).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 503 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: pairwise calibration model metadata validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-08 - Active calibration malformed-row gate

- Tightened `backend/app/quality_calibration.py` so active calibration readiness reports malformed persisted calibration rows instead of trusting corrupted kappa/sample/timestamp values.
- Added an API calibration status regression that inserts a malformed SQLite calibration row directly and verifies the readiness payload exposes `malformed_calibrations`.
- Updated the completion audit with latest verification counts and active calibration malformed-row evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/api -q`: 50 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 392 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 379 passed, 2 skipped; quality coverage 86.50% (5511/6371).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 504 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: active calibration malformed-row validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review queue evidence validation

- Tightened `tools/sample_quality_reviews.py` so direct queue appends reject duplicate/inapplicable weak dimensions, malformed priority scores, malformed priority reasons, and timezone-less sampling timestamps.
- Tightened `backend/app/quality_routes.py` so persisted review queue rows are validated before list/claim/submit paths expose or mutate them.
- Added sampler and API regressions for malformed persisted queue evidence.
- Updated the completion audit with current verification counts and queue evidence validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 34 passed.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 50 passed.
- Verified `./.venv/bin/python -m pytest tests/api -q`: 55 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 143 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 399 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 386 passed, 2 skipped; quality coverage 86.40% (5592/6472).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 511 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: review queue evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Drift alert metric validation

- Tightened `tools/calibrate_judges.py` so latest and rolling-window drift alert helpers validate calibration metric shape before emitting alerts.
- Rolling-window drift alert ordering now uses parsed timezone-aware instants instead of lexical timestamp order.
- Added calibration tests for malformed drift metrics and mixed-offset rolling-window ordering.
- Updated the completion audit with current verification counts and drift-alert evidence validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 31 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 145 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 401 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 388 passed, 2 skipped; quality coverage 86.42% (5607/6488).
- Verified `./.venv/bin/python -m pytest -q`: 513 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: drift alert metric validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out promotion score validation

- Tightened `vision_planner/quality_evaluation.py` so direct strategy-promotion evaluation rejects empty identifiers, empty dimension names, boolean/non-finite/out-of-range scores, and non-object score maps.
- Added held-out evaluation tests for malformed public promotion score maps and identifiers.
- Updated the completion audit with current verification counts and held-out promotion validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 26 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 51 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 403 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 388 passed, 2 skipped; quality coverage 86.42% (5607/6488).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 515 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: held-out promotion score validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B run evidence validation

- Tightened `vision_planner/quality_evaluation.py` so controlled A/B success checks reject malformed direct run objects before counting them toward the three-run Phase G criterion.
- Added run-evidence validation for non-empty unique evaluated document IDs, target score presence, decision metadata consistency, boolean promotion state, finite target lift, and finite numeric regression deltas.
- Added held-out evaluation tests for malformed controlled A/B run evidence.
- Updated the completion audit with current verification counts and controlled A/B run validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 27 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 52 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 404 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 388 passed, 2 skipped; quality coverage 86.42% (5607/6488).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 516 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled A/B run validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Snapshot top-level quality-result guard

- Tightened `tools/verify_corpus_snapshots.py` so committed default-flow snapshot payloads reject a top-level `quality_result` field, not only `default_response_metadata.quality_result`.
- Added a snapshot-gate regression for ambiguous top-level quality result evidence.
- Updated the completion audit with current verification counts and snapshot evidence validation.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py -q`: 13 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_capture_corpus_snapshots.py -q`: 12 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus -q`: 146 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 405 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 517 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: snapshot evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out split identity validation

- Tightened `vision_planner/quality_evaluation.py` so deterministic proposal/holdout splits reject non-object records, missing stable document identities, and duplicate identities before assigning corpus entries to proposal or holdout sets.
- Preserved deterministic tiny-corpus fallback assignment while avoiding score-based removal ambiguity.
- Added held-out split tests for missing, duplicate, and non-object split records.
- Updated the completion audit with current verification counts and split-validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 30 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 55 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 408 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 520 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: held-out split validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B score-derived decision validation

- Tightened `vision_planner/quality_evaluation.py` so direct `HoldoutABEvaluation` evidence is rechecked against its baseline/candidate score maps before a controlled A/B run can count toward the three-run Phase G criterion.
- Controlled A/B validation now rejects forged target lifts, promoted flags, and regression maps that do not match score-derived promotion criteria.
- Updated held-out evaluation tests with score-derived decision consistency cases.
- Updated the completion audit with controlled A/B decision validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 30 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 55 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 408 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 520 passed, 2 skipped, 5 warnings.
- Gap: controlled A/B decision evidence is stricter, but the PRD still requires real controlled held-out A/B runs on a specialist corpus before Phase G can complete.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B source-hash evidence validation

- Extended `HoldoutABEvaluation` with `source_hashes` so held-out source artifact hashes are preserved after per-document aggregation.
- Tightened controlled A/B validation so every counted run must include exact source-hash coverage for its evaluated documents, rejecting missing, extra, or malformed hash evidence.
- Added held-out evaluation tests for aggregate hash preservation and malformed controlled-run source hash evidence.
- Updated the completion audit with source-hash-bound controlled A/B evidence validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 30 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 55 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 408 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 520 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled A/B hash evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out identity type validation

- Tightened `vision_planner/quality_evaluation.py` so corpus split, holdout aggregation, and quality-result aggregation do not coerce non-string `doc_id`/`document_hash`/`source_path` values into stable identities.
- Tightened controlled A/B source-hash validation so non-string source-hash map keys are rejected instead of stringified.
- Added tests for non-string split identities, holdout identities, result identities, and source-hash document IDs.
- Updated the completion audit with identity-type validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 31 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 56 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 409 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 521 passed, 2 skipped, 5 warnings.
- Gap: identity evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out dimension-set consistency validation

- Tightened `vision_planner/quality_evaluation.py` so candidate-only non-target dimensions are rejected instead of being treated as clean no-regression evidence.
- Added validation at public promotion, per-document holdout aggregation, and direct controlled A/B evidence boundaries.
- Added tests for extra candidate dimensions in promotion maps, holdout result rows, and controlled-run score maps.
- Updated the completion audit with dimension-set consistency evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 33 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 58 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 411 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 523 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: dimension-set evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out dimension-name validation

- Tightened `vision_planner/quality_evaluation.py` so direct and nested held-out score maps reject non-string dimension keys and duplicate names after trimming.
- Stopped stringifying nested `dimensions` keys before score validation, preserving malformed key evidence for rejection.
- Added tests for non-string and duplicate dimension names in promotion maps and holdout result rows.
- Updated the completion audit with dimension-name validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 34 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 59 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 412 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 524 passed, 2 skipped, 5 warnings.
- Gap: dimension-name evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out non-target evidence validation

- Tightened `vision_planner/quality_evaluation.py` so target-only score maps cannot count as proof that a Phase G strategy avoided non-target regressions.
- Added validation at public promotion, per-document holdout aggregation, and direct controlled A/B evidence boundaries.
- Added tests for target-only promotion maps, holdout rows, and controlled-run score maps.
- Updated the completion audit with non-target evidence validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 36 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 61 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 414 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 526 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: non-target evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out decision reason validation

- Tightened `vision_planner/quality_evaluation.py` so direct controlled A/B evidence rejects promotion reasons that do not match score-derived promotion criteria.
- Updated regression evidence fixtures to use the exact score-derived non-target regression reason.
- Added a malformed-run test for a forged decision reason.
- Updated the completion audit with decision-reason validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 36 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 61 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 414 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 526 passed, 2 skipped, 5 warnings.
- Gap: decision-reason evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out split source-artifact validation

- Tightened `vision_planner/quality_evaluation.py` so deterministic proposal/holdout corpus splits require valid source hashes and reject duplicate source artifacts before assignment.
- Added split tests for missing, duplicate, malformed, and nested `artifact_hashes.source_sha256` evidence.
- Updated valid split fixtures so split inputs are source-hash-bound.
- Updated the completion audit with split source-artifact validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 39 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 64 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 417 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 529 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: split source-artifact validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B run ID validation

- Extended `HoldoutABEvaluation` with `run_id`; aggregated holdout evaluations now get a deterministic run ID fingerprint when no external run ID is supplied.
- Tightened controlled A/B success validation so counted runs require non-empty unique run IDs, preventing repeated copies of the same run from satisfying the three-experiment criterion.
- Added tests for generated run IDs, empty run IDs, duplicate run IDs, and unique IDs across successful/regression series.
- Updated the completion audit with run-ID evidence validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 40 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 65 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 418 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 530 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled A/B run-ID validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out split salt validation

- Tightened `vision_planner/quality_evaluation.py` so deterministic proposal/holdout splits reject blank or non-string salts before partitioning.
- Added focused tests for malformed split salts.
- Updated the completion audit with split configuration validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 41 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 66 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 419 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 531 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: split salt validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out explicit run ID validation

- Tightened `vision_planner/quality_evaluation.py` so explicitly supplied holdout A/B `run_id` values must be non-empty strings; malformed explicit values no longer fall back to generated fingerprints.
- Added focused tests for invalid explicit holdout run IDs.
- Updated the completion audit with explicit run-ID boundary validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 42 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 67 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 420 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 532 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: explicit run-ID validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Source-hash-keyed holdout split

- Changed `deterministic_corpus_split()` to key proposal/holdout assignment on source artifact SHA-256 rather than `doc_id`, preventing annotation renames from moving documents between proposal and holdout sets.
- Added a regression test proving renamed document IDs preserve proposal/holdout membership by source hash.
- Updated the completion audit with source-hash-keyed split evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 43 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 68 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 421 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 533 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: split isolation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out A/B duplicate source artifact validation

- Tightened `evaluate_holdout_ab()` so direct holdout A/B evaluation rejects duplicate source artifacts under different document IDs.
- Added a regression test covering direct and nested source-hash evidence in duplicate holdout records.
- Updated the completion audit with direct held-out duplicate-source validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 44 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 69 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 422 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 534 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct held-out duplicate-source validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B duplicate evidence validation

- Tightened `evaluate_controlled_ab_success()` so repeated copies of the same source-hash/score evidence cannot count as distinct controlled A/B experiments under different run IDs.
- Added a normalized evidence fingerprint for each `HoldoutABEvaluation`.
- Updated controlled A/B success fixtures to use distinct evaluated source artifacts, and added a regression test for duplicate evidence with distinct run IDs.
- Updated the completion audit with duplicate evidence fingerprint validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: duplicate controlled A/B evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out promotion threshold floor validation

- Tightened `evaluate_strategy_promotion()` and `evaluate_holdout_ab()` so callers cannot relax Phase G promotion below the PRD thresholds: target-lift threshold must be at least 5pp and non-target regression allowance must be at most 2pp.
- Added tests for relaxed target-lift and regression thresholds at both public promotion and aggregated holdout boundaries.
- Updated the completion audit with PRD threshold enforcement evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: promotion threshold enforcement is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B required experiment floor validation

- Tightened `evaluate_controlled_ab_success()` so callers cannot lower the Phase G controlled A/B series requirement below three experiments.
- Added a regression check for `required_experiments=2`, preserving the existing positive-integer validation for malformed counts.
- Updated the completion audit with the hard controlled A/B experiment-count floor.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled A/B count validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B regression dimension-name validation

- Tightened direct `HoldoutABEvaluation` evidence validation so promotion-decision regression dimensions must be non-empty strings instead of being normalized with `str(...)`.
- Added a malformed controlled-run regression test for a non-string regression dimension key.
- Updated the completion audit with direct regression dimension-name validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct regression dimension validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B duplicate source artifact validation

- Tightened direct `HoldoutABEvaluation` evidence validation so multiple evaluated document IDs cannot point at the same source SHA-256.
- Added a malformed controlled-run test for duplicate direct-run source artifacts.
- Updated the completion audit with duplicate direct-run source artifact validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct duplicate source artifact validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B missing non-target score validation

- Tightened direct `HoldoutABEvaluation` evidence validation so candidate score maps must include every baseline non-target dimension before the run can count as controlled A/B evidence.
- Added a malformed controlled-run test for omitted candidate non-target dimensions.
- Updated the completion audit with direct candidate score-map completeness evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct candidate score-map validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G canonical source SHA validation

- Tightened Phase G source-hash validation so split, holdout, and direct controlled A/B evidence require lower-case SHA-256 digests, matching the corpus schema, annotation CLI, review queue, and sampler.
- Added regression coverage for upper-case source digests at corpus split and direct controlled-run evidence boundaries.
- Updated the completion audit with canonical source-hash evidence validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: source-hash canonicalization is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Holdout A/B strategy identifier normalization

- Tightened `evaluate_holdout_ab()` so returned `HoldoutABEvaluation` evidence preserves the same normalized strategy identifier as its nested promotion decision.
- Added coverage that aggregated evidence trims surrounding strategy-name whitespace before it can be used in controlled A/B series validation.
- Updated the completion audit with normalized aggregated strategy identifiers.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: aggregated strategy identifier handling is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B top-level identifier validation

- Tightened direct `HoldoutABEvaluation` evidence validation so top-level strategy and target-dimension identifiers must be non-empty strings before mismatch checks or duplicate-evidence fingerprints run.
- Normalized direct-run identifiers when building evidence fingerprints.
- Added malformed controlled-run cases for blank top-level strategy and target-dimension identifiers.
- Updated the completion audit with top-level controlled-run identifier validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct controlled-run identifier validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B nested decision identifier validation

- Tightened direct `HoldoutABEvaluation` evidence validation so nested `PromotionDecision` strategy and target-dimension identifiers must be non-empty strings before mismatch checks.
- Added malformed controlled-run cases for blank nested decision strategy and target-dimension identifiers.
- Updated the completion audit with nested promotion-decision identifier validation evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: nested promotion-decision identifier validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B canonical regression reporting

- Tightened `evaluate_controlled_ab_success()` so controlled-series regression reports use the canonical regression dimension names validated from each direct `HoldoutABEvaluation`.
- Added coverage proving a submitted regression key with surrounding whitespace is reported as the normalized dimension name.
- Updated the completion audit with canonical controlled-series regression reporting evidence.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 70 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 423 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 535 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled-series regression reporting is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Holdout A/B row object-shape validation

- Tightened `evaluate_holdout_ab()` and quality result row loading so holdout, baseline, and candidate rows must be object-shaped before aggregation.
- Added regression coverage for non-object holdout, baseline, and candidate rows.
- Updated the completion audit with holdout/result row object-shape validation and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 46 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 71 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 424 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 536 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: holdout/result row object-shape validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Holdout A/B score payload shape validation

- Tightened holdout A/B row loading so present `quality_dimensions` and nested `dimensions` payloads must be well-formed score containers instead of being silently ignored.
- Added regression coverage for non-object score payloads, nested dimensions missing `score`, and unsupported nested dimension payload shapes.
- Updated the completion audit with malformed row-level score payload rejection and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 47 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 72 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 425 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 537 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: row-level score payload validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Holdout A/B missing score evidence validation

- Tightened holdout A/B row loading so baseline/candidate result rows must include either `quality_dimensions` or `dimensions` before aggregation.
- Added coverage for a row with source identity but no score payload.
- Updated the completion audit from malformed score payload rejection to missing-or-malformed score payload rejection.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 47 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 72 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 425 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 537 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: missing score evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Holdout A/B empty score evidence validation

- Tightened holdout A/B row loading so empty `quality_dimensions` or `dimensions` containers are rejected before aggregation.
- Added coverage for empty score containers in the malformed score-payload cases.
- Updated the completion audit from missing-or-malformed score payload rejection to missing/empty/malformed score payload rejection.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 47 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 72 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 425 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 537 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: empty score evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B empty direct score-map validation

- Tightened direct `HoldoutABEvaluation` evidence validation so empty baseline or candidate score maps are rejected before target-dimension checks.
- Added malformed controlled-run cases for empty direct baseline and candidate score maps.
- Updated the completion audit with empty direct controlled-run score-map validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 47 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 72 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 425 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 537 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: direct score-map validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out source hash conflict validation

- Tightened held-out split/evaluation evidence loading so records that include both `source_sha256` and `artifact_hashes.source_sha256` must agree before the evidence can count.
- Added regression coverage for conflicting source-hash metadata on corpus split records, holdout records, and baseline result rows.
- Updated the completion audit with conflicting direct/nested source-hash metadata rejection and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 49 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 74 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 427 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 539 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: source-hash conflict validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Held-out source hash metadata shape validation

- Tightened held-out split/evaluation evidence loading so present `source_sha256`, `artifact_hashes`, and `artifact_hashes.source_sha256` fields must be structurally valid instead of being ignored when another hash field is usable.
- Added regression coverage for malformed direct source-hash metadata, non-object `artifact_hashes`, and malformed nested `artifact_hashes.source_sha256` on split, holdout, baseline, and candidate evidence rows.
- Updated the completion audit with malformed present source-hash metadata rejection and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 51 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 76 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 429 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 541 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: source-hash metadata shape validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B evaluation collection validation

- Tightened `evaluate_controlled_ab_success()` so malformed evidence collections such as scalars, strings, bytes, and mappings are rejected with a clear `ValueError` before individual run evidence can count.
- Added regression coverage for malformed controlled A/B evaluation collection shapes.
- Updated the completion audit with controlled-series evaluation collection shape validation and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 52 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 77 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 430 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 542 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled-series collection validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B source artifact independence validation

- Tightened `evaluate_controlled_ab_success()` so a source artifact hash cannot be reused across controlled A/B runs, even when the run ID, document ID, and score maps differ.
- Added regression coverage for reused source artifacts with changed scores so the new guard is distinct from exact duplicate-evidence fingerprint rejection.
- Fixed the Phase G test helper to assign default synthetic source hashes by document ID rather than by list position, matching the production source-hash keyed split behavior.
- Updated the completion audit with cross-run source-artifact reuse rejection and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 53 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 78 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 431 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 543 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled-run source artifact independence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B document identity independence validation

- Tightened `evaluate_controlled_ab_success()` so a normalized evaluated document ID cannot be reused across controlled A/B runs, even when the source hash and score maps differ.
- Added regression coverage for reused document IDs with changed source hashes and changed scores so the new guard is distinct from exact duplicate-evidence and source-artifact reuse rejection.
- Updated the completion audit with cross-run document-ID reuse rejection and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 54 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 79 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 432 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 544 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: controlled-run document identity independence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Controlled A/B decision reason type validation

- Tightened direct `HoldoutABEvaluation` evidence validation so nested `PromotionDecision.reason` must be a string before it is compared with the score-derived reason.
- Added regression coverage with a custom equality object that would otherwise compare equal to the expected reason string.
- Updated the completion audit with string-only promotion-decision reason validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 54 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 79 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 432 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 544 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: promotion-decision reason validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Holdout A/B record collection validation

- Tightened aggregate `evaluate_holdout_ab()` loading so `holdout_records`, `baseline_results`, and `candidate_results` must be iterable collections of objects instead of scalars, strings, bytes, or a single mapping.
- Added regression coverage for malformed holdout, baseline, and candidate record collections while preserving row-level non-object validation.
- Updated the completion audit with aggregate holdout/baseline/candidate record collection shape validation and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 55 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 80 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 433 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 545 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: record collection validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Corpus split record collection validation

- Tightened `deterministic_corpus_split()` so the split input must be an iterable collection of objects instead of a scalar, string, bytes, or a single mapping.
- Added regression coverage for malformed split record collections while preserving row-level non-object split record validation.
- Updated the completion audit with deterministic split record collection shape validation and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 56 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 81 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 434 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 546 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: split collection validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Corpus split minimum evidence validation

- Tightened `deterministic_corpus_split()` so valid split evidence must contain at least two records before proposal/holdout evidence can count.
- Added regression coverage for empty and one-record split inputs while preserving precise row-level validation for malformed records.
- Updated the completion audit with minimum two-record split evidence validation and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 57 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 82 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 435 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 547 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: split minimum evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Holdout cross-document dimension coverage validation

- Tightened holdout A/B aggregation so every evaluated holdout document must expose the same quality dimensions before aggregate no-regression evidence can count.
- Added regression coverage where each document has internally matched baseline/candidate dimensions, but the holdout set mixes different non-target dimensions.
- Updated the completion audit with consistent cross-document dimension coverage validation and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 58 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 83 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 436 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 389 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 548 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: holdout dimension coverage validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G vision strategy map targets

- Added the PRD-named `vision.py` targets to `dimension_strategy_map.yaml` for alt-text and complex-content strategies.
- Added proposer tests proving the map declares `VisionProcessor.generate_alt_text`, `VisionProcessor.recreate_chart_as_svg`, and `VisionProcessor.describe_diagram`, and that generated strategy metadata carries the expanded target list.
- Updated the completion audit with the concrete `vision.py` target declarations and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_proposer_dimension_aware.py -q`: 18 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 84 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 437 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 390 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 549 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: strategy map target coverage is closer to the PRD, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G reading-order strategy map targets

- Added the PRD-named planner `fix_reading_order` action guidance target to `tighten_reading_order_*` alongside the existing grounder region-detection target.
- Added proposer coverage proving the reading-order strategy map entry declares both required harness targets.
- Updated the completion audit with the multi-target reading-order declaration and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_proposer_dimension_aware.py -q`: 19 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 85 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 438 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 391 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 550 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: strategy map target coverage is closer to the PRD, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G link text planner action

- Added the PRD-named `rewrite_link_text` planner action to the baseline harness and prompt schema for non-descriptive link text.
- Added a conservative executor implementation that sets `/Alt` and `/ActualText` on existing `/Link` structure elements without changing visible page text, and skips non-link targets.
- Added focused harness/executor tests for action exposure, link accessible-name updates, and non-link skip behavior.
- Updated the completion audit with the link-text action evidence and the new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_harness_link_text_action.py -q`: 3 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 88 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 441 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 391 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 553 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total annotations 0 < required 50`, `PDF annotations 0 < required 30`, `Office annotations 0 < required 20`, `phase_a_ready=false`, and `total_annotations=0`; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: link-text action coverage is closer to the PRD, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G link text executor dispatch coverage

- Added regression coverage proving `execute_plan()` dispatches planner-emitted `rewrite_link_text` operations end-to-end and persists `/Alt` plus `/ActualText` on the output PDF's `/Link` StructElem.
- Added rejection coverage for blank `replacement_text` so malformed link-text operations fail without mutating the target element.
- Updated the completion audit with the dispatch coverage and new full-suite count.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_harness_link_text_action.py -q`: 5 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 90 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 443 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 391 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 555 passed, 2 skipped, 5 warnings.
- Gap: link-text executor dispatch is covered, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G concrete target hook isolation

- Tightened `validate_dimension_strategy_map()` so every concrete target hook is globally unique across Phase G strategies, not just each strategy's primary hook.
- Added proposer regression coverage proving duplicate secondary target hooks are rejected before a strategy map can claim overlapping harness or `vision.py` extension points.
- Updated the completion audit with concrete target-hook isolation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_proposer_dimension_aware.py -q`: 20 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 91 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 444 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 392 passed, 2 skipped; quality coverage 86.43% (5609/6490).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 556 passed, 2 skipped, 5 warnings.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing behavioral results; calibration dry run reports no annotation JSON files.
- Gap: concrete Phase G hook isolation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PPTX per-slide metadata validation

- Added shared PPTX `slide_count` metadata validation so per-slide fallback signals reject booleans, strings, floats, and negative integers instead of coercing them into slide counts.
- Wired the validation through PPTX reading-order, slide-title, heading-semantics, slide-title navigation, and slide-reading-order behavioral proxy paths.
- Added Office judge/proxy regression tests for invalid per-slide metadata before fallback evidence can be emitted.
- Updated the completion audit with PPTX per-slide metadata validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/office/test_office_judges.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 71 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies tests/quality_judges -q`: 154 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 446 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 394 passed, 2 skipped; quality coverage 86.45% (5625/6507).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 558 passed, 2 skipped, 5 warnings.
- Gap: PPTX per-slide metadata is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - XLSX sheet-name metadata validation

- Tightened explicit XLSX `sheet_names` evidence so sheet-organization judges/proxies reject scalar, non-string, and blank sheet-name metadata instead of coercing values into sheet-navigation signals.
- Added Office judge/proxy regression tests for malformed `sheet_names` metadata before explicit sheet evidence can be emitted.
- Updated the completion audit with XLSX sheet-name metadata validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/office/test_office_judges.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 73 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies tests/quality_judges -q`: 156 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 448 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 396 passed, 2 skipped; quality coverage 86.47% (5635/6517).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 560 passed, 2 skipped, 5 warnings.
- Gap: XLSX sheet-organization metadata is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Screen-reader generated object transcript detection

- Tightened raw screen-reader transcript analysis so generated unlabeled object announcements such as `Graphic 12` and `Unlabeled image` are flagged while descriptive phrases such as `Company logo graphic` are not.
- Added shared transcript regression coverage for generated object announcements.
- Updated the completion audit with the transcript-analysis evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_transcript_analysis.py tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 71 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies tests/quality_judges -q`: 157 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 449 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 397 passed, 2 skipped; quality coverage 86.48% (5650/6533).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 561 passed, 2 skipped, 5 warnings.
- Gap: transcript analysis is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PDF complex-content target filtering

- Tightened `PDFComplexContentJudge` so it targets formulas and chart/graph/diagram/data-like figures instead of scoring every simple figure or image as complex content.
- Added PDF judge regression coverage proving simple logo/headshot figures are ignored by the complex-content dimension while thin chart descriptions are still flagged.
- Updated the completion audit with the complex-content targeting evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/pdf/test_pdf_judges.py -q`: 11 passed.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies tests/quality_judges -q`: 159 passed.
- Verified `./.venv/bin/python -m pytest tests/api tests/corpus tests/behavioral_proxies tests/quality_judges tests/vision_planner -q`: 451 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 399 passed, 2 skipped; quality coverage 86.53% (5660/6541).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 563 passed, 2 skipped, 5 warnings.
- Gap: PDF complex-content targeting is sharper, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review sampler candidate shape validation

- Tightened `tools/sample_quality_reviews.py` so candidate JSONL rows and direct sampler candidates reject non-string identity/source/class fields instead of coercing them with `str(...)`.
- Candidate score/confidence fields now treat explicitly provided empty non-object values as malformed evidence instead of falling back to an omitted empty object, and direct candidates are validated against the same format/dimension matrix before sampling.
- Added sampler regression coverage for malformed scalar fields, empty non-object score maps, malformed sampling arguments, malformed direct candidates, and direct source-hash binding.
- Updated the completion audit with the stricter sampler validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 39 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 201 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 404 passed, 2 skipped; quality coverage 86.63% (5694/6573).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 568 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: review sampling evidence is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Drift alert emitter validation

- Tightened `emit_drift_alerts()` so alert payloads are revalidated before writing JSONL rows or posting to a webhook.
- Added validation for alert event, judge identifiers, format/dimension applicability, finite kappa fields, positive sample/window sizes, and timezone-aware timestamps.
- Restricted optional drift alert webhooks to HTTP(S) URLs.
- Added calibration regression tests for malformed alert rows leaving no log side effects and non-HTTP webhook rejection.
- Updated the completion audit with the stricter drift alert emission evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 33 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 203 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 406 passed, 2 skipped; quality coverage 86.60% (5720/6605).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 570 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: drift alert emission is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Loop stopping criteria artifact

- Added `v2_docs/quality-layer-loop-stopping-criteria.md` to document explicit stop/escalation criteria for calibration, judge prompt/rubric iteration, review sampling, drift alerts, default-flow regressions, Phase G holdout evaluation, and the phase build loop.
- Added artifact-tracking coverage so the loop criteria document remains present and names the PRD-required kappa, prompt-iteration, no-auto-retrain, byte-identical regression, controlled A/B, lift/regression, and no-progress criteria.
- Updated the completion audit with the stopping-criteria evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_artifact_tracking.py -q`: 5 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 204 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 407 passed, 2 skipped; quality coverage 86.60% (5720/6605).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 571 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: loop stopping criteria are now documented and guarded, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review queue pagination evidence

- Added endpoint coverage proving `GET /v1/quality/review/queue` applies `format` filtering before `limit`/`offset` pagination and returns the filtered total.
- Updated the completion audit to call out the PRD-required paginated, filterable specialist queue evidence.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 51 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 205 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 408 passed, 2 skipped; quality coverage 86.60% (5720/6605).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 572 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: specialist review queue pagination is now directly covered, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Quality route API-key coverage

- Added route-wide API-key regression coverage for the quality dimensions, calibration, PDF audit, Office audit, review queue, review claim, and review submit endpoints.
- Updated the completion audit so the PRD `X-API-Key` gating requirement is backed by concrete coverage across the full quality router, not just one representative route.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 52 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 206 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 409 passed, 2 skipped; quality coverage 86.60% (5720/6605).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 573 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: quality route API-key coverage is broader, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review claim identity validation coverage

- Added endpoint regression coverage proving blank `doc_id` and `reviewer_id` values on `POST /v1/quality/review/claim` are rejected before queue mutation.
- Updated the completion audit with the claim identity validation evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 54 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 208 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 411 passed, 2 skipped; quality coverage 86.63% (5722/6605).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 575 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: review claim input validation is directly covered, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Reviewer-key wrong-key coverage

- Extended specialist review endpoint tests so `GET /review/queue`, `POST /review/claim`, and `POST /review/submit` reject both missing and wrong `X-Reviewer-Key` values when reviewer keys are configured.
- Updated the completion audit to distinguish missing-key and wrong-key reviewer authorization coverage.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 54 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 208 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 411 passed, 2 skipped; quality coverage 86.63% (5722/6605).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 575 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: reviewer-key authorization coverage is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review queue reviewer identity validation

- Tightened persisted review queue row validation so present `claimed_by` and `completed_by` fields must be non-empty strings, matching the reviewer identity fields written by claim/submit flows.
- Added endpoint regression coverage for blank `claimed_by` and blank `completed_by` rows failing before queue exposure.
- Updated the completion audit with the stricter persisted queue identity validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 56 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 210 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 413 passed, 2 skipped; quality coverage 86.64% (5725/6608).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 577 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: persisted queue reviewer identity validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review queue status metadata validation

- Tightened persisted review queue row validation so `claimed` rows require `claimed_by` plus timezone-aware `claimed_at`, and `completed` rows require timezone-aware `completed_at`.
- Updated review endpoint fixtures to use queue states matching the claim/submit mutation outputs.
- Added endpoint regression coverage for claimed rows missing `claimed_at` and completed rows missing `completed_at`.
- Updated the completion audit with the stricter queue status metadata validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 58 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 212 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 415 passed, 2 skipped; quality coverage 86.64% (5731/6615).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 579 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: persisted queue status metadata validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Sampler existing queue validation

- Tightened `tools/sample_quality_reviews.py` so existing queue rows are fully validated before new sampled review items are appended.
- Existing queue validation now rejects malformed status, reviewer identity fields, source hashes, priority metadata, weak dimensions, timestamps, and claimed/completed status metadata.
- Added sampler regression coverage for malformed existing claimed/completed queue state and updated completed-row fixtures with completion timestamps.
- Updated the completion audit with the stricter sampler existing-queue validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 40 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 213 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 416 passed, 2 skipped; quality coverage 86.57% (5770/6665).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 580 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: sampler queue validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Quality endpoint response envelope validation

- Tightened `backend/app/quality_routes.py` response envelope models for quality dimensions, calibration lists, review queues, review claim results, and review submit results so malformed container shapes, coerced booleans/integers, and invalid counts are rejected before serialization.
- Expanded OpenAPI regression coverage so every quality endpoint advertises its intended response schema, not just the PDF audit `QualityResultResponse` schema.
- Updated the completion audit with the stricter response model/OpenAPI evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 59 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 214 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 417 passed, 2 skipped; quality coverage 86.65% (5820/6717).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 581 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: quality endpoint schemas and response envelope validation are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review submission identity validation

- Tightened `POST /v1/quality/review/submit` so present top-level `doc_id`, `format`, and `reviewer_id` values must be non-empty strings before any annotation, queue, calibration, or submission-log side effects.
- Tightened submitted calibration row validation so `judge_id`, `judge_version`, `format`, and `dimension` must be non-empty strings before registry matching or persistence.
- Added no-side-effect API regressions for malformed review submission identity and malformed calibration row identity.
- Updated the completion audit with the stricter review submission/calibration identity evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py -q`: 66 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 221 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 424 passed, 2 skipped; quality coverage 86.67% (5832/6729).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 588 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: review submission evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Quality response identity validation

- Tightened quality API response models so response identity fields are non-empty strings, nested evidence containers have object/list shape, response dimensions are applicable to their format, and nested result map keys/formats match their payloads.
- Tightened `ExperimentStore.record_judge_calibration()` so blank/non-string judge IDs, judge versions, formats, and dimensions are rejected at the persistence boundary before readiness evidence can be stored.
- Added response-model regression coverage for malformed identity fields, inapplicable dimensions, malformed finding containers, nested result key mismatches, invalid `n/a`/failing dimension lists, and calibration row identity validation.
- Added experiment-store regression coverage for blank calibration judge identifiers.
- Updated the completion audit with stricter response-model and calibration-store identity evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py tests/vision_planner/test_quality_metrics_extension.py -q`: 75 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py tests/vision_planner -q`: 313 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 425 passed, 2 skipped; quality coverage 86.59% (5893/6806).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 589 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: quality response and calibration-store identity validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Calibration external row string validation

- Tightened `tools/calibrate_judges.py` external judge-result parsing so required identifiers are non-empty strings and optional artifact path/hash/model metadata, when present, must be strings instead of being coerced.
- Tightened external judge-comparison parsing with the same string-shape validation for required identifiers, candidate paths, candidate hashes, judge model, and artifact-generator model metadata.
- Added corpus-tool regression coverage for numeric judge-result identity/model/path/hash fields and numeric judge-comparison identity/model/hash fields.
- Updated the completion audit with stricter external calibration row evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 35 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 224 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 427 passed, 2 skipped; quality coverage 86.59% (5915/6831).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 591 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: external calibration-row validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Behavioral corpus row string validation

- Tightened `tools/verify_behavioral_corpus.py` so behavioral result rows reject non-string `doc_id`, `format`, variant aliases, artifact path/hash aliases, and artifact-generator model metadata instead of coercing or ignoring malformed values.
- Added behavioral corpus gate regression coverage for numeric result identity fields, artifact metadata, and artifact-generator model metadata.
- Updated the completion audit with stricter behavioral result row evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 19 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 226 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 429 passed, 2 skipped; quality coverage 86.68% (5959/6875).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 593 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: behavioral result row validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review queue falsy metadata validation

- Tightened `tools/sample_quality_reviews.py` so present `source_sha256` must be a string digest and present `weak_dimensions` must be a list for both new queue items and existing queue rows.
- Tightened `backend/app/quality_routes.py` so persisted review queue rows reject present non-string/falsy `source_sha256` values instead of treating them as absent.
- Added sampler/API regressions for falsy source hashes and weak-dimension containers.
- Updated the completion audit with stricter review queue evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py tests/api/test_quality_routes.py -q`: 109 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 228 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 431 passed, 2 skipped; quality coverage 86.76% (5965/6875).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 595 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: review queue metadata validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Snapshot capture job identity validation

- Tightened `tools/capture_corpus_snapshots.py` so upload responses must provide a non-empty string job ID before polling.
- Tightened snapshot capture so final job payload IDs, when present, must be non-empty strings matching the upload job ID before default-flow evidence can be built.
- Added snapshot capture regressions for numeric upload job IDs and mismatched final job IDs.
- Updated the completion audit with stricter snapshot capture evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_capture_corpus_snapshots.py -q`: 14 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 230 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 433 passed, 2 skipped; quality coverage 86.78% (5976/6886).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 597 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: snapshot capture validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Snapshot capture polling validation

- Tightened `tools/capture_corpus_snapshots.py` so capture rejects boolean, non-finite, negative poll intervals and non-positive/non-finite timeouts before any network polling.
- Applied the same polling validation at the capture CLI boundary so malformed `--poll-interval` and `--timeout-seconds` fail before annotation selection or API calls.
- Added snapshot capture regressions for malformed direct polling arguments and malformed CLI polling arguments.
- Updated the completion audit with stricter snapshot capture evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_capture_corpus_snapshots.py -q`: 16 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 232 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 435 passed, 2 skipped; quality coverage 86.82% (5986/6895).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 599 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: snapshot capture polling validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Snapshot polling status validation

- Tightened `tools/capture_corpus_snapshots.py` so job polling accepts only non-empty string statuses in the API's supported set: `queued`, `running`, `done`, and `failed`.
- Malformed, missing, or unsupported job statuses now fail immediately instead of waiting for timeout.
- Added snapshot capture regressions for missing, non-string, unsupported, and queued/running/done polling status sequences.
- Updated the completion audit with stricter snapshot polling evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_capture_corpus_snapshots.py -q`: 18 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 234 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 437 passed, 2 skipped; quality coverage 86.94% (6004/6906).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 601 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: snapshot polling status validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Behavioral annotation identity validation

- Tightened `tools/verify_behavioral_corpus.py` so direct behavioral discrimination summaries reject non-string or blank annotation `doc_id`/`format` values and unsupported annotation formats before matching result rows.
- Added an `annotation_record_errors` summary bucket so malformed annotation evidence is reported separately from malformed result rows.
- Added behavioral corpus gate regression coverage for numeric annotation identity fields and unsupported annotation formats not counting toward per-format totals.
- Updated the completion audit with stricter behavioral annotation evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 20 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 235 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 438 passed, 2 skipped; quality coverage 86.99% (6027/6928).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 602 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: behavioral annotation identity validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Behavioral known-bad artifact path validation

- Tightened `tools/verify_behavioral_corpus.py` so `known_bad_artifact_paths` entries must be strings before they can resolve to artifacts or participate in result binding.
- Known-bad result artifact binding now compares only against non-empty string annotation paths instead of stringifying malformed path values.
- Added behavioral corpus gate regression coverage for non-string and empty known-bad annotation artifact paths.
- Updated the completion audit with stricter behavioral artifact evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 21 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 236 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 439 passed, 2 skipped; quality coverage 87.06% (6034/6931).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 603 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: behavioral known-bad artifact path validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Behavioral gold artifact metadata validation

- Tightened `tools/verify_behavioral_corpus.py` so direct gold result binding rejects non-string annotation `gold_remediation_path` and `artifact_hashes.gold_remediation_sha256` values before comparing result rows.
- Added behavioral corpus gate regression coverage proving malformed gold annotation artifact metadata cannot be matched by stringified result artifact values.
- Updated the completion audit with stricter behavioral gold artifact evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 22 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 237 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 440 passed, 2 skipped; quality coverage 87.08% (6045/6942).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 604 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: behavioral gold artifact metadata validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Behavioral result dimension metadata validation

- Tightened `tools/verify_behavioral_corpus.py` so behavioral result test names must be non-empty strings before pass/fail extraction or applicability checks.
- Tightened explicit behavioral result `dimension` metadata so present values must be strings instead of being coerced before applicability checks.
- Added behavioral corpus gate regression coverage for numeric behavioral test names and numeric explicit dimension metadata.
- Updated the completion audit with stricter behavioral result metadata evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 23 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 238 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 441 passed, 2 skipped; quality coverage 87.10% (6055/6952).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 605 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: behavioral result dimension metadata validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Behavioral result alias validation

- Tightened `tools/verify_behavioral_corpus.py` so behavioral result payload aliases are resolved by first-present field rather than truthiness.
- Malformed primary `behavioral` payloads now fail as malformed instead of falling through to `behavioral_results` or `results`.
- Added behavioral corpus gate regression coverage for malformed present result aliases.
- Updated the completion audit with first-present behavioral result alias evidence and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_behavioral_corpus_gate.py -q`: 24 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 442 passed, 2 skipped; quality coverage 87.09% (6060/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 606 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: behavioral result alias validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Experiment quality evidence key validation

- Tightened `ExperimentStore.record_experiment()` so `quality_dimensions` and `behavioral_results` must be object-shaped maps before persistence.
- Added validation that quality dimension and behavioral result keys must be non-empty, canonical strings, and that quality dimensions / mapped behavioral proxy dimensions are known before persistence.
- Expanded the vision-planner quality metrics regression test to cover non-object evidence maps, blank keys, numeric keys, whitespace-padded keys, and unknown quality/proxy keys.
- Updated the completion audit with stricter experiment-store quality evidence validation.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py -q`: 8 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py tests/vision_planner/test_proposer_dimension_aware.py -q`: 28 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 91 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 442 passed, 2 skipped; quality coverage 87.11% (6061/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 606 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: experiment-store evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Persisted experiment quality evidence validation

- Tightened `ExperimentStore._row_to_experiment()` so persisted `quality_dimensions_json` and `behavioral_results_json` must decode as valid JSON and pass the same quality evidence validation used before writes.
- Corrupted SQLite experiment rows now fail with experiment-scoped errors before Phase G failure analysis or review sampling can consume the evidence.
- Added regression coverage for invalid persisted JSON, non-object persisted maps, unknown quality dimensions, and unknown behavioral proxy names.
- Updated the completion audit with read-side persisted experiment quality evidence validation and new verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py -q`: 9 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 92 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 443 passed, 2 skipped; quality coverage 87.11% (6061/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 607 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: persisted experiment evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G canonical dimension evidence validation

- Tightened `vision_planner/quality_evaluation.py` so target dimensions, score-map dimensions, and controlled-run regression dimensions must be canonical PRD quality dimensions.
- Promotion and controlled A/B evidence now reject whitespace-normalized or unknown dimension names instead of treating them as valid holdout evidence.
- Expanded Phase G quality-evaluation tests for unknown score-map dimensions, non-canonical target dimensions, and malformed regression dimension evidence.
- Updated the completion audit with canonical known-dimension evidence validation for held-out promotion criteria.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 58 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 92 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 443 passed, 2 skipped; quality coverage 87.11% (6061/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 607 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: Phase G evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G format-applicable holdout evidence validation

- Tightened `vision_planner/quality_evaluation.py` so holdout records and result rows reject malformed or non-canonical format metadata before aggregation evidence can count.
- Holdout A/B aggregation now rejects baseline/candidate result rows whose declared format conflicts with the holdout record and rejects score-map dimensions that are not applicable to the active format.
- Added Phase G regression coverage for format-inapplicable score dimensions, result format mismatches, and malformed format metadata.
- Updated the completion audit with format-applicable held-out evidence validation and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 61 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 95 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 443 passed, 2 skipped; quality coverage 87.11% (6061/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 610 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: Phase G evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G controlled-run format evidence validation

- Added format evidence to `HoldoutABEvaluation` so controlled A/B run records carry per-document format metadata alongside source hashes.
- Tightened controlled A/B validation so direct run evidence must include canonical supported formats for every evaluated document before it can count.
- Controlled run score maps and regression dimensions now reject dimensions that are not applicable to the run format.
- Expanded Phase G regression coverage for malformed controlled-run format maps and format-inapplicable controlled-run score dimensions.
- Updated the completion audit with controlled-run format-applicable evidence validation and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 63 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 97 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 443 passed, 2 skipped; quality coverage 87.11% (6061/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 612 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: Phase G controlled-run validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G promotion format metadata validation

- Extended `evaluate_strategy_promotion()` with optional `document_format` validation for direct promotion checks while preserving existing callers.
- Direct promotion score maps now reject non-canonical/unsupported format metadata, target dimensions that do not apply to the format, and non-target dimensions that do not apply to the format.
- Holdout and controlled-run decision recomputation pass single-format evidence through the public promotion validator.
- Expanded Phase G regression coverage for malformed promotion format metadata and XLSX-inapplicable reading-order promotion evidence.
- Updated the completion audit with public promotion format metadata validation and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_evaluation.py -q`: 66 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 100 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 443 passed, 2 skipped; quality coverage 87.11% (6061/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 615 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: Phase G promotion validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Dimension metrics format applicability validation

- Tightened `vision_planner/scorer.py` so per-dimension metric computation validates the declared metrics format before reporting `DimensionMetrics`.
- Scorer metric aggregation now rejects quality dimensions and behavioral proxy dimensions that are not applicable to the requested format.
- Replaced the scorer's local behavioral proxy mapping with the shared quality-dimension mapper used by the rest of the quality layer.
- Added regression coverage for XLSX sheet-organization metrics, malformed scorer formats, and XLSX-inapplicable reading-order quality/behavioral metrics.
- Updated the completion audit with scorer-side format applicability validation and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py -q`: 12 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 103 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 446 passed, 2 skipped; quality coverage 87.11% (6061/6958).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 618 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: scorer-side metric validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Experiment record document-format persistence

- Added a backfill-safe `document_format` field/column to `ExperimentRecord` and `experiment_records`, defaulting legacy rows to `pdf`.
- Experiment persistence and readback now reject unsupported/non-canonical formats plus quality and behavioral evidence whose mapped dimensions are not applicable to the stored document format.
- Scorer aggregation now groups per-dimension metrics by stored experiment format and reports multi-format `format_breakdown` instead of hardcoding `pdf`.
- Review sampling from experiment records now uses the stored experiment format when no explicit CLI format override is provided and skips records outside an explicit format filter.
- Added regression coverage for format-specific experiment persistence, legacy migration ordering, persisted invalid formats, multi-format scorer breakdowns, proposer behavioral normalization with separate PPTX/XLSX records, and XLSX experiment sampling.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py tests/vision_planner/test_proposer_dimension_aware.py -q`: 35 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 40 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 106 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 239 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 449 passed, 2 skipped; quality coverage 87.06% (6071/6973).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 621 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: experiment records and scoring are more format-aware, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Experiment sampling stored-format default

- Corrected `tools/sample_quality_reviews.py sample-experiments` so omitting `--format` uses each stored experiment record's `document_format` instead of silently filtering to PDF.
- Explicit `--format` now remains a true filter over stored experiment formats.
- Added regression coverage for default XLSX experiment sampling and explicit XLSX filtering from a mixed-format experiment store.
- Updated the completion audit with the corrected stored-format sampling behavior and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 42 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 241 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 106 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 451 passed, 2 skipped; quality coverage 87.09% (6073/6973).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 623 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: experiment sampling now honors stored formats by default, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G proposer PDF-scope guard

- Tightened `vision_planner/proposer.py` so the failure report can include Office quality signals, but Phase G dimension-aware strategy generation only consumes PDF experiment quality evidence.
- Office-only PPTX/XLSX quality or behavioral failures no longer produce PDF harness evolution strategies while Office evolution remains out of scope for v1.
- Added regression coverage proving Office weak dimensions are still reported but do not create `recommended_strategies`.
- Updated the completion audit with the PDF-scope guard for Phase G strategy generation and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_proposer_dimension_aware.py -q`: 21 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 107 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 241 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 452 passed, 2 skipped; quality coverage 87.09% (6073/6973).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 624 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: Phase G proposer scope is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Review sampler behavioral-confidence applicability

- Tightened `tools/sample_quality_reviews.py` so JSONL, direct, and experiment-derived review candidates validate `behavioral_confidence` keys through the shared behavioral-test-to-dimension mapper.
- Review sampling now rejects non-canonical behavioral confidence keys, unknown behavioral proxy names, and behavioral confidence evidence whose mapped dimension is not applicable to the candidate format.
- Added regression coverage for XLSX accepting `sheet_navigation` confidence while rejecting `reading_order_comprehension`, plus unknown behavioral confidence tests.
- Updated the completion audit with sampler-side behavioral confidence applicability validation and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_sample_quality_reviews.py -q`: 45 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 244 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 107 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 455 passed, 2 skipped; quality coverage 87.11% (6081/6981).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 627 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: review sampling evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Scorer behavioral-only dimension metrics

- Tightened `vision_planner/scorer.py` so direct metric computation rejects malformed quality scores and non-boolean behavioral results instead of coercing them.
- Document-class quality breakdowns now use the same quality score validation as per-dimension metric aggregation.
- Per-dimension metric aggregation now preserves behavioral-only dimensions, so behavioral proxy evidence is surfaced even when no quality judge score exists for that dimension.
- Added regression coverage for behavioral-only metrics plus malformed direct scorer evidence.
- Updated the completion audit with scorer-side behavioral-only metric coverage and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py -q`: 19 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 111 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 244 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 459 passed, 2 skipped; quality coverage 87.11% (6081/6981).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 631 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: scorer metrics now preserve behavioral-only evidence, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Format-specific failure report buckets

- Added format-specific failure-analysis buckets to `ExperimentStore.get_failure_patterns()` for weak dimensions, weak dimensions by document type, and behavioral proxy failures.
- `analyze_failures()` now surfaces those additive format-specific buckets while preserving existing PRD-shaped keys and keeping Phase G strategy generation PDF-scoped.
- Added regression coverage proving same-named document classes across formats remain separable in the full failure report and Office signals remain non-strategy-generating for the PDF proposer.
- Updated the completion audit with format-specific failure report evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py tests/vision_planner/test_proposer_dimension_aware.py -q`: 41 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 112 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 244 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 460 passed, 2 skipped; quality coverage 87.11% (6081/6981).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 632 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: failure analysis now keeps format-specific evidence visible, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Calibration readiness instant ordering

- Tightened `ExperimentStore.list_judge_calibration()` so calibration rows sort by parsed timezone-aware instant instead of lexicographic `measured_at` text.
- Malformed calibration timestamps now sort ahead of valid rows so readiness checks fail closed and surface malformed persisted evidence.
- Added regression coverage for timezone-offset ordering and for the active calibration gate selecting the actual latest row when timestamp text order disagrees with UTC instant order.
- Updated the completion audit with calibration readiness instant ordering and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/vision_planner/test_quality_metrics_extension.py tests/api/test_quality_routes.py -q`: 91 passed.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 113 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 245 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 462 passed, 2 skipped; quality coverage 87.12% (6082/6981).
- Verified `./.venv/bin/python -m compileall -q backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 634 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: calibration row ordering is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Office calibration gate coverage

- Added API regression coverage proving `/v1/quality/audit/office` rejects uncalibrated Office quality execution when `QUALITY_REQUIRE_CALIBRATION=true`.
- Added API regression coverage proving the Office audit endpoint runs after all required DOCX judge calibrations are present.
- Added worker regression coverage proving `/v1/office/remediate?quality=true` enforces the same calibration gate before Office quality audit execution.
- Updated the completion audit with Office calibration-gate coverage and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/api/test_quality_routes.py tests/test_engine_quality_opt_in.py -q`: 78 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 247 passed, 2 skipped.
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 113 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 465 passed, 2 skipped; quality coverage 87.17% (6085/6981).
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 637 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: Office calibration-gate tests are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Core quality result shape validation

- Tightened `QualityDimensionScore` so judge output rejects malformed `per_criterion` containers/keys, `judge_versions`, and `sample_findings` containers before serialization.
- Tightened `BehavioralTestResult` so behavioral proxy output rejects blank identity fields plus malformed finding and metadata containers at construction time.
- Tightened `QualityResult` so aggregate results reject malformed nested quality and behavioral result values before serialization.
- Added shared result-model regression coverage for the stricter constructor validation.
- Updated the completion audit with the stricter result-shape validation and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_rubrics.py tests/behavioral_proxies/shared/test_behavioral_model_separation.py tests/quality_judges/shared/test_behavioral_precedence.py -q`: 37 passed.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/shared/test_rubrics.py tests/quality_judges/shared/test_behavioral_precedence.py -q`: 19 passed.
- Verified `./.venv/bin/python -m pytest tests/quality_judges tests/behavioral_proxies -q`: 162 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 247 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 468 passed, 2 skipped; quality coverage 87.20% (6119/7017).
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 640 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: result evidence validation is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase G coverage gate scope

- Expanded `tools/quality_coverage.py` so the quality coverage gate measures `vision_planner/quality_evaluation.py` directly.
- Added `tests/vision_planner/test_quality_evaluation.py` to the traced default quality test arguments.
- Updated the coverage guard test so the default target set must include both the behavioral corpus verifier and Phase G holdout/evaluation module.
- Updated the completion audit with the expanded coverage scope and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_coverage.py tests/vision_planner/test_quality_evaluation.py -q`: 73 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 534 passed, 2 skipped; quality coverage 87.71% (6690/7627).
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 113 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 247 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 640 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: Phase G coverage is measured directly, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Vision planner quality coverage scope

- Expanded `tools/quality_coverage.py` so the quality coverage gate also measures `vision_planner/scorer.py`, `vision_planner/experiment_store.py`, and `vision_planner/proposer.py`.
- Updated the coverage guard test so the default target set must keep measuring the per-dimension scorer/store/proposer integration surfaces.
- Updated the completion audit with the expanded coverage scope and current verification counts.
- Verified one-off expanded target coverage before committing the scope: quality coverage 86.46% (7424/8587), with `experiment_store.py` 81.89%, `proposer.py` 70.18%, and `scorer.py` 77.78%.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_coverage.py tests/vision_planner/test_quality_metrics_extension.py tests/vision_planner/test_proposer_dimension_aware.py -q`: 49 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 534 passed, 2 skipped; quality coverage 86.46% (7424/8587).
- Verified `./.venv/bin/python -m pytest tests/vision_planner -q`: 113 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 247 passed, 2 skipped.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 640 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: per-dimension vision-planner quality surfaces are measured directly, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Default-flow snapshot quality flag guard

- Tightened `tools/verify_corpus_snapshots.py` so default-flow snapshots reject response metadata containing `quality=true` or any non-false `quality` value.
- Updated `tools/capture_corpus_snapshots.py` so captured payloads only mark `quality_false=true` when response metadata omits `quality` or records exact `false`.
- Added snapshot verifier and capture regression coverage for rejecting `quality=true` default metadata while accepting explicit `quality=false`.
- Updated the completion audit with the stricter default-flow snapshot guard and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_snapshot_gate.py tests/corpus/test_capture_corpus_snapshots.py -q`: 35 passed.
- Verified `./.venv/bin/python -m pytest tests/corpus tests/api/test_quality_routes.py -q`: 251 passed, 2 skipped.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 538 passed, 2 skipped; quality coverage 86.46% (7426/8589).
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python -m pytest -q`: 644 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: default-flow snapshot evidence is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - CI compile scope for quality calibration and planner surfaces

- Expanded the `quality-checks` compile step so it explicitly compiles `backend/app/quality_calibration.py` plus the Phase G planner quality surfaces measured by the coverage gate.
- Added artifact-tracking coverage that guards the CI compile list for quality routes, calibration, scorer, experiment store, proposer, and holdout evaluation modules.
- Updated the completion audit with the stricter CI compile scope and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_quality_artifact_tracking.py tests/corpus/test_quality_coverage.py -q`: 13 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 539 passed, 2 skipped; quality coverage 86.46% (7426/8589).
- Verified `./.venv/bin/python -m pytest -q`: 645 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Gap: CI now compiles the calibration and planner quality surfaces directly, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Drift alert webhook validation before side effects

- Tightened `tools/calibrate_judges.py` so drift alert webhook URLs are validated before writing alert-log rows or sending webhooks.
- Added regression coverage proving an invalid webhook URL does not leave a partial alert log behind.
- Updated the completion audit with the stricter drift-alert side-effect ordering and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/corpus/test_calibrate_judges.py -q`: 36 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 540 passed, 2 skipped; quality coverage 86.46% (7426/8589).
- Verified `./.venv/bin/python -m pytest -q`: 646 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: drift alert emission is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - XLSX sheet organization ordering signal

- Tightened `XLSXSheetNavigationTest` so workbook tab evidence flags overview, summary, index, contents, or dashboard sheets that appear after detail sheets.
- Added `sheet_ordering` rubric evidence to `XLSXSheetOrganizationJudge` and surfaced ordering failures through the existing sheet-purpose alignment score.
- Added Office judge and behavioral proxy regressions for a summary sheet placed after a detail sheet.
- Updated the completion audit with the stronger XLSX sheet-organization signal and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/office/test_office_judges.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 75 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 542 passed, 2 skipped; quality coverage 86.47% (7431/8594).
- Verified `./.venv/bin/python -m pytest -q`: 648 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Gap: XLSX sheet organization is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Screen-reader transcript unlabeled control signal

- Tightened shared transcript analysis so raw screen-reader transcripts flag unlabeled form controls such as bare `button`, `checkbox not checked`, and `blank edit required`.
- Kept descriptive control announcements such as `Submit button` and `Email text field` out of the error path.
- Updated the completion audit with the stronger transcript-analysis signal and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/shared/test_transcript_analysis.py tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/behavioral_proxies/office/test_office_behavioral_proxies.py -q`: 73 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 543 passed, 2 skipped; quality coverage 86.49% (7453/8617).
- Verified `./.venv/bin/python -m pytest -q`: 649 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Gap: screen-reader transcript analysis is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PPTX reading-order visual backtracking signal

- Tightened shared PPTX reading-order signals so per-slide shape order flags same-column bottom-before-top and same-row right-before-left visual backtracking.
- Exposed shape-order and visual-order text lists through the PPTX behavioral proxy and judge metadata, with a rubric-backed `shape_order_visual_sequence` criterion.
- Added Office proxy, Office judge, and rubric regressions for visual backtracking after the slide title.
- Updated the completion audit with the stronger PPTX per-slide reading-order evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 87 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 545 passed, 2 skipped; quality coverage 86.51% (7496/8665).
- Verified `./.venv/bin/python -m pytest -q`: 651 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Gap: PPTX per-slide reading-order signals are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - XLSX drawing alt-text specificity signal

- Tightened XLSX drawing alt-text assessment so generic chart/image descriptions and duplicated substitutive descriptions fail alongside missing alt text.
- Added the rubric-backed `drawing_alt_text_specificity` criterion and shared the stricter assessment between the XLSX behavioral proxy and quality judge.
- Added Office proxy, Office judge, and rubric regressions for generic and duplicate XLSX drawing descriptions.
- Updated the completion audit with the stronger XLSX alt-text evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 89 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 547 passed, 2 skipped; quality coverage 86.56% (7537/8707).
- Verified `./.venv/bin/python -m pytest -q`: 653 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Gap: XLSX alt-text signals are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - DOCX and PPTX alt-text specificity signal

- Added shared Office alt-text specificity assessment for DOCX/PPTX objects so generic descriptions and duplicated substitutive descriptions fail alongside missing alt text.
- Added the rubric-backed `ooxml_alt_text_specificity` criterion and shared the assessment between Office behavioral proxies and quality judges.
- Added DOCX and PPTX proxy/judge regressions for generic and duplicate OOXML alt text.
- Updated the completion audit with the stronger DOCX/PPTX alt-text evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 93 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 551 passed, 2 skipped; quality coverage 86.60% (7593/8768).
- Verified `./.venv/bin/python -m pytest -q`: 657 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Gap: DOCX/PPTX alt-text signals are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - XLSX formula complex-content context signal

- Extended XLSX complex-content judging beyond drawing OOXML so formula cells are inspected as complex content candidates.
- Added adjacent row/column label context extraction for formulas and a rubric-backed `formula_context` criterion.
- Added an XLSX judge regression proving unlabeled formula cells fail while labeled formulas pass.
- Updated the completion audit with the stronger XLSX complex-content evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 45 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 552 passed, 2 skipped; quality coverage 86.65% (7642/8819).
- Verified `./.venv/bin/python -m pytest -q`: 658 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Gap: XLSX complex-content signals are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - DOCX equation complex-content context signal

- Extended DOCX complex-content judging beyond drawing OOXML so math/equation paragraphs are inspected as complex content candidates.
- Added same-paragraph explanatory text extraction for equations and a rubric-backed `equation_context` criterion.
- Added a DOCX judge regression proving an unlabeled equation paragraph fails while a contextualized equation passes.
- Updated the completion audit with the stronger DOCX complex-content evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 46 passed.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 553 passed, 2 skipped; quality coverage 86.69% (7699/8881).
- Verified `./.venv/bin/python -m pytest -q`: 659 passed, 2 skipped, 5 warnings.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `git diff --check`.
- Verified readiness gates still block on missing corpus data: annotation coverage reports `total_annotations=0`, `phase_a_ready=false`, and missing PDF/Office minimums; snapshot check reports `ready=false` and `total_annotations=0`; behavioral check reports no annotations and missing `behavioral_results.jsonl`; calibration dry run reports no annotation JSON files.
- Gap: DOCX complex-content signals are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PPTX equation complex-content context signal

- Extended PPTX complex-content judging beyond drawing metadata so slide math/equation paragraphs are inspected as complex-content candidates.
- Reused the OOXML math-text and same-paragraph explanatory-context extraction for PPTX slide parts and updated the `equation_context` rubric wording to cover DOCX/PPTX.
- Added a PPTX judge regression proving an unlabeled equation paragraph fails while a contextualized equation passes.
- Updated the completion audit with the stronger PPTX complex-content evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 47 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 554 passed, 2 skipped; quality coverage 86.70% (7705/8887).
- Verified `./.venv/bin/python -m pytest -q`: 660 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: PPTX complex-content signals are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - DOCX repeated table-header flag semantics

- Tightened DOCX table-cell lookup so `w:tblHeader` only counts as a repeated header row when the flag is absent/default true or explicitly truthy.
- Added behavioral proxy and judge regressions proving `w:tblHeader w:val="false"` fails as a missing repeated header row instead of passing by element presence.
- Updated the completion audit with the stricter DOCX table-structure evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py -q`: 88 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 556 passed, 2 skipped; quality coverage 86.70% (7714/8897).
- Verified `./.venv/bin/python -m pytest -q`: 662 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: DOCX table-structure semantics are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - DOCX visual heading semantic-style signal

- Tightened DOCX heading navigation so short bold or large-font paragraphs that look like headings are flagged when they lack Word heading or outline semantics.
- Added a rubric-backed `visual_heading_semantics` criterion for DOCX heading judges.
- Added behavioral proxy and judge regressions proving visually styled heading text without semantic heading style fails navigation quality.
- Updated the completion audit with the stronger DOCX heading-semantics evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 100 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 558 passed, 2 skipped; quality coverage 86.71% (7768/8959).
- Verified `./.venv/bin/python -m pytest -q`: 664 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: DOCX heading semantics are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - XLSX sheet-organization multi-issue reporting

- Tightened XLSX sheet navigation so a single worksheet can preserve multiple deterministic issues, such as a default tab name and hidden data on the same sheet.
- Updated sheet-organization judge criteria to score name descriptiveness, purpose alignment, ordering, and hidden data sheets against the full issue set instead of only the first issue.
- Added behavioral proxy and judge regressions for a hidden default-named data sheet.
- Updated the completion audit with the stronger XLSX sheet-organization evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py -q`: 92 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 560 passed, 2 skipped; quality coverage 86.73% (7773/8962).
- Verified `./.venv/bin/python -m pytest -q`: 666 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: XLSX sheet organization is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PPTX table header-row semantics

- Tightened PPTX table-cell lookup so table shapes must expose explicit first-row header semantics in addition to non-empty header cells.
- Added a rubric-backed `pptx_table_header_row_presence` criterion for PPTX table judges.
- Added behavioral proxy and judge regressions proving a table with visible header text but `first_row=false` fails as missing header-row semantics.
- Updated the completion audit with the stronger PPTX table-structure evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/office/test_office_behavioral_proxies.py tests/quality_judges/office/test_office_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 104 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 562 passed, 2 skipped; quality coverage 86.72% (7788/8981).
- Verified `./.venv/bin/python -m pytest -q`: 668 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: PPTX table structure is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PDF table lookup non-empty cell signal

- Tightened PDF table-cell lookup so tagged tables require non-empty header text and non-empty data-cell text, not only the presence of `TH` and `TD` tags.
- Added behavioral proxy and judge regressions for empty PDF table header and data cells.
- Updated the completion audit with the stronger PDF table-structure evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py -q`: 35 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 564 passed, 2 skipped; quality coverage 86.71% (7791/8985).
- Verified `./.venv/bin/python -m pytest -q`: 670 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: PDF table lookup is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PDF decorative skip whitespace-alt signal

- Tightened PDF decorative-skip scoring so whitespace-only `/Alt` is treated as empty alternate text rather than a valid non-skipped description.
- Added behavioral proxy and judge regressions proving informative figures with whitespace alt text fail as skipped informative content.
- Updated the completion audit with the stronger PDF decorative evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py -q`: 37 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 566 passed, 2 skipped; quality coverage 86.71% (7791/8985).
- Verified `./.venv/bin/python -m pytest -q`: 672 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: PDF decorative-skip scoring is stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - PDF heading label descriptiveness signal

- Tightened PDF heading navigation so generic labels such as `Section` and duplicate heading labels fail the deterministic heading-quality proxy.
- Added rubric-backed `heading_label_descriptiveness` and `heading_label_uniqueness` criteria for PDF heading judges.
- Added behavioral proxy and judge regressions for generic and duplicate PDF heading labels.
- Updated the completion audit with the stronger PDF heading-semantics evidence and current verification counts.
- Verified `./.venv/bin/python -m pytest tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py tests/quality_judges/pdf/test_pdf_judges.py tests/quality_judges/shared/test_rubrics.py -q`: 49 passed.
- Verified `./.venv/bin/python -m compileall backend src tests tools`.
- Verified `./.venv/bin/python tools/quality_coverage.py check --threshold 70`: 568 passed, 2 skipped; quality coverage 86.75% (7818/9012).
- Verified `./.venv/bin/python -m pytest -q`: 674 passed, 2 skipped, 5 warnings.
- Verified `git diff --check`.
- Gap: PDF heading semantics are stricter, but the PRD still requires real specialist corpus artifacts, live default-flow snapshots, behavioral result rows, calibration metrics, and held-out A/B runs.
- Next: remaining completion depends on specialist corpus artifacts, snapshot evidence, behavioral run evidence, calibration evidence, and held-out A/B runs.

## 2026-05-09 - Phase summary audit completion

- Added all PRD phase summary artifacts required by `agent-prompt.md`:
  - `v2_docs/phase-A-summary.md`
  - `v2_docs/phase-B-summary.md`
  - `v2_docs/phase-C-summary.md`
  - `v2_docs/phase-D-summary.md`
  - `v2_docs/phase-E-summary.md`
  - `v2_docs/phase-F-summary.md`
  - `v2_docs/phase-G-summary.md`
  - `v2_docs/phase-H-summary.md`
  - `v2_docs/phase-I-summary.md`
- Re-ran no new full-suite checks for this documentation-only iteration.
- Remaining PRD blockers remain unchanged: no source artifacts, no specialist annotations, no gold/known-bad artifacts, no behavioral result rows, no judge-result rows, and no held-out A/B runs.

## 2026-05-09 - Completion runbook artifact and audit alignment

- Added `v2_docs/quality-layer-finish-runbook.md` with the exact command sequence to close remaining PRD gates for corpus, snapshots, behavioral results, calibration, sampling, and held-out promotion criteria.
- Updated `v2_docs/quality-layer-completion-audit.md` coverage counts and phase summary status row to match the latest verified runs.
- Re-ran targeted gate commands (`annotate_corpus.py`, `verify_corpus_snapshots.py`, `verify_behavioral_corpus.py`, `calibrate_judges.py` dry-run, `quality_coverage.py check --threshold 70`).
- Current state after latest verification: all implementation infrastructure is present; objective remains blocked on missing corpus annotations/artifacts and real judge/behavioral/evidence data.

## 2026-05-09 - Corpus onboarding template added

- Added `v2_docs/quality-layer-corpus-onboarding-template.md` with concrete JSON/JSONL examples and hash/reference workflow for producing PRD-compliant annotation, behavioral-result, and artifact rows.

## 2026-05-09 - Hard blocker ledger added

- Added `v2_docs/quality-layer-hard-blockers.md` to pin unresolved PRD-critical gating conditions to current command evidence.
- Re-ran gate checks to confirm current state:
  - `tools/annotate_corpus.py coverage` → blocked (`total_annotations=0`),
  - `tools/verify_corpus_snapshots.py check` → blocked (`ready=false`),
  - `tools/verify_behavioral_corpus.py check` → blocked (missing results),
  - `tools/calibrate_judges.py ... --enforce-readiness` → blocked (no annotations),
  - `tools/quality_coverage.py check --threshold 70` → pass (`86.75% (7819/9013)`).

## 2026-05-09 - Completion audit script improved for one-pass reporting

- Updated `v2_docs/quality-layer-audit.sh` to execute all five quality gates and report failures across the full checklist without exiting on the first failure.
- Added one-pass behavior summary (`== Done ==` vs `== Done with failures ==`) and retained command-level diagnostics plus captured stderr output for each step.
- Ran `bash v2_docs/quality-layer-audit.sh` to validate behavior:
  - `1) Corpus coverage` failed (`phase_a_ready=false`, `total_annotations=0`)
  - `2) Snapshot gate` failed (`ready=false`, `total_annotations=0`)
  - `3) Behavioral corpus gate` failed (`missing behavioral_results.jsonl`, no annotations)
  - `4) Calibration readiness` failed (`no annotation JSON files found`)
  - `5) Quality coverage` passed (`86.75%`, `7819/9013`, threshold 70)
  - Script exit status remained non-zero (`done with failures`) to keep CI/readiness automation honest.
- Remaining objective blockers are unchanged and remain external-data dependent (annotations, snapshots, behavioral rows, held-out evidence).

## 2026-05-09 - Audit inventory expansion

- Expanded `v2_docs/quality-layer-audit.sh` to include artifact inventory reporting after gates:
  - `annotation_rows` from `tools/corpus_annotations/v1/annotations`
  - `snapshot_rows` from `tools/corpus_annotations/v1/snapshots`
  - `behavioral_rows` existence/count of `behavioral_results.jsonl`
- Re-ran the one-pass audit:
  - same gate failures as before,
  - artifact inventory showed `annotation_rows=0`, `snapshot_rows=0`, `behavioral_rows=missing`.
- Objective remains blocked on external corpus artifacts and derived evidence (50+ annotations, default snapshots, behavioral rows, calibration/eval rows) before full PRD completion criteria can be claimed.

## 2026-05-09 - Make audit script directly executable

- Marked `v2_docs/quality-layer-audit.sh` as executable (`chmod +x`) so one-pass verification is directly runnable.
- Re-ran `v2_docs/quality-layer-audit.sh`; gates remain blocked on data availability:
  - `phase_a_ready=false`
  - snapshot/behavioral/calibration gates failed due missing annotations
  - quality coverage still passes (`86.75%`, `7819/9013`)
- Artifact inventory remains `annotation_rows=0`, `snapshot_rows=0`, `behavioral_rows=missing`.

## 2026-05-09 - Manifest and corpus directory evidence refreshed

- Verified corpus annotation manifest is still empty (`tools/corpus_annotations/v1/manifest.jsonl` has no rows).
- Confirmed one-pass audit script is executable: `-rwxr-xr-x v2_docs/quality-layer-audit.sh`.
- Reconfirmed corpus file inventory contains only `.gitkeep` stubs in `tools/corpus_annotations/v1/annotations/*` and `tools/corpus_annotations/v1/snapshots/*`.
- Re-ran the one-pass audit; failure pattern unchanged:
  - `phase_a_ready=false`, `total_annotations=0`
  - snapshots/behavioral/cali gates failed due missing annotations/results
  - quality coverage remains passing (`86.75%`, `7819/9013`, threshold 70)

## 2026-05-09 - Objective-evidence map added

- Added `v2_docs/quality-layer-objective-evidence-map.md` to provide a single mapping of objective→artifact→evidence→status.
- Updated completion audit index to include this map.

## 2026-05-15 - Alt-text pipeline hardening (45/45 corpus accessibility pass)

- Diagnosed regression on Chicano Studies corpus: 0/218 figures had vision-generated alts; all were fallback OCR dumps.
- Root cause: `create_provider_from_config` silently swallowed exceptions, leaving `vision_provider=None`. Hardened to `logger.warning(...)`.
- Five categories of alt-text bug now handled in the engine:
  1. Fallback OCR dumps (`"Image containing text:"` etc.) — flagged generic, self-heals
  2. `/P`-wrapping-image — `fix_image_struct_elems_retag` retags to `/Figure`
  3. `/Artifact`-wrapping-substantive-image — `fix_substantive_artifact_images` rewrites content stream
  4. Form-XObject-nested image — `fix_orphan_image_xobjects` adds `/Figure` via recursive resource walk
  5. Filename-path alts (`C:\Users\...\photo.jpg`) — flagged generic
- Adobe hover-text binding requires MCID linkage. `_rewrite_artifact_scope_to_figure` rewrites `/Artifact BMC ... EMC` → `/Figure <</MCID N>> BDC ... EMC` and extends the parent tree.
- Quieted two false-positive checks (ported from v1's c552c19): split-word threshold 1→12; skip near-black text over dark backgrounds.
- 9 commits on `main`: ec67495, 3d75000, 107afe3, fcb49b1, 8346424, c772007, 188670f, 9c6ec29 (plus baseline 5750800). All CI green.
- Final corpus result: all 45 PDFs PASS 33/33 on the engine accessibility checker.
- Detailed session notes: `v2_docs/session-memory-2026-05-15-alt-text.md`.
