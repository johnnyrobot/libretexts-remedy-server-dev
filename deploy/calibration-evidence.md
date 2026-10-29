# Calibration capability and evidence

The committed v1 corpus is historical bootstrap data. All 50 source artifacts
are invalid placeholders, and the records identify `automated_bootstrap` as
their annotator. Existing `human_verified` / `human_specialist` labels and
matching hashes do **not** establish specialist review or parser readability.
These files and their historical score/snapshot records remain unchanged.
Calibration-dependent quality execution is unavailable on this evidence.

Readiness now parses source, gold and known-bad PDF/OOXML artifacts using the
real format parsers, verifies their bytes against recorded hashes, classifies
synthetic/bootstrap/unreviewed attribution, and requires a separate
operator-controlled approval bound to the exact annotations, artifact hashes
and persisted judge-result bytes. Stored perfect scores cannot bypass this.
The runtime also recomputes agreement from that approved dataset and requires
the current stored judge/version/format/dimension values to match it before
applying configured agreement, sample-size and freshness thresholds.

`GET /v1/quality/calibration?format=pdf` (or an Office format) returns historical
rows separately from readiness. Readiness includes `capability`,
`evidence_errors` and `evidence_digest`; unavailable evidence yields
`ready:false`, `capability:"unavailable"`, and no calibrated judges/dimensions.
Direct quality audit routes retain their explicit HTTP 409 conflict refusal.
`QUALITY_REQUIRE_CALIBRATION=false` cannot bypass evidence qualification.
Base health/readiness remains separate from this optional quality capability.
Office and PDF remediation retain usable downloads when requested calibration
is unavailable, with an explicit quality advisory in job metadata. A completed
artifact never implies calibrated quality or WCAG/PDF-UA certification.

## Evidence owners must provide

Keep v1 as history. Prepare a new corpus version with parser-readable source,
specialist-reviewed gold and known-bad artifacts; accurate hashes; attributable
specialist annotations and dates; and persisted judge results bound to those
same sources and the required judge/model versions. Synthetic fixtures can
prove parser, scoring and transport mechanics only. Do not relabel bootstrap
or model-produced work as specialist review.

If pairwise comparison calibration is used, persist the bound comparisons as
`judge_comparisons.jsonl` beside `judge_results.jsonl` and include that file in
the approved digest with `--judge-comparisons`. Runtime qualification binds
and recomputes both datasets; adding or changing comparisons invalidates the
previous approval.

The production pass/fail score threshold is fixed at 0.8 and shared by the CLI
and runtime recomputation. `--score-threshold` accepts that value for command
compatibility and explicitly rejects other values; an unsupported threshold
cannot produce a successful calibration that the runtime would later reject.

The calibration command refuses unqualified evidence in both actual-audit and
stored-score modes before running a judge/provider or writing calibration
rows. Actual audit collection remains available through
`tools.calibrate_judges.run_audits_for_annotations` for parser-readable inputs;
collecting scores itself establishes no human verification. An owner must
review and persist the evidence before requesting active calibration.

An authorized evidence owner independently records an approval file with these
fields: `schema_version` (integer 1), `classification` (`human_reviewed`),
`reviewer_id` (attributable specialist/owner identity), `reviewed_at` (timezone
date, not in the future), `evidence_reference` (the retained review record),
and `corpus_digest` (the digest reported for that exact corpus and result
dataset). This task creates no such approval and makes no human assertion.

The approval file is an **operator trust input**, not a cryptographic proof
that a person reviewed a document. Mount it read-only outside HTTP-writable
corpus/review directories, writable only by the authorized evidence owner.
Do not trust an approval supplied inside an upload or a reviewer API request.
Set `QUALITY_CORPUS_ROOT_PATH` to the new corpus and
`QUALITY_EVIDENCE_APPROVAL_PATH` to that independent file. Leave the latter
empty to keep the capability unavailable. API callers cannot select it.

Use the same approval and persisted results with the CLI:

```sh
python tools/calibrate_judges.py calibrate \
  --root /path/to/reviewed-corpus \
  --judge-results /path/to/reviewed-corpus/judge_results.jsonl \
  --evidence-approval /path/to/read-only-approval.json \
  --store /path/to/quality_experiments.db --enforce-readiness --json
```

Changed artifacts, annotations or judge-result bytes invalidate the approval.
The CLI refuses invalid evidence even without `--enforce-readiness`; that flag
is retained for command compatibility. Failed qualification writes no new
calibration metrics and does not rewrite historical rows. Synthetic positive
parser tests and negative capability tests make CI green by proving refusal,
not by manufacturing a calibrated corpus. Production evidence, resource
envelopes, stack integration and owner approval remain release gates.
