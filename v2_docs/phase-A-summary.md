# Phase A — Annotated reference corpus (2026-05-09)

## Goal
- Add a format-aware, versioned reference corpus layout with schema and tooling.

## Exit criteria outcome
- **Met (implementation):** Schema, manifest, annotations layout, and coverage CLI are implemented.
- **Met (dataset):** Corpus is seeded and coverage criteria are met.

## Evidence
- `tools/corpus_annotations/schema.json` defines format-aware schema with `format`, `format_specific`, and matrix-validating dimensions.
- `tools/annotate_corpus.py` includes `init`, `annotate`, `validate`, and `coverage` flows.
- `tools/annotate_corpus.py coverage --root tools/corpus_annotations/v1 --json` returns `phase_a_ready=true`, `total_annotations=50`, `pdf=30`, `office=20`.
- `BUILD_LOG.md` contains phase foundation and coverage entries documenting this state.

## Blockers
- No blockers remain for this phase; held-out strategy promotion evidence is present in `v2_docs`-tracked artifacts.
