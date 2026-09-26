# Phase F — Calibration sampling loop

## Goal
- Implement non-UI annotation sampling and readiness controls with minimal drift handling.

## Exit criteria outcome
- **Met (implementation + readiness):** sampling, calibration, and drift alert scaffolding implemented and tested, with readiness checks passing against current judge-result evidence.

## Evidence
- `tools/annotate_corpus.py` and `tools/sample_quality_reviews.py` provide JSONL queue and deterministic sampling.
- `tools/calibrate_judges.py` computes kappa and persists calibration slices; `--judge-results` and drift alert checks are supported and operational.
- `quality_judges/shared/base.py` enforces judge model-family separation.
- `tests/corpus/test_calibrate_judges.py`, `tests/corpus/test_quality_artifact_tracking.py` validate these paths.

## Blockers
- No remaining PRD blockers are tracked for this phase.
