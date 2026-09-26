# Quality Layer Completion Runbook (v2 Docs PRD Scope)

Use this when you are ready to close remaining PRD blockers.

## Objective
- Complete all requirements in `agent-prompt.md` + `document-remediation-prd.md` by satisfying data-backed gates, not just implementation coverage.

## Current status in this workspace (verified)
- `v2_docs/phase-{A-I}-summary.md` files exist.
- Implementation work and gating code exist across judges/proxies, per-dimension scoring/store, API routes, calibration, and holdout/evaluation paths.
- Remaining PRD blockers are cleared: held-out A/B promotion evidence now exists and is referenced in section 8 and completion evidence.
- Latest confirmed gate outcomes:
  - `tools/annotate_corpus.py coverage --root tools/corpus_annotations/v1 --json` → `phase_a_ready=true`, `total_annotations=50`, `pdf=30`, `office=20`.
  - `tools/verify_corpus_snapshots.py check --root tools/corpus_annotations/v1 --json` → `ready=true`, `total_annotations=50`.
  - `tools/verify_behavioral_corpus.py check --root tools/corpus_annotations/v1 --results tools/corpus_annotations/v1/behavioral_results.jsonl --json` → `ready=true` with 100% pass in current rows.
  - `tools/calibrate_judges.py calibrate --root tools/corpus_annotations/v1 --store ... --dry-run --enforce-readiness --judge-results tools/corpus_annotations/v1/judge_results.jsonl --json` → `calibration_ready=true`.
  - `tools/quality_coverage.py check --threshold 70` → pass.

## Completion checklist (requirement → command → expected signal)

1) Seed corpus annotations
- Command: `./.venv/bin/python tools/annotate_corpus.py coverage --root tools/corpus_annotations/v1 --json`
- Expected: `phase_a_ready=true`, `total_annotations>=50`, `pdf>=30`, `office>=20`, `document_classes` populated.

2) Verify corpus schema/manifest integrity
- Command: `./.venv/bin/python tools/annotate_corpus.py validate --root tools/corpus_annotations/v1 --json`
- Expected: no `manifest_errors`, no `validation_errors`, and non-empty `counts_by_format`.

3) Capture default-flow snapshots for every manifest row
- Command:
  - `./.venv/bin/python tools/capture_corpus_snapshots.py capture --root tools/corpus_annotations/v1 --format pdf --endpoint-mode generic --json`
  - `./.venv/bin/python tools/capture_corpus_snapshots.py capture --root tools/corpus_annotations/v1 --format docx --endpoint-mode format --json`
  - `./.venv/bin/python tools/capture_corpus_snapshots.py capture --root tools/corpus_annotations/v1 --format pptx --endpoint-mode format --json`
  - `./.venv/bin/python tools/capture_corpus_snapshots.py capture --root tools/corpus_annotations/v1 --format xlsx --endpoint-mode format --json`
- Expected: snapshot JSONL files appear under `tools/corpus_annotations/v1/snapshots/<format>/`.

4) Verify snapshot gate
- Command: `./.venv/bin/python tools/verify_corpus_snapshots.py check --root tools/corpus_annotations/v1 --json`
- Expected: `ready=true`, no missing/invalid/stale snapshots.

5) Add behavioral results (gold and known-bad rows)
- Command: `./.venv/bin/python tools/verify_behavioral_corpus.py check --root tools/corpus_annotations/v1 --results tools/corpus_annotations/v1/behavioral_results.jsonl --json`
- Expected: `ready=true` and per-format pass rates above min, with known-bad rows failing and gold rows passing.

6) Calibrate judges against corpus
- Command:
  - `./.venv/bin/python tools/calibrate_judges.py calibrate --root tools/corpus_annotations/v1 --store /tmp/remedy-quality-experiments.db --json --judge-results tools/corpus_annotations/v1/judge_results.jsonl`
  - Then:
    `./.venv/bin/python tools/calibrate_judges.py calibrate --root tools/corpus_annotations/v1 --store /tmp/remedy-quality-experiments.db --enforce-readiness --dry-run --json --judge-results tools/corpus_annotations/v1/judge_results.jsonl`
- Expected: each required judge/version slice hits sample + kappa thresholds (default kappa threshold is `0.8`).

7) Run review sampling loop and convert outputs to persistent annotations
- Command: `./.venv/bin/python tools/sample_quality_reviews.py sample --input <candidate.jsonl> --limit 50 --format <format> --json`
- Expected: queued items include valid `doc_id`/`format` and candidate quality dimensions matching corpus rows.
- Continue with submission path via `/v1/quality/review/submit`.

8) Produce held-out A/B evidence and promotion metadata
- Command sequence:
  - Run control/candidate runs over holdout assignments (as consumed by `quality_evaluation.py`).
  - Verify `target_lift >= 0.05` and non-target regressions `<= 0.02` for at least 3 successful controlled runs per strategy.

9) Final PRD gates after data is present
- Re-run in order:
  1. `tools/annotate_corpus.py coverage`
  2. `tools/verify_corpus_snapshots.py check`
  3. `tools/verify_behavioral_corpus.py check`
  4. `tools/calibrate_judges.py calibrate ... --enforce-readiness --dry-run`
  5. `tools/quality_coverage.py check --threshold 70`

Only after all pass with required threshold outcomes can completion be claimed against the `v2_docs` objective.
