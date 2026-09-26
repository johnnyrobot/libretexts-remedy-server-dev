# Phase I — Test hardening and formalization

## Goal
- Lock in quality-layer correctness with coverage, CI, and cross-phase integration.

## Exit criteria outcome
- **Met (infrastructure):** most quality-related tests and CI job are implemented; quality coverage is above threshold.
- **Met (PRD):** completion criteria are no longer blocked by held-out A/B promotion evidence.

## Evidence
- `.github/workflows/ci.yml` includes a `quality-checks` job with compile, tests, and quality coverage.
- `tools/quality_coverage.py check --threshold 70` passes.
- API, corpus, and shared validation suites include gating behavior and artifact checks, plus PRD control criteria.

## Blockers
- PRD-style held-out A/B evidence is available and recorded in:
  - `tools/corpus_annotations/v1/phase_g_holdout_runs.jsonl`
  - `tools/corpus_annotations/v1/phase_g_controlled_success.json`
