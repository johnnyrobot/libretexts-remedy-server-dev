# Phase G — Dimension-aware evolution

## Goal
- Add dimension-aware strategy generation and held-out controlled A/B evaluation.

## Exit criteria outcome
- **Met:** architecture and controls are implemented, including deterministic proposal/holdout splitting and promotion criteria validation.
- **Met (PRD):** source-hash-bound heldout A/B evidence exists for an `improve_alt_text_report` strategy (`alt_text`), with three successful controlled runs, each meeting PRD thresholds (`target_lift=0.06`, no non-target regressions), captured in:
  - `tools/corpus_annotations/v1/phase_g_holdout_runs.jsonl`
  - `tools/corpus_annotations/v1/phase_g_controlled_success.json`.

## Evidence
- `src/project_remedy/vision_planner/dimension_strategy_map.yaml` exists and map validation is enforced.
- `proposer.py` appends dimension-aware strategies alongside existing veraPDF proposals.
- `src/project_remedy/vision_planner/quality_evaluation.py` implements held-out split/evaluation logic and promotion gates.
- `tests/vision_planner/test_proposer_dimension_aware.py` and `tests/vision_planner/test_quality_evaluation.py` cover proposer and evaluator validations.

## Blockers
- No remaining Phase G blockers after adding source-hash-bound heldout control evidence in `tools/corpus_annotations/v1/phase_g_holdout_runs.jsonl` and `tools/corpus_annotations/v1/phase_g_controlled_success.json`.
