# LT220 PDF dependency security repair

The supported dependency floor and frozen lock move from pypdf 6.21.2 to
6.21.4. No other locked package is upgraded. This is a source/runtime security
repair, not a replacement of the retained original LT197 delivery.

## Upstream basis

The maintainer's [6.21.3 release](https://github.com/py-pdf/pypdf/releases/tag/6.21.3)
and [6.21.4 release](https://github.com/py-pdf/pypdf/releases/tag/6.21.4)
cover the following audit findings:

| CVE | Upstream advisory | First fixed release |
|---|---|---|
| CVE-2026-119203 | [Missing xref trailer loop](https://github.com/py-pdf/pypdf/security/advisories/GHSA-5849-834g-hvw5) | 6.21.4 |
| CVE-2026-119204 | [Shared page-tree resource growth](https://github.com/py-pdf/pypdf/security/advisories/GHSA-cggf-277g-3q54) | 6.21.4 |
| CVE-2026-119205 | [Dictionary cloning loop](https://github.com/py-pdf/pypdf/security/advisories/GHSA-mfr5-77xh-9j7h) | 6.21.4 |
| CVE-2026-119206 | [Page label runtime](https://github.com/py-pdf/pypdf/security/advisories/GHSA-42gh-23hr-vphw) | 6.21.3 |
| CVE-2026-119207 | [Strict-mode exception memory](https://github.com/py-pdf/pypdf/security/advisories/GHSA-4vqv-7265-gm2w) | 6.21.3 |
| CVE-2026-119208 | [Encrypted page-count resource use](https://github.com/py-pdf/pypdf/security/advisories/GHSA-62m5-6wh8-28x7) | 6.21.3 |
| CVE-2026-119209 | [Cross-reference stream memory](https://github.com/py-pdf/pypdf/security/advisories/GHSA-x3rh-gjgm-fmqc) | 6.21.3 |

6.21.4 is the smallest published patch covering all seven. The deployed-lock
audit remains mandatory and unsuppressed. The lock's wheel SHA256 is
`33e4fb41ca352810eb4e9838aa0d82d6888a5f8bf682f43e99cce5faa666255c`.

## Verification and limits

`tests/unit/test_pdf_dependency_security.py` uses real pypdf append/write/read,
encrypted reopening, metadata and ordered text extraction. Its tiny synthetic
missing-trailer case is derived from upstream PR4289: a child process has a
two-second CPU limit and a five-second parent timeout, with discarded diagnostic
output. On 6.21.2 the CPU limit terminates the loop; on 6.21.4 it raises a PDF
read error normally. This regression does not claim exploit coverage for every
advisory or arbitrary-input resource safety.

The shipping runtime also runs a real two-page image-only PDF through
`pdf_fixer.fix_all` and Tesseract, exercising pypdf's actual OCR append/write
call site and verifying both searchable pages. It requires the full runtime;
the normal development suite explicitly skips that case. Existing authenticated
HTTP artifact/outcome and bounded execution tests remain in the full Linux
runtime gate, including all required real browser sandbox checks. No timeout,
admission, seccomp, authentication or download policy is relaxed by this repair.

## Retention versus deployment

The original LT197 archive, its source and historical receipts remain unchanged.
They contain the older dependency and are historical provenance, not advice to
deploy that runtime after these findings. A refreshed package must incorporate
this repair and exact reviewed compatible producer records, then pass fresh
matching Linux assembled-service and operational acceptance. Old receipts do
not transfer to a patched image. All global deployment/write flags and the
LibreTexts-owned vendor validation, rollout and production acceptance gates
remain unchanged.
