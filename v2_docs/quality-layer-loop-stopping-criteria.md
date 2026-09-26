# Quality Layer Loop Stopping Criteria

Date: 2026-05-09

This document records the explicit stopping criteria for quality-layer loops so
calibration, regression handling, prompt tuning, and Phase G evaluation do not
depend on improvised decisions.

## Calibration And Judge Readiness

- Stop as successful only when every required judge/version slice for each
  annotated format meets the configured minimum sample count and Cohen's kappa
  threshold.
- Stop as blocked when no specialist annotation records exist, when required
  source/gold/known-bad artifacts are missing, or when judge rows cannot be
  hash-bound to annotation metadata.
- Do not route active quality execution around calibration failure. The active
  gate remains closed until readiness passes.

## Judge Prompt And Rubric Iteration

- If a judge is below threshold, first run it against known-good and known-bad
  corpus evidence to determine whether the rubric can distinguish the cases.
- If the judge cannot distinguish gold from known-bad evidence, revise the
  rubric or deterministic signals before prompt wording.
- If the judge distinguishes the cases but disagrees with specialists on edge
  cases, expand the calibration set for those edges.
- Stop and escalate after 3 unsuccessful prompt/rubric iterations for the same
  judge slice.

## Review Sampling And Drift Alerts

- Sampling is bounded by the CLI `--limit` and deterministic strata. The job
  exits after writing the selected review rows or reporting validation errors.
- Open review-queue items are deduplicated by `(format, doc_id)`; completed
  items may be sampled again only as new evidence.
- Drift alerting emits a structured row only when the latest or rolling-window
  kappa is below threshold and sample count is sufficient.
- Drift alerts do not auto-retrain or auto-promote changes. They stop at
  human-visible JSONL/webhook output.

## Default-Flow Regression Handling

- Stop immediately on any byte-identical default-flow regression for
  `/v1/remediate` or `/v1/office/remediate`.
- Treat the regression as P0: revert or isolate the offending change, fix the
  root cause, and add regression coverage before continuing.
- Snapshot capture/verifier tooling must fail zero-selection filters and
  malformed snapshot metadata rather than treating missing evidence as stable.

## Phase G Dimension-Aware Evaluation

- Split proposal and holdout evidence deterministically by source hash once.
- Iterate strategy hypotheses only on proposal-set evidence. Do not tune a
  strategy on holdout failures.
- Promote only after at least 3 controlled A/B runs show at least 5 percentage points of lift on the target dimension and no more than 2 percentage points of regression on any non-target dimension.
- Record failed strategies instead of deleting them.
- After 2 unsuccessful refinements for the same target hypothesis, stop and
  escalate for review.

## Phase Exit And Build Loop

- A phase can stop as complete only when its PRD exit criteria are met with
  concrete artifact evidence, not just passing unit tests.
- If 3 consecutive iterations make no progress on the same component, stop and
  ask for guidance.
- Append each completed iteration to `BUILD_LOG.md` with changed scope,
  verification, shifted metrics, and remaining blockers.
