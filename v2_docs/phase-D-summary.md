# Phase D — Per-dimension metrics extension

## Goal
- Extend scoring/store result model with dimension-level quality and behavioral metrics while retaining backwards compatibility.

## Exit criteria outcome
- **Met (implementation):** additive schema/migration and scorer extensions are in place.
- **Validation:** coverage now includes these surfaces.

## Evidence
- `src/project_remedy/vision_planner/scorer.py` includes `DimensionMetrics` and `ScoringResultV2`.
- `src/project_remedy/vision_planner/experiment_store.py` stores `document_format`, `quality_dimensions_json`, `behavioral_results_json`, and `judge_calibration`.
- `tests/vision_planner/test_quality_metrics_extension.py` and `tests/corpus/test_quality_coverage.py` cover these integrations.
- `tools/quality_coverage.py check --threshold 70` passes with these modules included in measured targets.

## Blockers
- No blockers remain for phase D.
