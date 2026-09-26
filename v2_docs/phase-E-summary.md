# Phase E — Endpoints and opt-in execution

## Goal
- Add opt-in quality endpoints and route integration without changing default behavior.

## Exit criteria outcome
- **Met:** endpoint and wiring work completed; default flows remain unchanged.
- **Met (PRD):** evidence-backed promotion criteria now have held-out results in place for route-gated usage.

## Evidence
- `backend/app/quality_routes.py` added and mounted in `backend/app/main.py`.
- `/v1/quality/audit/pdf`, `/v1/quality/audit/office`, calibration/review routes implemented.
- `quality=true` query parameter implemented on remediation endpoints with regression tests.
- Worker path attaches quality results only when opt-in is true.

## Blockers
- PRD rollout blockers are no longer pending for this phase.
