# Synthetic integration contracts, v1 baseline

This directory documents the agreed LT-120/LT-112/LT-111 test contracts. The
version identifies fixture data. It adds no `schema_version`, `contract_id` or
completeness field to an HTTP payload. Production topology and Atlas tier are
unknown; these files are not a verified deployment bundle.

## HTML validation

The byte-for-byte canonical manifest is
[`tests/unit/contracts_v1/remedy-html-validation.json`](../../../tests/unit/contracts_v1/remedy-html-validation.json).
Its source is `/Users/libretexts/code/remedy-html-validation-v1-fixtures.json`,
SHA-256 `df8dfe2ca12b95e846c3e405464f16d72a03114608b21ee160e528efa20e1aaa`.
The four source hashes in it independently match immutable Server
`78710dc0af53d3e63a662fb392b5190f2e2d0dab` and the files at current main
`173a419f2ea458ed6b93589c674cc27cda95ecc0`. That is a verification at these
snapshots, not a requirement that future comments or unrelated source bytes
never change. The behavioral tests run current orchestration and serialization.

The producer seam is `AccessibilityValidator.validate` followed by
`serialize_validation_report`. Synthetic external checker adapters produce
pass, warning, accessibility-failure, partial-checker-failure and nullable axe
impact observations. Neither the supplied manifest nor these core contract
tests execute HTTP, Chromium, CLI tools or a live service. PR #8's separate
HTTP/worker/full-runtime evidence does not turn these synthetic findings into
checker-accuracy evidence.

`POST /v1/validate/html` accepts multipart `file`. Its HTTP 200 baseline is:

| Field | Allowed shape |
|---|---|
| `axe`, `pa11y`, `lighthouse`, `wave` | Object with `passed` boolean, `violations` array, `score` null or finite numeric value |
| `overall_passed` | Boolean |
| `all_violations` | Array of findings |
| `summary` | String for humans; never parse its wording for control flow |

Findings have string `tool`, `id` and `description` fields, including empty
strings where the tool emits them. `impact` is `critical`, `serious`,
`moderate`, `minor` or null. Optional fields retain tool-specific types:
Lighthouse findings may include numeric `score` and need not include `wcag` or
`selector`; axe can carry nullable impact, `nodes_count` and `html_snippets`.
Critical/serious findings map to errors; moderate/minor/null map to warnings
for this HTTP consumer contract. Direct-core canonical severity mapping is a
separate Scanner behavior and must remain intact.

Consumers allow additive unknown keys but reject malformed known fields,
missing arrays, nonboolean verdicts, nonfinite scores, malformed findings and
inconsistent would-be clean passes. No alternate `findings`, `results` or
`issues` success envelope is supported. Non-2xx or non-JSON is an operational
failure independent of the error-body wording; illustrative 401/503 bodies in
the manifest are not an exact universal error-text contract.

Warnings can coexist with `overall_passed: true`. A partial checker failure
can be HTTP 200 with `overall_passed: false`, a failed tool's `passed: false`
and empty `violations`, and empty `all_violations`. That remains unsuccessful
evidence. There is no typed completeness/error indicator in this baseline, so
clients cannot infer a successful run from empty findings or machine-parse
the summary to distinguish failure causes. WAVE's empty `passed: true` result
is a placeholder for uploaded-file validation; it does not prove WAVE ran.
A typed completeness extension requires a separate reviewed release slice.

## ADAPT assignment enumeration

[`adapt-assignment-enumeration.json`](../../../tests/unit/contracts_v1/adapt-assignment-enumeration.json)
contains source-derived synthetic external-service examples pinned to
`ee9478b0b418d222c17a15a004a36cec43858dfd`, with route/provider/controller
SHA-256 provenance. It is not a Laravel, live ADAPT or Scanner execution.

The actual request is `GET /api/assignments/{assignment}/questions/ids`.
`routes/api.php:511` selects
`AssignmentSyncQuestionController::getQuestionIdsByAssignment`; the provider
adds the `/api` prefix. A supported response is:

```json
{"type":"success","question_ids":"[101,202]","question_ids_array":[101,202]}
```

IDs 101/202 are invented synthetic values. `question_ids_array` is authoritative;
the JSON-encoded `question_ids` duplicate is not a fallback. The endpoint
`/api/assignments/{assignment}/get-questions-info` returns assignment metadata
through `AssignmentController::getQuestionsInfo`, not question enumeration.
Use neither guessed array envelopes nor a missing array as an empty result.

The pinned enumeration controller sets `type: success` before its queries.
Its catch can therefore retain success while omitting the array. Reject this
shape as contract failure; no ADAPT edit is required or made. `type: error`
is an application failure even at HTTP 200. LT-120 rejects malformed,
nonpositive or unknown IDs without coercing or silently filtering them and
preserves supported safe numeric-string IDs exactly.

Only a recognized success containing an actual empty `question_ids_array`
means no work. Scanner reports zero totals/results, `exitCode: 1`, additive
`outcome: no_work`, a clear message and HTTP `ok: false`. It must not fabricate
a failed question. Unknown or malformed envelopes are contract failures,
not no-work. The fixture's `consumer_policy` describes assertions; it is not
an ADAPT or Scanner payload field. Scanner owns the executable client/parser
checks under LT-120; this repo provides shared external-service test data.

## Conductor pins and execution limits

[`integration-targets.json`](../../../tests/unit/contracts_v1/integration-targets.json)
records exact agreed sources:

| Target | Pin |
|---|---|
| Server fixture-compatible main | `173a419f2ea458ed6b93589c674cc27cda95ecc0` |
| HTML fixture provenance | `78710dc0af53d3e63a662fb392b5190f2e2d0dab` |
| ADAPT source snapshot | `ee9478b0b418d222c17a15a004a36cec43858dfd` |
| Conductor staging | `67301b35c3784ed73ba1a65011ef5a1d689abca1` |
| Conductor released floor `v2.156.2` | `352a657ec6de7b317a70ad3f8f744bc6d5054d9d` |

Both Conductor commits and the lightweight release tag were independently
resolved through read-only GitHub metadata. The local Conductor checkout lacks
those objects; it was not fetched into, checked out or changed. No patch
application/build on these targets or live release compatibility is claimed.
Conductor patch validation belongs in fresh scratch clones to its owner.

The fixture manifests are source pins for synthetic integration, not a claim
that components have been assembled or production deployed. Real cross-stack
auth, scan, preview, write, invalidation, restore, resource policy, compatible
images, storage, upgrade and rollback proof remain release gates. Do not use
floating references in the assembled test or release bundle.

Run the producer contract guards with the project Python:

```sh
.venv/bin/python -m pytest tests/unit/test_html_validation_contract.py -q
```

The tests deliberately check summary type without freezing English text and
allow additive fields. JSON fixture provenance is retained unchanged; runtime
schema negotiation or a new generic validation framework is not introduced.

The approved signed-reviewer transport and its remaining integration gates are
specified in [reviewer-forwarding.md](reviewer-forwarding.md).
