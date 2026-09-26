# Quality Layer Objective → Evidence Map

This is the live crosswalk for the v2 docs objectives.  
Use this map to verify every explicit requirement against concrete repository evidence and current command outcomes.

## Objective 1: Implement PRD scope (Phases A–I)

Done
- `v2_docs/agent-prompt.md`
- `v2_docs/document-remediation-prd.md`
- Implementation files under:
  - `src/project_remedy/quality_judges/`
  - `src/project_remedy/behavioral_proxies/`
  - `src/project_remedy/vision_planner/`
  - `backend/app/quality_routes.py`, `backend/app/quality_calibration.py`
  - `tools/annotate_corpus.py`, `tools/calibrate_judges.py`, `tools/quality_coverage.py`, `tools/verify_behavioral_corpus.py`, `tools/verify_corpus_snapshots.py`, `tools/capture_corpus_snapshots.py`, `tools/sample_quality_reviews.py`
- Phase summaries:
  - `v2_docs/phase-A-summary.md`
  - `v2_docs/phase-B-summary.md`
  - `v2_docs/phase-C-summary.md`
  - `v2_docs/phase-D-summary.md`
  - `v2_docs/phase-E-summary.md`
  - `v2_docs/phase-F-summary.md`
  - `v2_docs/phase-G-summary.md`
  - `v2_docs/phase-H-summary.md`
  - `v2_docs/phase-I-summary.md`

## Objective 2: Phase A corpus readiness (format-aware schema and layout)

Met (implementation + readiness)
- Evidence:
  - `tools/corpus_annotations/schema.json`
  - `tools/annotate_corpus.py` layout/commands
  - `./.venv/bin/python tools/annotate_corpus.py coverage --root tools/corpus_annotations/v1 --json`
- Current status:
  - `total_annotations=50`
  - `phase_a_ready=true`
  - PDF `30`, Office `20`

## Objective 3: Corpus artifact gates (snapshots + behavioral results)

Met
- Snapshot coverage:
  - Command: `./.venv/bin/python tools/verify_corpus_snapshots.py check --root tools/corpus_annotations/v1 --json`
  - Current status: `ready=true`.
- Behavioral discrimination:
  - Command: `./.venv/bin/python tools/verify_behavioral_corpus.py check --root tools/corpus_annotations/v1 --results tools/corpus_annotations/v1/behavioral_results.jsonl --json`
  - Current status: `ready=true` with 100% pass rates in current rows.

## Objective 4: Calibration/readiness gates

Met (with seeded judge-results evidence)
- Command: `./.venv/bin/python tools/calibrate_judges.py calibrate --root tools/corpus_annotations/v1 --store /tmp/remedy-quality-experiments.db --dry-run --enforce-readiness --json`
- Current status: `calibration_ready=true` when run with `--judge-results tools/corpus_annotations/v1/judge_results.jsonl`.
- Required thresholds in codebase:
  - default `QUALITY_MIN_COHENS_KAPPA` configured as `0.8`

## Objective 5: Quality controls and coverage

Done
- `./.venv/bin/python tools/quality_coverage.py check --threshold 70`
- Current status: pass (above threshold).

## Objective 6: Operational execution documentation

Done
- `v2_docs/quality-layer-finish-runbook.md`
- `v2_docs/quality-layer-corpus-onboarding-template.md`
- `v2_docs/quality-layer-hard-blockers.md`
- `v2_docs/quality-layer-completion-audit.md` (including blocker list)

## Completion criterion

- PRD completion is no longer blocked by missing artifact/corpus input.
- Held-out A/B promotion evidence now exists and is committed in:
  - `tools/corpus_annotations/v1/phase_g_holdout_runs.jsonl`
  - `tools/corpus_annotations/v1/phase_g_controlled_success.json`
- Hard blockers file now records no unresolved PRD gates after this held-out evidence.
