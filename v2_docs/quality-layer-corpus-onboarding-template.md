# Quality Layer Corpus Onboarding Template (PRD v2 Docs)

Use this when preparing specialist annotations and supporting artifacts for
`tools/corpus_annotations/v1`.

## 1) Directory map

- Place source artifacts under your internal doc store and reference by relative path in each annotation.
- Keep annotation JSON under `tools/corpus_annotations/v1/annotations/<format>/<doc_id>.json`.
- Keep known-bad artifacts and source artifacts where your team stores them; reference exact paths and SHA-256 in `known_bad_artifact_paths` and `artifact_hashes`.
- Keep behavioral result rows in `tools/corpus_annotations/v1/behavioral_results.jsonl` (one JSON object per line).

## 2) Minimum required artifacts

- 50–80 total annotations.
- At least 30 PDF annotations and 20 Office annotations.
- Office mix should cover `docx`, `pptx`, and `xlsx` across the 20 Office minimum.
- Each annotated row must include:
  - `doc_id`
  - `format` (`pdf|docx|pptx|xlsx`)
  - `source_path`
  - `document_class`
  - `edge_case_flags`
  - `gold_remediation_path`
  - `known_bad_artifact_paths` (array)
  - `artifact_hashes`
  - `annotator`
  - `annotated_at` (ISO-8601)
  - `annotation_version`
  - `provenance` (must show human provenance)
  - `applicable_dimensions`
  - `dimensions`
  - `pairwise_comparisons`
  - `format_specific`

## 3) Shared example shell template

```bash
python - <<'PY'
import hashlib, pathlib
def sha(path):
  b = pathlib.Path(path).read_bytes()
  return hashlib.sha256(b).hexdigest()
print(sha("SOURCE_PATH"))
PY
```

## 4) Minimal PDF annotation example

```json
{
  "doc_id": "pdf_001",
  "format": "pdf",
  "source_path": "corpus-source/pdf/pdf_001_source.pdf",
  "document_class": "form",
  "edge_case_flags": ["complex_tables"],
  "gold_remediation_path": "corpus-gold/pdf/pdf_001_gold.pdf",
  "known_bad_artifact_paths": [
    "corpus-known-bad/pdf/pdf_001_bad.pdf"
  ],
  "artifact_hashes": {
    "source_sha256": "",
    "gold_remediation_sha256": "",
    "known_bad_sha256": {
      "corpus-known-bad/pdf/pdf_001_bad.pdf": ""
    }
  },
  "annotator": "specialist_name",
  "annotated_at": "2026-05-09T10:00:00-07:00",
  "annotation_version": "1.0",
  "provenance": {
    "gold_standard_source": "human_specialist",
    "human_verified": true,
    "candidate_seed_model": null,
    "notes": "initial seed pass"
  },
  "applicable_dimensions": [
    "alt_text",
    "reading_order",
    "heading_semantics",
    "table_structure",
    "link_text",
    "decorative",
    "complex_content"
  ],
  "dimensions": {
    "alt_text": {
      "score": 0.62,
      "notes": "3 images with weak alternatives",
      "per_image": [
        {
          "artifact_id": "image_1",
          "score": 0.33,
          "notes": "needs meaningful alt"
        }
      ]
    },
    "reading_order": {
      "score": 0.9,
      "notes": "mostly coherent",
      "per_paragraph": []
    }
  },
  "pairwise_comparisons": [
    {
      "dimension": "alt_text",
      "a_path": "artifacts/pdf_001_A.pdf",
      "b_path": "artifacts/pdf_001_B.pdf",
      "winner": "a",
      "rationale": "A preserves chart meaning better",
      "a_sha256": "",
      "b_sha256": ""
    }
  ],
  "format_specific": {
    "pdf": {
      "layout": "single_column",
      "language": "en"
    }
  }
}
```

## 5) DOCX/PPTX/XLSX specifics

- Include exactly one of these format-specific blocks:
  - `docx`
  - `pptx`
  - `xlsx`
- PPTX and XLSX can include nested per-slide/per-sheet quality structures where relevant.
- Keep `applicable_dimensions` aligned to the matrix:
  - XLSX: no `reading_order`, no `heading_semantics`, no `slide_title`
  - PPTX: no `sheet_organization`

## 6) Behavioral results row example

Each line in `behavioral_results.jsonl` should include:

- `doc_id`
- `format`
- `source_path`
- `source_sha256`
- `artifact_path` (or `artifact_path_gold` / `artifact_path_known_bad`)
- `behavioral_test`
- `artifact_role` (`gold` | `known_bad` | `candidate`)
- `artifact_hash`
- `passed`
- `score`
- `threshold`
- `confidence`
- `metadata`

Example line:

```json
{"doc_id":"pdf_001","format":"pdf","source_path":"corpus-source/pdf/pdf_001_source.pdf","source_sha256":"","artifact_path":"corpus-source/pdf/pdf_001_source.pdf","artifact_path_gold":"corpus-gold/pdf/pdf_001_gold.pdf","artifact_path_known_bad":"corpus-known-bad/pdf/pdf_001_bad.pdf","artifact_role":"candidate","behavioral_test":"reading_order_comprehension","dimension":"reading_order","passed":true,"score":0.98,"threshold":0.9,"confidence":0.93,"artifact_hash":"", "metadata":{}}
```

## 7) Intake sequence

- Stage source/gold/known-bad files and compute hashes before writing any annotation row.
- Ensure annotation `source_sha256` / `gold_remediation_sha256` / `known_bad_sha256` match actual artifact bytes.
- Write annotation rows and then run:
  - `./.venv/bin/python tools/annotate_corpus.py validate --root tools/corpus_annotations/v1 --json`
  - `./.venv/bin/python tools/annotate_corpus.py coverage --root tools/corpus_annotations/v1 --json`
- After annotations pass, produce behavioral rows and run behavioral + snapshot + calibration checks from the finish runbook.

