# Phase B — PDF behavioral proxies

## Goal
- Add format-namespaced behavioral proxies with deterministic signals and corpus-compatible outputs.

## Exit criteria outcome
- **Met:** Proxy modules and corpus integration are present, with behavioral gate passing on the seeded corpus.

## Evidence
- `src/project_remedy/behavioral_proxies/pdf/*` implemented plus registry/types in shared modules.
- Deterministic proxy tests exist and pass (`tests/behavioral_proxies/pdf/test_pdf_behavioral_proxies.py`).
- Behavioral corpus verifier requires and consumes behavior rows bound to annotated corpus (`tools/verify_behavioral_corpus.py`).
- Current run: `tools/verify_behavioral_corpus.py check --root tools/corpus_annotations/v1 --results tools/corpus_annotations/v1/behavioral_results.jsonl --json` reports `ready=true` with 100% pass rates.

## Blockers
- No remaining PRD blockers are tracked for this phase.
