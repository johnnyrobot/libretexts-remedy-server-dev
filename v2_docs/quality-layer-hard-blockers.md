# Hard Blockers to PRD Completion (v2 Docs Scope)

This file is the final objective-critical blocker ledger.

## Current blocker status (as of latest run)

- `tools/corpus_annotations/coverage`: clear
  - Evidence: `./.venv/bin/python tools/annotate_corpus.py coverage --root tools/corpus_annotations/v1 --json`
  - Result: `phase_a_ready=true`, `total_annotations=50`, `pdf=30`, `office=20`.
- `tools/verify_corpus_snapshots`: clear
  - Evidence: `./.venv/bin/python tools/verify_corpus_snapshots.py check --root tools/corpus_annotations/v1 --json`
  - Result: `ready=true`, `total_annotations=50`.
- `tools/verify_behavioral_corpus`: clear
  - Evidence: `./.venv/bin/python tools/verify_behavioral_corpus.py check --root tools/corpus_annotations/v1 --results tools/corpus_annotations/v1/behavioral_results.jsonl --json`
  - Result: `ready=true`, 100% pass rates across formats.
- `tools/calibrate_judges` readiness: clear for threshold criteria (using `judge_results.jsonl`)
  - Evidence: `./.venv/bin/python tools/calibrate_judges.py calibrate --root tools/corpus_annotations/v1 --store /tmp/remedy-quality-experiments.db --dry-run --enforce-readiness --judge-results tools/corpus_annotations/v1/judge_results.jsonl --json`
  - Result: `calibration_ready=true`, metrics exist for every registered format x dimension x judge slice.
- `tools/quality_coverage`: passing
  - Evidence: `./.venv/bin/python tools/quality_coverage.py check --threshold 70`
  - Result: pass (above threshold).
- `phase-g holdout promotion evidence`: clear
  - Evidence:
    - `tools/corpus_annotations/v1/phase_g_holdout_runs.jsonl`
    - `tools/corpus_annotations/v1/phase_g_controlled_success.json`
  - Result: 3 controlled A/B runs, each with source-hash-bound evidence, achieved `target_lift=0.06` (>= 0.05), no non-target regressions, and final `passed=true`.

## Exact evidence required to clear each blocker

1) Annotation corpus
- Add >=50 total annotations with `>=30` PDF and `>=20` Office under:
  - `tools/corpus_annotations/v1/annotations/pdf/*.json`
  - `tools/corpus_annotations/v1/annotations/docx/*.json`
  - `tools/corpus_annotations/v1/annotations/pptx/*.json`
  - `tools/corpus_annotations/v1/annotations/xlsx/*.json`

2) Snapshot evidence
- Populate `tools/corpus_annotations/v1/snapshots/<format>/<doc_id>.json` for every manifest row via capture tool.

3) Behavioral evidence
- Add `tools/corpus_annotations/v1/behavioral_results.jsonl` rows for gold/known-bad with hash-bound `artifact_path` and `artifact_hash`.

4) Calibration evidence
- Ensure judge-result source rows are present and support per-slice kappa calculations against `QUALITY_MIN_COHENS_KAPPA` defaults.

5) Holdout promotion evidence
- Generate controlled holdout A/B run evidence with source-hash-bound row data and strategy promotions meeting:
  - target lift >= `0.05`
  - non-target regressions <= `0.02`
  - at least 3 successful controlled runs per promoted strategy.

## Latest clear status for blocker #5

- Cleared by committed evidence artifacts:
  - `tools/corpus_annotations/v1/phase_g_holdout_runs.jsonl`
  - `tools/corpus_annotations/v1/phase_g_controlled_success.json`

## Completion gate

Goal is complete when the above blockers are removed and the existing
`v2_docs/quality-layer-completion-audit.md` blocker list no longer includes these unresolved items.
