# Phase H — Office quality layer

## Goal
- Extend judges/proxies to DOCX/PPTX/XLSX in a format-aware way and expose Office quality auditing.

## Exit criteria outcome
- **Met:** Office judge/proxy namespaces and audit route exist with n/a handling and matrix checks.
- **Met:** judge/proxy namespaces, calibration evidence, and Phase G promotion evidence support are present.

## Evidence
- `src/project_remedy/quality_judges/office/{docx,pptx,xlsx}` and `quality_judges/office/*/prompts`.
- `src/project_remedy/behavioral_proxies/office/{docx,pptx,xlsx}` with per-format heuristics.
- Office audit route and opt-in worker plumbing in `backend/app/quality_routes.py` and engine integration.
- Tests cover prompt registration, format applicability, and Office quality report shape.
- Matrix `not_applicable_dimensions` behavior is represented.

## Blockers
- No blockers are tracked for this phase from a docs/artifact standpoint.
