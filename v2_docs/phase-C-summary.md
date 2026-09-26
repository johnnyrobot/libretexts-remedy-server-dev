# Phase C — PDF judges

## Goal
- Introduce format-scoped narrow judges with prompt-versioned rubrics and ensemble aggregation.

## Exit criteria outcome
- **Met (implementation + readiness):** Judge classes, prompts, rubric files, registry, and ensemble path are implemented and calibration readiness passes with current judge-result evidence.

## Evidence
- PDF judge classes in `src/project_remedy/quality_judges/pdf/*`, prompts in `src/project_remedy/quality_judges/pdf/prompts/*.md`.
- `quality_judges/shared/rubrics/*.yaml` and shared rubric tests are present.
- Calibration CLI supports judge/compare slices (`tools/calibrate_judges.py`).
- `tools/calibrate_judges.py calibrate --root tools/corpus_annotations/v1 --store /tmp/remedy-quality-experiments.db --dry-run --enforce-readiness --judge-results tools/corpus_annotations/v1/judge_results.jsonl --json` reports `calibration_ready=true`.

## Blockers
- No remaining PRD blockers are tracked for this phase.
