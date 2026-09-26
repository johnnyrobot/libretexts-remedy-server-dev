# Session Memory: Adobe Remediation Loop (2026-05-12)

## Summary
- Committed Adobe-focused remediation work and pushed to `origin/main`.
- Commit: `19721c5`
- Message: `Tune Adobe alt-text remediation for associated-content edge cases`
- Scope included only `src/project_remedy/pdf_fixer.py`.

## What was changed
- Added Adobe-specific retain/clear controls for node-level remediations:
  - `PDF_ADOBE_ASSOCIATED_RETAIN_TYPES`
  - `PDF_ADOBE_ASSOCIATED_RETAIN_MCID_LIMIT`
  - `PDF_ADOBE_ACTUALTEXT_STALE_CLEAR_TYPES`
- Added helper `_should_retain_associated_alt(...)` to keep alt text on narrow patterns where Adobe flagged false positives.
- Added helper `_should_clear_stale_actual_text(...)` to clear stale `/ActualText` on narrow leaf nodes.
- Extended `_fix_empty_leaf_text_elements(...)` to:
  - clear stale `/ActualText` before removal heuristics,
  - safely remove no-content no-MCID leaves when not holding direct content.

## Verification done in this session
- Ran local checks via `PDFAccessibilityChecker` on all 45 remediated files in:
  - input root: `/Users/johnnyrobot/Desktop/Chicano Studies Docs`
  - output root: `/Users/johnnyrobot/Desktop/Chicano-remedy-server-v2`
- Results:
  - 45 files exist in output for all 45 inputs.
  - 45 files still had some manual findings (`doc-use-of-color`, `doc-color-contrast`, mostly `doc-reading-order`).
  - Remaining failed local checks:
    - `Fernndez-AbriendocaminosBrotherland-1994 1.pdf` → `page-content-tagged`
    - `RuizVickiSanche-LatinasInTheUnitedSta-2006-LatinasInTheSouthwest 1.pdf` → `page-content-tagged`
    - `Wealth_of_Selves_Multiple_Identities,_Mestiza_Cons..._----_(Chapter_Two) 1.pdf` → `doc-reading-order`
- `all failed` was initially false for local checks because of manual checks; `zero failed` except for the 3 above.
- Adobe API verification was not completed due missing credentials in environment (`ADOBE_CLIENT_ID` / `ADOBE_CLIENT_SECRET`).

## Current repository state note
- User requested only targeted code changes for this push.
- A large number of unrelated files remain modified/uncommitted in the working tree beyond this commit.
