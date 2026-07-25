# office-verify Phase 0 + Phase 1 (DOCX) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic OOXML accessibility rule engine for DOCX (12 rules from PRD §4.1), the Office L0–L4 level classifier, the post-remediation acceptance gate, and the `remedy-office` CLI — Phases 0 and 1 of `PRD_ooxml_a11y_validator.md`.

**Architecture:** A versioned rule registry (`office_rules.py`) declares every rule's id, checkpoint, WCAG ref, and exact XML refs. Pure rule functions in `office_checker.py` read a shared `DocxContext` (one python-docx `Document` + one parsed `word/document.xml` ElementTree) and return the existing `OfficeCheckResult` dataclass. `office_acceptance.run_office_checker()` swaps its hand-rolled `_check_docx` for the new engine; `office_levels.py` classifies `OfficeAcceptanceResult` + a structure probe onto the existing `LevelResult` L0–L4 ladder; `engine_service._remediate_office` gains the acceptance gate; `cli_office.py` exposes it all.

**Tech Stack:** Python 3.13, python-docx / python-pptx / openpyxl (already vendored), stdlib `zipfile` + `xml.etree.ElementTree`, click + rich (already vendored for `cli_pdf.py`), pytest. Run everything via `uv run`.

## Global Constraints

- **Spec:** `PRD_ooxml_a11y_validator.md` (committed in Task 1). Rule semantics come from its §4.1 table verbatim.
- **NFR1 determinism:** no network, no LLM, no wall-clock values in any rule function. Byte-identical report for identical input bytes.
- **NFR3/AC6 zero new runtime dependencies:** nothing added to `[project.dependencies]` in `pyproject.toml`. (`pytest-cov` as a *dev* dependency in Task 13 is permitted — AC6 gates runtime deps.)
- **NFR4 backward compatibility:** `OfficeCheckResult`/`OfficeCheckReport`/`OfficeAcceptanceResult` shapes must not break. New dataclass fields must be defaulted. The 5 pre-existing docx rule ids (`docx-title`, `docx-language`, `docx-headings`, `docx-table-headers`, `docx-alt-text`) **must keep being emitted under those exact ids** — `quality_judges/office/_heuristics.py:35` and 6 `behavioral_proxies` modules filter checker results by them. Net-new rules emit canonical `OOXML-DOCX-<checkpoint>.<condition>` ids.
- **FR3/AC3 invariant:** `office_levels.classify_level()` must never return `"L5"` — enforced by an `assert` identical to `levels.py:159`.
- **Status vocabulary:** exactly `"Passed"` / `"Failed"` / `"Manual Check Needed"`. Pattern-based rules (`OOXML-DOCX-5.1`, `OOXML-DOCX-7.1`) flag as `"Manual Check Needed"`, never `"Failed"` (PRD §5, §10). `Manual Check Needed` does not block `OfficeAcceptanceResult.passed`.
- **FR6:** rules with no remediator code path ship `fixable=False` (`OOXML-DOCX-4.2`, `5.1`, `6.1`, `7.1`, and `2.2`/`2.3`/`3.2`).
- **NFR5:** test fixtures are built in-memory by `python-docx`/`python-pptx`/`openpyxl` inside the test run — no checked-in binary blobs.
- **NFR6:** every Fail cites location (paragraph index, table index, image ordinal) in `details`, not just a count.
- **XML parsing:** stdlib `xml.etree.ElementTree`, matching the repo's existing OOXML pattern (`behavioral_proxies/office/_ooxml.py`). `defusedxml` would be a new runtime dependency (forbidden by NFR3/AC6). Residual XXE/billion-laughs exposure is bounded: modern CPython's bundled expat (≥2.4) enforces entity-amplification limits, ElementTree does not fetch external entities, and the FR8 guard rejects non-ZIP input before parsing. Hardening for arbitrary *untrusted* OOXML (zip bombs etc.) is PRD open question §11.3 — a human scope decision, deliberately not resolved here.
- Tests live in `tests/unit/`, run with `uv run pytest tests/unit -q`. Commit after every task with a conventional message.
- All commits end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

## Deferred to later plans (explicitly NOT in this plan)

- PPTX rules (§4.2, Phase 2 plan) and XLSX rules (§4.3, Phase 3 plan). `run_office_checker` keeps the legacy `_check_pptx`/`_check_xlsx` for those formats.
- `office_compliance_report.py` / VPAT ACR (FR4, AC5) and the CLI `report` subcommand (Phase 4 plan).
- FR6 remediator gaps (merged-cell splitting etc.) — follow-on tickets per PRD Non-Goals.
- AC4 (≥20-real-file corpus round-trip) — needs corpus access; belongs to the Phase 4 corpus-integration plan.
- PRD §11 open questions — human decisions; do not resolve unilaterally. §11.1's naming default (`OOXML-DOCX-x.y`) is used as proposed.

## File Structure

| File | Responsibility |
|---|---|
| Create `src/project_remedy/office_rules.py` | `RuleSpec` dataclass, `RULE_CATALOG` (12 docx entries), OOXML namespace map `NS`, `qn_w()` helper |
| Create `src/project_remedy/office_checker.py` | `DocxContext`, 12 rule functions in `DOCX_RULES` registry, `OfficeAccessibilityChecker.run_all()` |
| Create `src/project_remedy/office_levels.py` | `OfficeStructureProbe`, `probe_office_structure()`, `classify_level()` (reuses `levels.LevelResult`) |
| Create `src/project_remedy/cli_office.py` | click group `office_group`: `check`, `classify-level`; OLE2/legacy guard |
| Modify `src/project_remedy/office_acceptance.py` | `OfficeCheckResult` gains defaulted `checkpoint`/`wcag_ref`; docx branch of `run_office_checker` delegates to new engine; delete `_check_docx`; add `summarize_office_acceptance()` |
| Modify `backend/app/engine_service.py:277` | `_remediate_office` gains post-remediation acceptance gate (FR5) |
| Modify `pyproject.toml:62` | add `remedy-office` script entry |
| Create `tests/unit/office_fixtures.py` | in-memory docx/pptx/xlsx builders |
| Create `tests/unit/test_office_fixtures.py` | builder smoke tests |
| Create `tests/unit/test_office_acceptance_baseline.py` | regression tests for the existing 12 legacy checks |
| Create `tests/unit/test_office_rules_docx.py` | Pass+Fail test per docx rule (AC1) |
| Create `tests/unit/test_office_checker_golden.py` | known-bad docx golden test (AC2) + catalog parity |
| Create `tests/unit/test_office_levels.py` | gate tests + seeded never-L5 fuzz (AC3) |
| Create `tests/unit/test_office_remediate_gate.py` | FR5 gate test |
| Create `tests/unit/test_cli_office.py` | CLI tests incl. FR8 guard |

---

### Task 1: Commit the spec + in-memory OOXML fixture builders

**Files:**
- Create: `PRD_ooxml_a11y_validator.md` (copy into repo — it is untracked in the main checkout)
- Create: `tests/unit/office_fixtures.py`
- Test: `tests/unit/test_office_fixtures.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `make_docx(path: Path, **opts) -> Path`, `make_pptx(path: Path, **opts) -> Path`, `make_xlsx(path: Path, **opts) -> Path`, `TINY_PNG: bytes`. Every later test task builds fixtures through these.

- [ ] **Step 1: Copy the PRD into the worktree and commit it**

```bash
cp /Users/laccd/code/lamc_district_forms/remedy-server/PRD_ooxml_a11y_validator.md .
cp /Users/laccd/code/lamc_district_forms/remedy-server/docs/superpowers/plans/2026-07-01-office-verify-phase0-1-docx.md docs/superpowers/plans/ 2>/dev/null || true
git add PRD_ooxml_a11y_validator.md docs/superpowers/plans/2026-07-01-office-verify-phase0-1-docx.md
git commit -m "docs: commit office-verify PRD + Phase 0/1 implementation plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(If the plan file already exists in the worktree, the `cp` is a no-op; commit whatever is present.)

- [ ] **Step 2: Write the failing smoke test**

Create `tests/unit/test_office_fixtures.py`:

```python
"""Smoke tests for the in-memory OOXML fixture builders."""

from __future__ import annotations

import zipfile

from tests.unit.office_fixtures import make_docx, make_pptx, make_xlsx


def test_make_docx_produces_openable_package(tmp_path):
    path = make_docx(
        tmp_path / "sample.docx",
        title="Sample",
        language="en-US",
        headings=[("Sample", 0), ("Section One", 1)],
        body_paragraphs=["This is a body paragraph with enough words to look like prose."],
        tables=1,
        inline_images=1,
        image_alt="A sample image",
    )
    from docx import Document

    doc = Document(str(path))
    assert doc.core_properties.title == "Sample"
    assert len(doc.tables) == 1
    assert len(doc.inline_shapes) == 1


def test_make_docx_anchored_image_is_invisible_to_inline_shapes(tmp_path):
    path = make_docx(tmp_path / "anchored.docx", inline_images=1, image_alt=None, anchored_images=True)
    from docx import Document

    doc = Document(str(path))
    # the anchored conversion hides the image from python-docx's inline API —
    # exactly the baseline gap OOXML-DOCX-3.1 must close
    assert len(doc.inline_shapes) == 0
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<wp:anchor" in xml


def test_make_pptx_and_xlsx_open(tmp_path):
    pptx_path = make_pptx(tmp_path / "deck.pptx", title="Deck", slides=2, slide_titles=True, pictures=1)
    xlsx_path = make_xlsx(tmp_path / "book.xlsx", title="Book", data_rows=3, data_cols=2)
    from openpyxl import load_workbook
    from pptx import Presentation

    prs = Presentation(str(pptx_path))
    assert len(prs.slides.__iter__().__self__._sldIdLst) == 2 or len(list(prs.slides)) == 2
    wb = load_workbook(str(xlsx_path))
    assert wb.properties.title == "Book"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_office_fixtures.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.unit.office_fixtures'` (ensure `tests/__init__.py` and `tests/unit/__init__.py` exist; create empty ones if imports fail that way instead).

- [ ] **Step 4: Write the fixture builders**

Create `tests/unit/office_fixtures.py`:

```python
"""In-memory OOXML fixture builders (NFR5: no checked-in binary blobs).

The anchored-image conversion is schema-loose (it renames ``wp:inline`` to
``wp:anchor`` without adding the positioning children Word itself would
require). That is sufficient here: these fixtures only need to be readable by
python-docx and ``xml.etree.ElementTree``, not openable in Word.
"""

from __future__ import annotations

import base64
import shutil
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Sequence

# 1x1 transparent PNG
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_LEGACY_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def make_docx(
    path: Path,
    *,
    title: str = "",
    language: str = "",
    headings: Sequence[tuple[str, int]] = (),
    body_paragraphs: Sequence[str] = (),
    body_first: bool = False,
    tables: int = 0,
    mark_table_headers: bool = True,
    merge_header_cells: bool = False,
    inline_images: int = 0,
    image_alt: str | None = "A sample image",
    anchored_images: bool = False,
    manual_bullets: Sequence[str] = (),
    real_list_items: Sequence[str] = (),
    hyperlinks: Sequence[tuple[str, str]] = (),
    color_paragraph: str = "",
) -> Path:
    """Build a .docx exercising exactly the features the caller asks for.

    ``headings`` is a list of ``(text, level)``; level 0 applies the Title
    style, level N >= 1 applies "Heading N". ``body_first`` puts one body
    paragraph before the first heading (for OOXML-DOCX-2.3 Fail fixtures).
    ``anchored_images=True`` converts every image to a floating ``wp:anchor``.
    ``image_alt=None`` leaves images with no descr/title.
    """
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import RGBColor

    doc = Document()
    props = doc.core_properties
    if title:
        props.title = title
    if language:
        props.language = language

    body_iter = list(body_paragraphs)
    if body_first and body_iter:
        doc.add_paragraph(body_iter.pop(0))

    for text, level in headings:
        style = "Title" if level == 0 else f"Heading {level}"
        doc.add_paragraph(text, style=style)

    for text in body_iter:
        doc.add_paragraph(text)

    for text in manual_bullets:
        doc.add_paragraph(text)  # visual bullet chars, deliberately no numPr

    for text in real_list_items:
        para = doc.add_paragraph(text, style="List Bullet")
        p_pr = para._p.get_or_add_pPr()
        num_pr = OxmlElement("w:numPr")
        ilvl = OxmlElement("w:ilvl")
        ilvl.set(qn("w:val"), "0")
        num_id = OxmlElement("w:numId")
        num_id.set(qn("w:val"), "1")
        num_pr.append(ilvl)
        num_pr.append(num_id)
        p_pr.append(num_pr)

    for display_text, url in hyperlinks:
        para = doc.add_paragraph()
        r_id = para.part.relate_to(url, RT.HYPERLINK, is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)
        run = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = display_text
        run.append(t)
        hyperlink.append(run)
        para._p.append(hyperlink)

    if color_paragraph:
        para = doc.add_paragraph()
        run = para.add_run(color_paragraph)
        run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)

    for _ in range(tables):
        table = doc.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = "Header A"
        table.rows[0].cells[1].text = "Header B"
        table.rows[1].cells[0].text = "data 1"
        table.rows[1].cells[1].text = "data 2"
        if merge_header_cells:
            table.rows[0].cells[0].merge(table.rows[0].cells[1])
        if mark_table_headers:
            tr_pr = table.rows[0]._tr.get_or_add_trPr()
            if tr_pr.find(qn("w:tblHeader")) is None:
                tr_pr.append(OxmlElement("w:tblHeader"))

    for _ in range(inline_images):
        doc.add_picture(BytesIO(TINY_PNG))
        if image_alt is not None:
            doc_pr = doc.inline_shapes[-1]._inline.docPr
            doc_pr.set("descr", image_alt)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))

    if anchored_images:
        _convert_inline_images_to_anchored(path)
    return path


def _convert_inline_images_to_anchored(path: Path) -> None:
    """Rewrite word/document.xml so every wp:inline becomes wp:anchor."""
    tmp = path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "word/document.xml":
                text = data.decode("utf-8")
                text = text.replace("<wp:inline", "<wp:anchor")
                text = text.replace("</wp:inline>", "</wp:anchor>")
                data = text.encode("utf-8")
            dst.writestr(item, data)
    shutil.move(str(tmp), str(path))


def make_pptx(
    path: Path,
    *,
    title: str = "",
    language: str = "",
    slides: int = 1,
    slide_titles: bool = True,
    pictures: int = 0,
    picture_alt: str | None = None,
) -> Path:
    from pptx import Presentation
    from pptx.util import Emu

    prs = Presentation()
    if title:
        prs.core_properties.title = title
    if language:
        prs.core_properties.language = language
    layout = prs.slide_layouts[5]  # "Title Only"
    for index in range(slides):
        slide = prs.slides.add_slide(layout)
        if slide_titles and slide.shapes.title is not None:
            slide.shapes.title.text = f"Slide {index + 1} Title"
        for _ in range(pictures):
            pic = slide.shapes.add_picture(BytesIO(TINY_PNG), Emu(0), Emu(0))
            if picture_alt is not None:
                pic._element.nvPicPr.cNvPr.set("descr", picture_alt)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return path


def make_xlsx(
    path: Path,
    *,
    title: str = "",
    language: str = "",
    data_rows: int = 3,
    data_cols: int = 2,
    header_behaviors: bool = True,
) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    if title:
        wb.properties.title = title
    if language:
        wb.properties.language = language
    ws = wb.active
    for row in range(1, data_rows + 1):
        for col in range(1, data_cols + 1):
            ws.cell(row=row, column=col, value=f"h{col}" if row == 1 else f"v{row}.{col}")
    if header_behaviors and data_rows > 1:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.print_title_rows = "1:1"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
    return path


def make_fake_ole2(path: Path) -> Path:
    """A legacy .doc-shaped byte blob for FR8 guard tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_LEGACY_OLE2_MAGIC + b"\x00" * 64)
    return path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_fixtures.py -q`
Expected: PASS (3 tests). If `tests/unit/__init__.py` is missing and imports fail, create empty `tests/__init__.py` and `tests/unit/__init__.py` and re-run. If the pptx slide-count assertion is awkward, simplify it to `assert len(list(Presentation(str(pptx_path)).slides)) == 2`.

- [ ] **Step 6: Commit**

```bash
git add tests/
git commit -m "test: add in-memory OOXML fixture builders for office-verify

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Baseline regression tests for the existing 12 legacy checks

PRD §10 risk table: "the *first* deliverable in Phase 0 to include tests for the *existing* `office_acceptance.py` checks before any new rule is added." No production code changes in this task.

**Files:**
- Test: `tests/unit/test_office_acceptance_baseline.py`

**Interfaces:**
- Consumes: `make_docx`/`make_pptx`/`make_xlsx` from Task 1; `run_office_checker(file_path: Path, file_type: FileType) -> OfficeCheckReport` and `evaluate_office_acceptance(file_path, *, file_type=None) -> OfficeAcceptanceResult` from `office_acceptance.py` (unchanged).
- Produces: the AC7 regression baseline — these tests must still pass unmodified after Task 9 swaps in the new engine.

- [ ] **Step 1: Write the baseline tests**

Create `tests/unit/test_office_acceptance_baseline.py`:

```python
"""Regression baseline for the pre-office-verify legacy checks (PRD §10, NFR5).

These tests pin the observable behavior of the 12 legacy rule ids so that the
Task-9 engine swap is provably non-regressive (AC7). Do not modify them when
swapping the docx engine — they must pass before AND after.
"""

from __future__ import annotations

import pytest

from project_remedy.models import FileType
from project_remedy.office_acceptance import evaluate_office_acceptance, run_office_checker
from tests.unit.office_fixtures import make_docx, make_pptx, make_xlsx


def _status(report, rule_id: str) -> str:
    matches = [r.status for r in report.results if r.rule_id == rule_id]
    assert matches, f"rule {rule_id!r} missing from report: {[r.rule_id for r in report.results]}"
    return matches[0]


GOOD_DOCX_KWARGS = dict(
    title="Good Doc",
    language="en-US",
    headings=[("Good Doc", 0), ("Section", 1)],
    body_paragraphs=["Body text long enough to be clearly a body paragraph of prose."],
    tables=1,
    mark_table_headers=True,
    inline_images=1,
    image_alt="A sample image",
)


@pytest.mark.parametrize(
    ("rule_id", "bad_kwargs"),
    [
        ("docx-title", {**GOOD_DOCX_KWARGS, "title": ""}),
        ("docx-language", {**GOOD_DOCX_KWARGS, "language": ""}),
        ("docx-headings", {**GOOD_DOCX_KWARGS, "headings": []}),
        ("docx-table-headers", {**GOOD_DOCX_KWARGS, "mark_table_headers": False}),
        ("docx-alt-text", {**GOOD_DOCX_KWARGS, "image_alt": None}),
    ],
)
def test_docx_legacy_rule_fails_on_bad_input(tmp_path, rule_id, bad_kwargs):
    path = make_docx(tmp_path / "bad.docx", **bad_kwargs)
    report = run_office_checker(path, FileType.DOCX)
    assert _status(report, rule_id) == "Failed"


def test_docx_legacy_rules_all_pass_on_good_input(tmp_path):
    path = make_docx(tmp_path / "good.docx", **GOOD_DOCX_KWARGS)
    report = run_office_checker(path, FileType.DOCX)
    for rule_id in ("docx-title", "docx-language", "docx-headings", "docx-table-headers", "docx-alt-text"):
        assert _status(report, rule_id) == "Passed"


def test_pptx_legacy_rules(tmp_path):
    good = make_pptx(tmp_path / "good.pptx", title="Deck", language="en-US",
                     slides=1, slide_titles=True, pictures=1, picture_alt="chart")
    report = run_office_checker(good, FileType.PPTX)
    for rule_id in ("pptx-title", "pptx-language", "pptx-slide-titles", "pptx-alt-text"):
        assert _status(report, rule_id) == "Passed"

    bad = make_pptx(tmp_path / "bad.pptx", slides=1, slide_titles=False, pictures=1, picture_alt=None)
    report = run_office_checker(bad, FileType.PPTX)
    assert _status(report, "pptx-title") == "Failed"
    assert _status(report, "pptx-language") == "Failed"
    assert _status(report, "pptx-alt-text") == "Failed"


def test_xlsx_legacy_rules(tmp_path):
    good = make_xlsx(tmp_path / "good.xlsx", title="Book", language="en-US", header_behaviors=True)
    report = run_office_checker(good, FileType.XLSX)
    for rule_id in ("xlsx-title", "xlsx-language", "xlsx-header-behaviors"):
        assert _status(report, rule_id) == "Passed"

    bad = make_xlsx(tmp_path / "bad.xlsx", header_behaviors=False)
    report = run_office_checker(bad, FileType.XLSX)
    assert _status(report, "xlsx-title") == "Failed"
    assert _status(report, "xlsx-header-behaviors") == "Failed"


def test_acceptance_passed_reflects_failures(tmp_path):
    bad = make_docx(tmp_path / "bad.docx")  # no title/language/headings
    result = evaluate_office_acceptance(bad)
    assert result.openable
    assert not result.passed
    assert result.checker_failures

    good = make_docx(tmp_path / "good.docx", **GOOD_DOCX_KWARGS)
    result = evaluate_office_acceptance(good)
    assert result.openable
    assert result.passed
```

- [ ] **Step 2: Run and fix expectations against actual behavior**

Run: `uv run pytest tests/unit/test_office_acceptance_baseline.py -q`
Expected: PASS. If any assertion fails, the test's expectation is wrong about current behavior — adjust the *test* to match the code exactly (this task documents current behavior; it must not change production code). One known subtlety: `pptx-slide-titles` falls back to "first non-empty text frame", so a title-less slide *with other text* still passes today — the bad-pptx fixture uses `slide_titles=False` with no other text so it fails cleanly; if layout placeholders add stray text, assert `pptx-slide-titles` on the good deck only and drop it from the bad-deck assertions.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_office_acceptance_baseline.py
git commit -m "test: pin regression baseline for legacy office_acceptance checks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Rule registry (`office_rules.py`) + `OfficeCheckResult` metadata fields

**Files:**
- Create: `src/project_remedy/office_rules.py`
- Modify: `src/project_remedy/office_acceptance.py:13-19` (`OfficeCheckResult`)
- Test: `tests/unit/test_office_rules_docx.py` (registry-invariant tests only, in this task)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `RuleSpec` frozen dataclass: `rule_id: str`, `emitted_id: str`, `format: str`, `checkpoint: str`, `description: str`, `wcag_ref: str`, `xml_refs: tuple[str, ...]`, `fixable: bool`, `flag_status: str`.
  - `RULE_CATALOG: tuple[RuleSpec, ...]` (12 docx entries), `RULE_SPECS_BY_ID: dict[str, RuleSpec]`.
  - `NS: dict[str, str]` namespace map and `qn_w(local: str) -> str`.
  - `OfficeCheckResult` gains `checkpoint: str = ""` and `wcag_ref: str = ""` (defaulted → NFR4-safe).

- [ ] **Step 1: Write the failing registry tests**

Create `tests/unit/test_office_rules_docx.py`:

```python
"""Rule-catalog invariants + per-rule Pass/Fail tests (grows through Task 8)."""

from __future__ import annotations

from project_remedy.office_rules import NS, RULE_CATALOG, RULE_SPECS_BY_ID, RuleSpec


def test_catalog_has_twelve_docx_rules_with_unique_ids():
    docx = [s for s in RULE_CATALOG if s.format == "docx"]
    assert len(docx) == 12
    assert len({s.rule_id for s in docx}) == 12
    assert len({s.emitted_id for s in docx}) == 12


def test_every_rule_declares_xml_refs_and_wcag_ref():
    for spec in RULE_CATALOG:
        assert spec.rule_id.startswith("OOXML-DOCX-")
        assert spec.xml_refs, spec.rule_id           # FR2: self-documenting XML refs
        assert spec.wcag_ref, spec.rule_id
        assert spec.flag_status in ("Failed", "Manual Check Needed")


def test_legacy_alias_mapping_is_exact():
    aliases = {s.rule_id: s.emitted_id for s in RULE_CATALOG if s.emitted_id != s.rule_id}
    assert aliases == {
        "OOXML-DOCX-1.1": "docx-title",
        "OOXML-DOCX-1.2": "docx-language",
        "OOXML-DOCX-2.1": "docx-headings",
        "OOXML-DOCX-3.1": "docx-alt-text",
        "OOXML-DOCX-4.1": "docx-table-headers",
    }


def test_pattern_rules_route_to_manual_check_needed():
    assert RULE_SPECS_BY_ID["OOXML-DOCX-5.1"].flag_status == "Manual Check Needed"
    assert RULE_SPECS_BY_ID["OOXML-DOCX-7.1"].flag_status == "Manual Check Needed"


def test_new_rules_without_remediator_support_ship_fixable_false():
    # FR6: never fixable=True without a real office_remediator code path
    for rule_id in ("OOXML-DOCX-2.2", "OOXML-DOCX-2.3", "OOXML-DOCX-3.2",
                    "OOXML-DOCX-4.2", "OOXML-DOCX-5.1", "OOXML-DOCX-6.1", "OOXML-DOCX-7.1"):
        assert RULE_SPECS_BY_ID[rule_id].fixable is False, rule_id


def test_namespace_map_covers_wordprocessing_drawing():
    assert set(NS) >= {"w", "wp", "a", "r"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_remedy.office_rules'`

- [ ] **Step 3: Implement `office_rules.py`**

Create `src/project_remedy/office_rules.py`:

```python
"""office-verify rule registry — the machine-readable §4 catalog of the PRD.

Every rule declares the exact OOXML part/element/attribute it reads
(``xml_refs``, FR2). ``rule_id`` is the canonical, stable, diffable id (G1).
``emitted_id`` is the id written into ``OfficeCheckResult.rule_id``: for the
five rules that predate office-verify it stays the legacy id
(``docx-title`` …) because ``quality_judges/office/_heuristics.py`` and six
``behavioral_proxies`` modules filter checker results by those exact strings
(NFR4/AC7); net-new rules emit their canonical id.
"""

from __future__ import annotations

from dataclasses import dataclass

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def qn_w(local: str) -> str:
    """Clark-notation name in the main wordprocessingml namespace."""
    return f"{{{NS['w']}}}{local}"


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str          # canonical "OOXML-DOCX-<checkpoint>.<condition>"
    emitted_id: str       # id written into OfficeCheckResult.rule_id
    format: str           # "docx" | "pptx" | "xlsx"
    checkpoint: str       # checkpoint group name from PRD §4
    description: str
    wcag_ref: str         # WCAG 2.1 success criterion, e.g. "1.1.1"
    xml_refs: tuple[str, ...]  # FR2: exact parts/elements/attributes read
    fixable: bool         # FR6: True only with a real office_remediator path
    flag_status: str      # status when the condition trips: "Failed" | "Manual Check Needed"


RULE_CATALOG: tuple[RuleSpec, ...] = (
    RuleSpec(
        "OOXML-DOCX-1.1", "docx-title", "docx", "Document metadata",
        "Document title metadata is present", "2.4.2",
        ("docProps/core.xml -> dc:title",), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-1.2", "docx-language", "docx", "Document metadata",
        "Document language metadata is present", "3.1.1",
        ("docProps/core.xml -> dc:language",), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-2.1", "docx-headings", "docx", "Heading structure",
        "Document includes heading/title styles", "1.3.1",
        ("word/document.xml -> w:p/w:pPr/w:pStyle/@w:val",
         "word/document.xml -> w:p/w:pPr/w:outlineLvl/@w:val"), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-2.2", "OOXML-DOCX-2.2", "docx", "Heading structure",
        "Heading levels do not skip (e.g. H1 to H3 without H2)", "2.4.6",
        ("word/document.xml -> w:p/w:pPr/w:pStyle/@w:val",
         "word/document.xml -> w:p/w:pPr/w:outlineLvl/@w:val"), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-2.3", "OOXML-DOCX-2.3", "docx", "Heading structure",
        "Document does not open on a body paragraph before any heading/title", "2.4.6",
        ("word/document.xml -> first non-empty w:p style",), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-3.1", "docx-alt-text", "docx", "Images",
        "Every inline/anchored image exposes non-empty descr or title", "1.1.1",
        ("word/document.xml -> w:drawing//wp:inline/wp:docPr/@descr|@title",
         "word/document.xml -> w:drawing//wp:anchor/wp:docPr/@descr|@title"), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-3.2", "OOXML-DOCX-3.2", "docx", "Images",
        "Alt text is not a filename/placeholder pattern", "1.1.1",
        ("word/document.xml -> wp:docPr/@descr value pattern",), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-4.1", "docx-table-headers", "docx", "Tables",
        "First row of every table is marked as a repeating header", "1.3.1",
        ("word/document.xml -> w:tbl/w:tr[1]/w:trPr/w:tblHeader",), True, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-4.2", "OOXML-DOCX-4.2", "docx", "Tables",
        "No merged cells (gridSpan/vMerge) in the header row", "1.3.1",
        ("word/document.xml -> w:tbl/w:tr[1]//w:tcPr/w:gridSpan",
         "word/document.xml -> w:tbl/w:tr[1]//w:tcPr/w:vMerge"), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-5.1", "OOXML-DOCX-5.1", "docx", "Lists",
        "Visual bullet/number patterns are backed by real w:numPr list structure", "1.3.1",
        ("word/document.xml -> w:p text pattern vs w:p/w:pPr/w:numPr",), False, "Manual Check Needed",
    ),
    RuleSpec(
        "OOXML-DOCX-6.1", "OOXML-DOCX-6.1", "docx", "Hyperlinks",
        "Hyperlink display text is not a bare URL or generic phrase", "2.4.4",
        ("word/document.xml -> w:hyperlink//w:t vs @r:id target",), False, "Failed",
    ),
    RuleSpec(
        "OOXML-DOCX-7.1", "OOXML-DOCX-7.1", "docx", "Color-only meaning",
        "No paragraph relies solely on run color adjacent to color-reference text", "1.4.1",
        ("word/document.xml -> w:r/w:rPr/w:color/@w:val co-occurring with color phrases",),
        False, "Manual Check Needed",
    ),
)

RULE_SPECS_BY_ID: dict[str, RuleSpec] = {spec.rule_id: spec for spec in RULE_CATALOG}
```

- [ ] **Step 4: Extend `OfficeCheckResult` with defaulted metadata fields**

In `src/project_remedy/office_acceptance.py`, change the dataclass (lines 13-19) to:

```python
@dataclass
class OfficeCheckResult:
    rule_id: str
    description: str
    status: str  # Passed / Failed / Manual Check Needed
    details: list[str] = field(default_factory=list)
    fixable: bool = False
    checkpoint: str = ""   # office-verify catalog group (empty for legacy checks)
    wcag_ref: str = ""     # WCAG 2.1 SC, e.g. "1.1.1" (empty for legacy checks)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_rules_docx.py tests/unit/test_office_acceptance_baseline.py -q`
Expected: PASS (registry tests green; baseline untouched — new fields are defaulted).

- [ ] **Step 6: Commit**

```bash
git add src/project_remedy/office_rules.py src/project_remedy/office_acceptance.py tests/unit/test_office_rules_docx.py
git commit -m "feat: add office-verify rule registry (12 docx RuleSpecs) + result metadata fields

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `office_checker.py` — `DocxContext` + metadata rules 1.1 / 1.2

**Files:**
- Create: `src/project_remedy/office_checker.py`
- Test: `tests/unit/test_office_rules_docx.py` (append)

**Interfaces:**
- Consumes: `RULE_SPECS_BY_ID`, `NS`, `qn_w` from Task 3; `OfficeCheckResult` from `office_acceptance`.
- Produces:
  - `DocxContext` dataclass with `path: Path`, `document` (python-docx Document), `body_root` (ElementTree Element of `word/document.xml`), and classmethod `DocxContext.load(path: Path) -> DocxContext`.
  - `DOCX_RULES: dict[str, Callable[[DocxContext], OfficeCheckResult]]` registry + `@docx_rule(rule_id)` decorator.
  - `_make_result(rule_id: str, *, flagged: bool, details: list[str]) -> OfficeCheckResult` helper. All later rule tasks add functions to this registry via the same decorator and helper.

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_office_rules_docx.py`:

```python
from pathlib import Path

from project_remedy.office_checker import DOCX_RULES, DocxContext
from tests.unit.office_fixtures import make_docx


def _run(rule_id: str, path: Path):
    return DOCX_RULES[rule_id](DocxContext.load(path))


def test_rule_1_1_title(tmp_path):
    good = make_docx(tmp_path / "g.docx", title="Has Title")
    bad = make_docx(tmp_path / "b.docx", title="")
    ok = _run("OOXML-DOCX-1.1", good)
    fail = _run("OOXML-DOCX-1.1", bad)
    assert ok.status == "Passed" and ok.rule_id == "docx-title"
    assert fail.status == "Failed" and fail.fixable is True
    assert fail.checkpoint == "Document metadata" and fail.wcag_ref == "2.4.2"


def test_rule_1_2_language(tmp_path):
    good = make_docx(tmp_path / "g.docx", language="en-US")
    bad = make_docx(tmp_path / "b.docx", language="")
    assert _run("OOXML-DOCX-1.2", good).status == "Passed"
    result = _run("OOXML-DOCX-1.2", bad)
    assert result.status == "Failed" and result.rule_id == "docx-language"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_remedy.office_checker'`

- [ ] **Step 3: Implement the module skeleton + rules 1.1/1.2**

Create `src/project_remedy/office_checker.py`:

```python
"""office-verify deterministic rule engine (PRD_ooxml_a11y_validator.md §4).

Each rule is a pure function ``(DocxContext) -> OfficeCheckResult`` registered
in ``DOCX_RULES`` under its canonical rule id. Determinism contract (NFR1):
no network, no LLM, no clock — same input bytes, same report.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from project_remedy.models import FileType
from project_remedy.office_acceptance import (
    OfficeCheckReport,
    OfficeCheckResult,
    _docx_outline_level,
    _docx_paragraph_has_heading_structure,
    _infer_file_type,
)
from project_remedy.office_rules import NS, RULE_CATALOG, RULE_SPECS_BY_ID, qn_w


@dataclass
class DocxContext:
    """Everything a docx rule may read, loaded exactly once per document."""

    path: Path
    document: Any                 # python-docx Document
    body_root: ET.Element         # parsed word/document.xml

    @classmethod
    def load(cls, path: Path) -> "DocxContext":
        from docx import Document

        with zipfile.ZipFile(path) as zf:
            body_root = ET.fromstring(zf.read("word/document.xml"))
        return cls(path=Path(path), document=Document(str(path)), body_root=body_root)


DOCX_RULES: dict[str, Callable[[DocxContext], OfficeCheckResult]] = {}


def docx_rule(rule_id: str):
    def wrap(fn: Callable[[DocxContext], OfficeCheckResult]):
        DOCX_RULES[rule_id] = fn
        return fn
    return wrap


def _make_result(rule_id: str, *, flagged: bool, details: list[str]) -> OfficeCheckResult:
    spec = RULE_SPECS_BY_ID[rule_id]
    return OfficeCheckResult(
        rule_id=spec.emitted_id,
        description=spec.description,
        status=spec.flag_status if flagged else "Passed",
        details=details if flagged else [],
        fixable=spec.fixable,
        checkpoint=spec.checkpoint,
        wcag_ref=spec.wcag_ref,
    )


# --- Checkpoint 1: document metadata ---------------------------------------

@docx_rule("OOXML-DOCX-1.1")
def rule_docx_title(ctx: DocxContext) -> OfficeCheckResult:
    title = (ctx.document.core_properties.title or "").strip()
    return _make_result("OOXML-DOCX-1.1", flagged=not title,
                        details=["docProps/core.xml dc:title is empty"])


@docx_rule("OOXML-DOCX-1.2")
def rule_docx_language(ctx: DocxContext) -> OfficeCheckResult:
    language = (getattr(ctx.document.core_properties, "language", "") or "").strip()
    return _make_result("OOXML-DOCX-1.2", flagged=not language,
                        details=["docProps/core.xml dc:language is empty"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/project_remedy/office_checker.py tests/unit/test_office_rules_docx.py
git commit -m "feat: office_checker DocxContext + metadata rules OOXML-DOCX-1.1/1.2

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Heading rules 2.1 / 2.2 / 2.3

**Files:**
- Modify: `src/project_remedy/office_checker.py` (append rules)
- Test: `tests/unit/test_office_rules_docx.py` (append)

**Interfaces:**
- Consumes: `DocxContext`, `docx_rule`, `_make_result` from Task 4; `_docx_paragraph_has_heading_structure`/`_docx_outline_level` imported from `office_acceptance`.
- Produces: `_heading_level(paragraph) -> int | None` helper (Title → 1, "Heading N" → N, `w:outlineLvl` v → v+1), used by rules 2.1–2.3. Level-skip semantics: the heading sequence starts from a virtual level 0, so a document whose first heading is level ≥2 is itself a skip.

- [ ] **Step 1: Append failing tests**

```python
def test_rule_2_1_headings_present(tmp_path):
    good = make_docx(tmp_path / "g.docx", headings=[("T", 0)])
    bad = make_docx(tmp_path / "b.docx", body_paragraphs=["Just plain body text here."])
    assert _run("OOXML-DOCX-2.1", good).status == "Passed"
    result = _run("OOXML-DOCX-2.1", bad)
    assert result.status == "Failed" and result.rule_id == "docx-headings"


def test_rule_2_2_no_level_skips(tmp_path):
    good = make_docx(tmp_path / "g.docx", headings=[("T", 0), ("A", 1), ("B", 2)])
    skip = make_docx(tmp_path / "s.docx", headings=[("A", 1), ("C", 3)])
    first_deep = make_docx(tmp_path / "f.docx", headings=[("Only", 2)])
    assert _run("OOXML-DOCX-2.2", good).status == "Passed"
    result = _run("OOXML-DOCX-2.2", skip)
    assert result.status == "Failed"
    assert any("1 -> 3" in d or "1 → 3" in d for d in result.details)
    assert _run("OOXML-DOCX-2.2", first_deep).status == "Failed"


def test_rule_2_2_vacuous_pass_without_headings(tmp_path):
    none = make_docx(tmp_path / "n.docx", body_paragraphs=["No headings at all in here."])
    assert _run("OOXML-DOCX-2.2", none).status == "Passed"


def test_rule_2_3_no_orphan_intro_text(tmp_path):
    good = make_docx(tmp_path / "g.docx", headings=[("T", 0)],
                     body_paragraphs=["Body paragraph following the title."])
    bad = make_docx(tmp_path / "b.docx", headings=[("T", 0)],
                    body_paragraphs=["Intro before any heading.", "More body."],
                    body_first=True)
    empty = make_docx(tmp_path / "e.docx")
    assert _run("OOXML-DOCX-2.3", good).status == "Passed"
    result = _run("OOXML-DOCX-2.3", bad)
    assert result.status == "Failed" and result.details
    assert _run("OOXML-DOCX-2.3", empty).status == "Passed"  # vacuous: nothing to mislead
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: FAIL — `KeyError: 'OOXML-DOCX-2.1'` (rule not registered).

- [ ] **Step 3: Implement**

Append to `office_checker.py`:

```python
# --- Checkpoint 2: heading structure ----------------------------------------

_HEADING_STYLE_RE = re.compile(r"^(?:accessibility )?heading\s*(\d+)?", re.IGNORECASE)


def _heading_level(paragraph: Any) -> int | None:
    """1-based heading level, or None if the paragraph is not a heading.

    Title (and Accessibility Title) count as level 1; "Heading N" is level N;
    a bare w:outlineLvl value v maps to level v+1.
    """
    style_name = (getattr(getattr(paragraph, "style", None), "name", "") or "").strip()
    lowered = style_name.lower()
    if lowered.startswith(("title", "accessibility title")):
        return 1
    match = _HEADING_STYLE_RE.match(lowered)
    if match:
        return int(match.group(1) or 1)
    outline = _docx_outline_level(paragraph)
    if outline is not None:
        return outline + 1
    return None


@docx_rule("OOXML-DOCX-2.1")
def rule_docx_headings_present(ctx: DocxContext) -> OfficeCheckResult:
    has_heading = any(_docx_paragraph_has_heading_structure(p) for p in ctx.document.paragraphs)
    return _make_result("OOXML-DOCX-2.1", flagged=not has_heading,
                        details=["no paragraph carries a Heading/Title style or w:outlineLvl"])


@docx_rule("OOXML-DOCX-2.2")
def rule_docx_heading_skips(ctx: DocxContext) -> OfficeCheckResult:
    skips: list[str] = []
    previous = 0  # virtual document root: the first heading must be level 1
    for index, paragraph in enumerate(ctx.document.paragraphs):
        level = _heading_level(paragraph)
        if level is None:
            continue
        if level > previous + 1:
            snippet = paragraph.text.strip()[:48]
            skips.append(f"paragraph {index}: heading level jumps {previous} -> {level} ('{snippet}')")
        previous = level
    return _make_result("OOXML-DOCX-2.2", flagged=bool(skips), details=skips)


@docx_rule("OOXML-DOCX-2.3")
def rule_docx_no_orphan_intro(ctx: DocxContext) -> OfficeCheckResult:
    first = next((p for p in ctx.document.paragraphs if p.text.strip()), None)
    if first is None:
        return _make_result("OOXML-DOCX-2.3", flagged=False, details=[])
    flagged = not _docx_paragraph_has_heading_structure(first)
    return _make_result(
        "OOXML-DOCX-2.3", flagged=flagged,
        details=[f"document opens on body paragraph: '{first.text.strip()[:64]}'"],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/project_remedy/office_checker.py tests/unit/test_office_rules_docx.py
git commit -m "feat: heading-structure rules OOXML-DOCX-2.1/2.2/2.3

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Image rules 3.1 / 3.2 (inline + anchored — closes the known baseline gap)

PRD §10: `_check_docx` only walked `doc.inline_shapes`, so floating (`wp:anchor`) images got a false "Passed" — a Phase 1 must-fix. These rules read the raw XML instead.

**Files:**
- Modify: `src/project_remedy/office_checker.py`
- Test: `tests/unit/test_office_rules_docx.py` (append)

**Interfaces:**
- Consumes: `ctx.body_root` (ElementTree), `NS` map.
- Produces: `_iter_image_doc_prs(body_root) -> list[tuple[str, ET.Element]]` yielding `("inline"|"anchored", wp:docPr element)` — reused by `office_levels.probe_office_structure` conceptually (probe re-implements the same two-XPath read; keep the XPaths identical).

- [ ] **Step 1: Append failing tests**

```python
def test_rule_3_1_inline_and_anchored_alt(tmp_path):
    good = make_docx(tmp_path / "g.docx", inline_images=1, image_alt="A chart")
    bad_inline = make_docx(tmp_path / "bi.docx", inline_images=1, image_alt=None)
    bad_anchored = make_docx(tmp_path / "ba.docx", inline_images=1, image_alt=None, anchored_images=True)
    assert _run("OOXML-DOCX-3.1", good).status == "Passed"
    r_inline = _run("OOXML-DOCX-3.1", bad_inline)
    assert r_inline.status == "Failed" and r_inline.rule_id == "docx-alt-text"
    # the baseline gap: anchored images must fail too (legacy check passed them)
    r_anchored = _run("OOXML-DOCX-3.1", bad_anchored)
    assert r_anchored.status == "Failed"
    assert any("anchored" in d for d in r_anchored.details)


def test_rule_3_2_placeholder_alt(tmp_path):
    good = make_docx(tmp_path / "g.docx", inline_images=1, image_alt="Campus map with entrances")
    bad = make_docx(tmp_path / "b.docx", inline_images=1, image_alt="image1.png")
    missing = make_docx(tmp_path / "m.docx", inline_images=1, image_alt=None)
    assert _run("OOXML-DOCX-3.2", good).status == "Passed"
    result = _run("OOXML-DOCX-3.2", bad)
    assert result.status == "Failed"
    assert any("image1.png" in d for d in result.details)
    # missing alt is 3.1's job; 3.2 passes vacuously
    assert _run("OOXML-DOCX-3.2", missing).status == "Passed"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: FAIL — `KeyError: 'OOXML-DOCX-3.1'`

- [ ] **Step 3: Implement**

Append to `office_checker.py`:

```python
# --- Checkpoint 3: images ----------------------------------------------------

_PLACEHOLDER_ALT_RE = re.compile(
    r"(?i)^\s*(?:image|picture|img|graphic|photo)[\s_-]*\d*\s*$"
    r"|(?i)^[\w\s_-]*\.(?:png|jpe?g|gif|bmp|tiff?|webp)\s*$"
)


def _iter_image_doc_prs(body_root: ET.Element) -> list[tuple[str, ET.Element]]:
    """(kind, wp:docPr) for every inline and anchored image in body order."""
    found: list[tuple[str, ET.Element]] = []
    for drawing in body_root.iter(qn_w("drawing")):
        for kind in ("inline", "anchor"):
            for container in drawing.iter(f"{{{NS['wp']}}}{kind}"):
                doc_pr = container.find(f"{{{NS['wp']}}}docPr")
                if doc_pr is not None:
                    found.append(("inline" if kind == "inline" else "anchored", doc_pr))
    return found


def _alt_text_of(doc_pr: ET.Element) -> str:
    return ((doc_pr.get("descr") or "").strip() or (doc_pr.get("title") or "").strip())


@docx_rule("OOXML-DOCX-3.1")
def rule_docx_image_alt_present(ctx: DocxContext) -> OfficeCheckResult:
    missing: list[str] = []
    for ordinal, (kind, doc_pr) in enumerate(_iter_image_doc_prs(ctx.body_root), start=1):
        if not _alt_text_of(doc_pr):
            missing.append(f"image {ordinal} ({kind}) has no descr/title alt text")
    return _make_result("OOXML-DOCX-3.1", flagged=bool(missing), details=missing)


@docx_rule("OOXML-DOCX-3.2")
def rule_docx_alt_not_placeholder(ctx: DocxContext) -> OfficeCheckResult:
    offenders: list[str] = []
    for ordinal, (kind, doc_pr) in enumerate(_iter_image_doc_prs(ctx.body_root), start=1):
        alt = _alt_text_of(doc_pr)
        if alt and _PLACEHOLDER_ALT_RE.match(alt):
            offenders.append(f"image {ordinal} ({kind}) alt is a placeholder: '{alt}'")
    return _make_result("OOXML-DOCX-3.2", flagged=bool(offenders), details=offenders)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: PASS. If `body_root.iter(qn_w("drawing"))` finds nothing, the fixture placed `w:drawing` under a run — `iter()` is recursive so it should match; debug by printing `{el.tag for el in ctx.body_root.iter()}`.

- [ ] **Step 5: Commit**

```bash
git add src/project_remedy/office_checker.py tests/unit/test_office_rules_docx.py
git commit -m "feat: image alt rules OOXML-DOCX-3.1/3.2 incl. anchored images (baseline gap fix)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Table rules 4.1 / 4.2

**Files:**
- Modify: `src/project_remedy/office_checker.py`
- Test: `tests/unit/test_office_rules_docx.py` (append)

**Interfaces:**
- Consumes: `ctx.body_root`, `qn_w`.
- Produces: nothing new beyond the two registered rules.

- [ ] **Step 1: Append failing tests**

```python
def test_rule_4_1_table_header_marked(tmp_path):
    good = make_docx(tmp_path / "g.docx", tables=1, mark_table_headers=True)
    bad = make_docx(tmp_path / "b.docx", tables=1, mark_table_headers=False)
    assert _run("OOXML-DOCX-4.1", good).status == "Passed"
    result = _run("OOXML-DOCX-4.1", bad)
    assert result.status == "Failed" and result.rule_id == "docx-table-headers"
    assert any("table 1" in d for d in result.details)


def test_rule_4_2_no_merged_header_cells(tmp_path):
    good = make_docx(tmp_path / "g.docx", tables=1)
    bad = make_docx(tmp_path / "b.docx", tables=1, merge_header_cells=True)
    assert _run("OOXML-DOCX-4.2", good).status == "Passed"
    result = _run("OOXML-DOCX-4.2", bad)
    assert result.status == "Failed" and result.fixable is False
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: FAIL — `KeyError: 'OOXML-DOCX-4.1'`

- [ ] **Step 3: Implement**

Append to `office_checker.py`:

```python
# --- Checkpoint 4: tables ----------------------------------------------------

@docx_rule("OOXML-DOCX-4.1")
def rule_docx_table_header_marked(ctx: DocxContext) -> OfficeCheckResult:
    unmarked: list[str] = []
    for index, tbl in enumerate(ctx.body_root.iter(qn_w("tbl")), start=1):
        first_tr = tbl.find(qn_w("tr"))
        if first_tr is None:
            continue
        tr_pr = first_tr.find(qn_w("trPr"))
        if tr_pr is None or tr_pr.find(qn_w("tblHeader")) is None:
            unmarked.append(f"table {index}: first row lacks w:tblHeader")
    return _make_result("OOXML-DOCX-4.1", flagged=bool(unmarked), details=unmarked)


@docx_rule("OOXML-DOCX-4.2")
def rule_docx_no_merged_header_cells(ctx: DocxContext) -> OfficeCheckResult:
    merged: list[str] = []
    for index, tbl in enumerate(ctx.body_root.iter(qn_w("tbl")), start=1):
        first_tr = tbl.find(qn_w("tr"))
        if first_tr is None:
            continue
        for tc_pr in first_tr.iter(qn_w("tcPr")):
            if tc_pr.find(qn_w("gridSpan")) is not None or tc_pr.find(qn_w("vMerge")) is not None:
                merged.append(f"table {index}: header row contains merged cells (gridSpan/vMerge)")
                break
    return _make_result("OOXML-DOCX-4.2", flagged=bool(merged), details=merged)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: PASS. Note: nested tables would be double-counted by `iter()`; acceptable for Phase 1 (district forms don't nest tables) — if a fixture trips it, scope with `body = ctx.body_root.find(qn_w('body'))` and iterate `body.iter(...)` identically since ElementTree lacks parent pointers; do NOT try to de-nest.

- [ ] **Step 5: Commit**

```bash
git add src/project_remedy/office_checker.py tests/unit/test_office_rules_docx.py
git commit -m "feat: table rules OOXML-DOCX-4.1/4.2

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Pattern rules 5.1 / 6.1 / 7.1 (Manual-Check routing for 5.1/7.1)

**Files:**
- Modify: `src/project_remedy/office_checker.py`
- Test: `tests/unit/test_office_rules_docx.py` (append)

**Interfaces:**
- Consumes: `ctx.body_root`, `qn_w`.
- Produces: nothing new beyond the three registered rules. `_p_text(p_element) -> str` helper (concatenated `w:t` text of a paragraph element).

- [ ] **Step 1: Append failing tests**

```python
def test_rule_5_1_manual_bullets(tmp_path):
    good = make_docx(tmp_path / "g.docx", real_list_items=["alpha", "beta"])
    bad = make_docx(tmp_path / "b.docx", manual_bullets=["• first item", "- second item"])
    assert _run("OOXML-DOCX-5.1", good).status == "Passed"
    result = _run("OOXML-DOCX-5.1", bad)
    assert result.status == "Manual Check Needed"  # never a hard Fail (PRD §5/§10)
    assert len(result.details) == 2


def test_rule_6_1_link_text(tmp_path):
    good = make_docx(tmp_path / "g.docx", hyperlinks=[("District accessibility policy", "https://example.com/policy")])
    bare = make_docx(tmp_path / "b1.docx", hyperlinks=[("https://example.com", "https://example.com")])
    generic = make_docx(tmp_path / "b2.docx", hyperlinks=[("click here", "https://example.com")])
    assert _run("OOXML-DOCX-6.1", good).status == "Passed"
    assert _run("OOXML-DOCX-6.1", bare).status == "Failed"
    result = _run("OOXML-DOCX-6.1", generic)
    assert result.status == "Failed"
    assert any("click here" in d for d in result.details)


def test_rule_7_1_color_only_meaning(tmp_path):
    good = make_docx(tmp_path / "g.docx", color_paragraph="Deadlines are firm.")
    bad = make_docx(tmp_path / "b.docx", color_paragraph="Required fields are shown in red")
    plain = make_docx(tmp_path / "p.docx", body_paragraphs=["Items shown in red are required."])
    assert _run("OOXML-DOCX-7.1", good).status == "Passed"      # color without referential phrase
    result = _run("OOXML-DOCX-7.1", bad)
    assert result.status == "Manual Check Needed"               # color + phrase → flag, not fail
    assert _run("OOXML-DOCX-7.1", plain).status == "Passed"     # phrase without colored run
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: FAIL — `KeyError: 'OOXML-DOCX-5.1'`

- [ ] **Step 3: Implement**

Append to `office_checker.py`:

```python
# --- Checkpoints 5-7: lists, hyperlinks, color-only meaning ------------------

_MANUAL_BULLET_RE = re.compile(r"^\s*(?:[•\-\*]\s+|\d+[.)]\s+)")
_BARE_URL_RE = re.compile(r"(?i)^\s*(?:https?://|www\.)\S+\s*$")
_GENERIC_LINK_TEXT = {"click here", "here", "read more", "more", "learn more", "link", "this link"}
_COLOR_PHRASE_RE = re.compile(
    r"(?i)\b(?:in|shown in|marked in|highlighted in|displayed in)\s+"
    r"(?:red|green|blue|yellow|orange|purple|pink)\b"
    r"|(?i)\b(?:red|green|blue|yellow|orange|purple|pink)\s+(?:text|items?|entries|values|fields?|cells?)\b"
)


def _p_text(p_element: ET.Element) -> str:
    return "".join(t.text or "" for t in p_element.iter(qn_w("t")))


@docx_rule("OOXML-DOCX-5.1")
def rule_docx_manual_bullets(ctx: DocxContext) -> OfficeCheckResult:
    flagged: list[str] = []
    for index, p in enumerate(ctx.body_root.iter(qn_w("p")), start=1):
        text = _p_text(p)
        if not _MANUAL_BULLET_RE.match(text):
            continue
        p_pr = p.find(qn_w("pPr"))
        has_num_pr = p_pr is not None and p_pr.find(qn_w("numPr")) is not None
        if not has_num_pr:
            flagged.append(f"paragraph {index}: manual bullet/number without w:numPr: '{text.strip()[:48]}'")
    return _make_result("OOXML-DOCX-5.1", flagged=bool(flagged), details=flagged)


@docx_rule("OOXML-DOCX-6.1")
def rule_docx_link_text(ctx: DocxContext) -> OfficeCheckResult:
    offenders: list[str] = []
    for index, link in enumerate(ctx.body_root.iter(qn_w("hyperlink")), start=1):
        display = "".join(t.text or "" for t in link.iter(qn_w("t"))).strip()
        if not display:
            continue
        if _BARE_URL_RE.match(display) or display.lower() in _GENERIC_LINK_TEXT:
            offenders.append(f"hyperlink {index}: display text is not descriptive: '{display[:64]}'")
    return _make_result("OOXML-DOCX-6.1", flagged=bool(offenders), details=offenders)


@docx_rule("OOXML-DOCX-7.1")
def rule_docx_color_only_meaning(ctx: DocxContext) -> OfficeCheckResult:
    flagged: list[str] = []
    for index, p in enumerate(ctx.body_root.iter(qn_w("p")), start=1):
        text = _p_text(p)
        if not text.strip() or not _COLOR_PHRASE_RE.search(text):
            continue
        has_colored_run = any(
            (color.get(qn_w("val")) or "").lower() not in ("", "auto", "000000")
            for color in p.iter(qn_w("color"))
        )
        if has_colored_run:
            flagged.append(
                f"paragraph {index}: color-reference phrase with colored run — verify meaning "
                f"is not conveyed by color alone: '{text.strip()[:64]}'"
            )
    return _make_result("OOXML-DOCX-7.1", flagged=bool(flagged), details=flagged)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_rules_docx.py -q`
Expected: PASS. Watch one subtlety in `test_rule_7_1`: the `good` fixture must not contain a color phrase, and the `bad` fixture's colored run and phrase are in the *same* paragraph (that's what `color_paragraph` builds).

- [ ] **Step 5: Commit**

```bash
git add src/project_remedy/office_checker.py tests/unit/test_office_rules_docx.py
git commit -m "feat: pattern rules OOXML-DOCX-5.1/6.1/7.1 with Manual-Check routing

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: `OfficeAccessibilityChecker.run_all()` + engine swap + parity + golden (AC2, AC7)

**Files:**
- Modify: `src/project_remedy/office_checker.py` (add the class)
- Modify: `src/project_remedy/office_acceptance.py:171-178` (`run_office_checker` docx branch) and delete `_check_docx` (lines 212-279)
- Test: `tests/unit/test_office_checker_golden.py`

**Interfaces:**
- Consumes: `DOCX_RULES`, `RULE_CATALOG`.
- Produces: `OfficeAccessibilityChecker(file_path: Path, file_type: FileType | None = None)` with `run_all() -> OfficeCheckReport` (FR1). `office_acceptance.run_office_checker()` keeps its exact signature; for `FileType.DOCX` it now returns the 12-rule report. Tasks 10-12 depend on this wiring.

- [ ] **Step 1: Write the failing golden + parity tests**

Create `tests/unit/test_office_checker_golden.py`:

```python
"""AC2 golden regression + AC7/§10 catalog-implementation parity."""

from __future__ import annotations

from project_remedy.models import FileType
from project_remedy.office_acceptance import run_office_checker
from project_remedy.office_checker import DOCX_RULES, OfficeAccessibilityChecker
from project_remedy.office_rules import RULE_CATALOG
from tests.unit.office_fixtures import make_docx


def test_catalog_implementation_parity():
    """§10 risk: every cataloged rule id must have a registered implementation."""
    docx_ids = {spec.rule_id for spec in RULE_CATALOG if spec.format == "docx"}
    assert docx_ids == set(DOCX_RULES)


def _known_bad_docx(tmp_path):
    return make_docx(
        tmp_path / "known_bad.docx",
        title="", language="",
        body_paragraphs=["This document opens on plain body text with no heading anywhere."],
        tables=1, mark_table_headers=False, merge_header_cells=True,
        inline_images=1, image_alt=None,
        manual_bullets=["• unstructured bullet item"],
        hyperlinks=[("https://example.com", "https://example.com")],
    )


def test_known_bad_docx_fails_exactly_the_expected_rules(tmp_path):
    report = OfficeAccessibilityChecker(_known_bad_docx(tmp_path)).run_all()
    failed = {r.rule_id for r in report.results if r.status == "Failed"}
    manual = {r.rule_id for r in report.results if r.status == "Manual Check Needed"}
    assert failed == {
        "docx-title", "docx-language", "docx-headings",
        "docx-alt-text", "docx-table-headers",
        "OOXML-DOCX-2.3", "OOXML-DOCX-4.2", "OOXML-DOCX-6.1",
    }
    assert manual == {"OOXML-DOCX-5.1"}
    assert len(report.results) == 12  # every cataloged rule evaluated (AC7)


def test_run_office_checker_docx_now_uses_the_engine(tmp_path):
    report = run_office_checker(_known_bad_docx(tmp_path), FileType.DOCX)
    assert len(report.results) == 12
    assert {r.rule_id for r in report.results} >= {"docx-title", "OOXML-DOCX-2.2"}


def test_deterministic_output(tmp_path):
    """NFR1: same bytes in, identical report out."""
    from dataclasses import asdict

    path = _known_bad_docx(tmp_path)
    first = [asdict(r) for r in OfficeAccessibilityChecker(path).run_all().results]
    second = [asdict(r) for r in OfficeAccessibilityChecker(path).run_all().results]
    assert first == second
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_checker_golden.py -q`
Expected: FAIL — `ImportError: cannot import name 'OfficeAccessibilityChecker'`

- [ ] **Step 3: Add the checker class**

Append to `office_checker.py`:

```python
# --- Engine entry point -------------------------------------------------------

class OfficeAccessibilityChecker:
    """FR1: runs the full deterministic rule catalog for one Office document.

    Phase 1 implements docx; pptx/xlsx delegate to the legacy per-format
    checks in ``office_acceptance`` until Phases 2/3 move them here.
    """

    def __init__(self, file_path: Path, file_type: FileType | None = None) -> None:
        self.file_path = Path(file_path)
        self.file_type = file_type or _infer_file_type(self.file_path)

    def run_all(self) -> OfficeCheckReport:
        if self.file_type != FileType.DOCX:
            from project_remedy.office_acceptance import _check_pptx, _check_xlsx

            if self.file_type == FileType.PPTX:
                return _check_pptx(self.file_path)
            if self.file_type == FileType.XLSX:
                return _check_xlsx(self.file_path)
            raise ValueError(f"Unsupported Office checker type: {self.file_type}")
        ctx = DocxContext.load(self.file_path)
        results = [
            DOCX_RULES[spec.rule_id](ctx)
            for spec in RULE_CATALOG
            if spec.format == "docx"
        ]
        return OfficeCheckReport(file_path=self.file_path, file_type=FileType.DOCX, results=results)
```

- [ ] **Step 4: Swap the docx branch in `office_acceptance.run_office_checker` and delete `_check_docx`**

In `office_acceptance.py`, replace the body of `run_office_checker`:

```python
def run_office_checker(file_path: Path, file_type: FileType) -> OfficeCheckReport:
    if file_type == FileType.DOCX:
        # office-verify deterministic rule engine (PRD §4.1); lazy import to
        # avoid a module-level cycle (office_checker imports our dataclasses).
        from project_remedy.office_checker import OfficeAccessibilityChecker

        return OfficeAccessibilityChecker(file_path, file_type).run_all()
    if file_type == FileType.PPTX:
        return _check_pptx(file_path)
    if file_type == FileType.XLSX:
        return _check_xlsx(file_path)
    raise ValueError(f"Unsupported Office acceptance type: {file_type}")
```

Then delete the entire `_check_docx` function (lines 212-279 pre-edit). Keep `_docx_paragraph_has_heading_structure`, `_docx_outline_level`, and `_qn` — `office_checker.py` imports the first two, and `office_remediator.py`-style callers may rely on `_qn` staying put.

- [ ] **Step 5: Run the full office test set — golden AND baseline must both pass**

Run: `uv run pytest tests/unit/test_office_checker_golden.py tests/unit/test_office_acceptance_baseline.py tests/unit/test_office_rules_docx.py -q`
Expected: PASS. The baseline file passing *unmodified* is the AC7 no-regression proof. If a baseline docx test fails, the new rule semantics diverge from legacy behavior for that rule — fix the rule function, not the baseline test.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest tests/unit -q`
Expected: PASS (87 pre-existing + all new).

- [ ] **Step 7: Commit**

```bash
git add src/project_remedy/office_checker.py src/project_remedy/office_acceptance.py tests/unit/test_office_checker_golden.py
git commit -m "feat: OfficeAccessibilityChecker.run_all + swap docx engine (AC2 golden, AC7 parity)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: `office_levels.py` — probe + L0–L4 classifier (FR3, AC3)

**Files:**
- Create: `src/project_remedy/office_levels.py`
- Test: `tests/unit/test_office_levels.py`

**Interfaces:**
- Consumes: `LevelResult` imported from `levels.py` (FR3 — do not redefine); `OfficeAcceptanceResult` and its `openable`/`checker_failures`/`quality_result` members; `NS`/`qn_w` from `office_rules`.
- Produces:
  - `OfficeStructureProbe` frozen dataclass: `has_text: bool`, `has_heading_structure: bool`, `has_table_header_marks: bool`, `has_alt_text_signal: bool`, `paragraph_count: int`, `table_count: int`, `image_count: int`.
  - `probe_office_structure(path: Path, file_type: FileType) -> OfficeStructureProbe` (never raises; docx only in Phase 1, `ValueError` for pptx/xlsx).
  - `classify_level(acceptance: OfficeAcceptanceResult | None, probe: OfficeStructureProbe, *, profile_name: str = OFFICE_PROFILE_NAME) -> LevelResult`.
  - `OFFICE_PROFILE_NAME = "LACCD-DistrictUA1-Office"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_office_levels.py`:

```python
"""Office L0-L4 gates (PRD §3.1) + the AC3 never-L5 invariant."""

from __future__ import annotations

import random
from pathlib import Path

from project_remedy.levels import LevelResult
from project_remedy.models import FileType
from project_remedy.office_acceptance import (
    OfficeAcceptanceResult,
    OfficeCheckReport,
    OfficeCheckResult,
    OfficePackageResult,
    OfficeScreenReaderResult,
    evaluate_office_acceptance,
)
from project_remedy.office_levels import (
    OFFICE_PROFILE_NAME,
    OfficeStructureProbe,
    classify_level,
    probe_office_structure,
)
from project_remedy.quality_judges.shared.base import QualityResult
from tests.unit.office_fixtures import make_docx


def _acceptance(*, openable=True, statuses=(), quality=None) -> OfficeAcceptanceResult:
    path = Path("synthetic.docx")
    results = [
        OfficeCheckResult(rule_id=f"r{i}", description="d", status=s)
        for i, s in enumerate(statuses)
    ]
    return OfficeAcceptanceResult(
        file_path=path,
        file_type=FileType.DOCX,
        checker_report=OfficeCheckReport(file_path=path, file_type=FileType.DOCX, results=results),
        screen_reader_result=OfficeScreenReaderResult(file_path=path, file_type=FileType.DOCX, issues=[]),
        package_result=OfficePackageResult(checked=True, passed=openable),
        quality_result=quality,
    )


def _probe(**overrides) -> OfficeStructureProbe:
    base = dict(has_text=True, has_heading_structure=True, has_table_header_marks=False,
                has_alt_text_signal=False, paragraph_count=3, table_count=0, image_count=0)
    base.update(overrides)
    return OfficeStructureProbe(**base)


def test_gate_ladder():
    assert classify_level(None, _probe()).level == "L0"
    assert classify_level(_acceptance(openable=False), _probe()).level == "L0"
    assert classify_level(_acceptance(), _probe(has_text=False)).level == "L0"
    r = classify_level(_acceptance(), _probe(has_heading_structure=False))
    assert r.level == "L1" and r.blocking_conditions == ["no_structural_signal"]
    assert classify_level(_acceptance(statuses=["Failed"]), _probe()).level == "L2"
    r = classify_level(_acceptance(statuses=["Passed"]), _probe())
    assert r.level == "L3" and "quality_layer_not_run" in r.blocking_conditions
    bad_q = QualityResult(format="docx", overall_pass=False)
    assert classify_level(_acceptance(statuses=["Passed"], quality=bad_q), _probe()).level == "L3"
    good_q = QualityResult(format="docx", overall_pass=True)
    r = classify_level(_acceptance(statuses=["Passed"], quality=good_q), _probe())
    assert r.level == "L4" and r.profile == OFFICE_PROFILE_NAME
    assert isinstance(r, LevelResult)  # FR3: shared dataclass, not a fork


def test_manual_check_routes_to_needs_human_not_blocking():
    r = classify_level(_acceptance(statuses=["Passed", "Manual Check Needed"]), _probe())
    assert r.level == "L3"
    assert "r1" in r.needs_human


def test_never_l5_fuzz():
    """AC3: randomized inputs can never produce L5 (seeded — deterministic)."""
    rng = random.Random(20260701)
    statuses = ["Passed", "Failed", "Manual Check Needed"]
    for _ in range(500):
        acceptance = None
        if rng.random() > 0.1:
            quality = None
            if rng.random() > 0.5:
                quality = QualityResult(format="docx", overall_pass=rng.random() > 0.5)
            acceptance = _acceptance(
                openable=rng.random() > 0.2,
                statuses=[rng.choice(statuses) for _ in range(rng.randrange(0, 6))],
                quality=quality,
            )
        probe = _probe(
            has_text=rng.random() > 0.3,
            has_heading_structure=rng.random() > 0.5,
            has_table_header_marks=rng.random() > 0.5,
            has_alt_text_signal=rng.random() > 0.5,
        )
        result = classify_level(acceptance, probe)
        assert result.level in {"L0", "L1", "L2", "L3", "L4"}


def test_probe_reads_real_docx(tmp_path):
    rich = make_docx(tmp_path / "rich.docx", headings=[("T", 0)], tables=1,
                     inline_images=1, image_alt="chart",
                     body_paragraphs=["Some body text."])
    probe = probe_office_structure(rich, FileType.DOCX)
    assert probe.has_text and probe.has_heading_structure
    assert probe.has_table_header_marks and probe.has_alt_text_signal
    assert probe.table_count == 1 and probe.image_count == 1

    empty = make_docx(tmp_path / "empty.docx")
    probe = probe_office_structure(empty, FileType.DOCX)
    assert not probe.has_text and not probe.has_heading_structure

    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip at all")
    probe = probe_office_structure(broken, FileType.DOCX)  # must never raise
    assert probe == OfficeStructureProbe(False, False, False, False, 0, 0, 0)


def test_end_to_end_classification(tmp_path):
    path = make_docx(tmp_path / "l2.docx", title="T", headings=[("T", 0)],
                     inline_images=1, image_alt=None)  # structure present, alt fails
    acceptance = evaluate_office_acceptance(path)
    result = classify_level(acceptance, probe_office_structure(path, FileType.DOCX))
    assert result.level == "L2"
    assert "docx-alt-text" in result.blocking_conditions
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_levels.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_remedy.office_levels'`

- [ ] **Step 3: Implement `office_levels.py`**

```python
"""Office Remediation-Level classifier (L0-L4) — PRD §3.1, FR3.

OOXML has no PDF-style tag tree: heading styles + ``w:tblHeader`` + ``docPr``
alt attributes *are* the structure layer, so the level gates read those
signals. Reuses ``levels.LevelResult`` (FR3 — one shared contract for the
District burndown report) and carries the identical never-L5 invariant.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_remedy.levels import LevelResult
from project_remedy.models import FileType
from project_remedy.office_acceptance import OfficeAcceptanceResult
from project_remedy.office_rules import NS, qn_w

logger = logging.getLogger(__name__)

OFFICE_PROFILE_NAME = "LACCD-DistrictUA1-Office"


@dataclass(frozen=True)
class OfficeStructureProbe:
    """Raw structural facts read straight from the OOXML parts. Never LLM-derived."""

    has_text: bool
    has_heading_structure: bool
    has_table_header_marks: bool
    has_alt_text_signal: bool
    paragraph_count: int
    table_count: int
    image_count: int


_EMPTY_PROBE = OfficeStructureProbe(False, False, False, False, 0, 0, 0)


def probe_office_structure(path: Path, file_type: FileType) -> OfficeStructureProbe:
    """Read structural facts from a docx. Never raises (mirrors levels.probe_structure)."""
    if file_type != FileType.DOCX:
        raise ValueError(
            f"office_levels Phase 1 supports DOCX only, got {file_type} (pptx/xlsx are Phase 2/3)"
        )
    try:
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        logger.warning("probe_office_structure failed for %s: %s", path, exc)
        return _EMPTY_PROBE

    has_text = any((t.text or "").strip() for t in root.iter(qn_w("t")))

    has_heading = False
    paragraph_count = 0
    for p in root.iter(qn_w("p")):
        paragraph_count += 1
        p_pr = p.find(qn_w("pPr"))
        if p_pr is None:
            continue
        style = p_pr.find(qn_w("pStyle"))
        style_val = ((style.get(qn_w("val")) if style is not None else "") or "").lower()
        if style_val.startswith(("heading", "title")) or p_pr.find(qn_w("outlineLvl")) is not None:
            has_heading = True

    has_tbl_header = root.find(f".//{qn_w('tblHeader')}") is not None
    table_count = sum(1 for _ in root.iter(qn_w("tbl")))

    image_count = 0
    has_alt = False
    for kind in ("inline", "anchor"):
        for container in root.iter(f"{{{NS['wp']}}}{kind}"):
            doc_pr = container.find(f"{{{NS['wp']}}}docPr")
            if doc_pr is None:
                continue
            image_count += 1
            if (doc_pr.get("descr") or "").strip() or (doc_pr.get("title") or "").strip():
                has_alt = True

    return OfficeStructureProbe(
        has_text=has_text,
        has_heading_structure=has_heading,
        has_table_header_marks=has_tbl_header,
        has_alt_text_signal=has_alt,
        paragraph_count=paragraph_count,
        table_count=table_count,
        image_count=image_count,
    )


def classify_level(
    acceptance: OfficeAcceptanceResult | None,
    probe: OfficeStructureProbe,
    *,
    profile_name: str = OFFICE_PROFILE_NAME,
) -> LevelResult:
    """Classify an Office document into L0-L4. Never returns L5 (invariant)."""
    sub_scores = _build_sub_scores(acceptance, probe)
    needs_human = (
        [r.rule_id for r in acceptance.checker_report.results if r.status == "Manual Check Needed"]
        if acceptance is not None
        else []
    )

    def result(level: str, blocking: list[str], *, machine: bool = True) -> LevelResult:
        # Defensive: the classifier must never emit L5 (same invariant as levels.py).
        assert level in {"L0", "L1", "L2", "L3", "L4"}, f"illegal level {level!r}"
        return LevelResult(
            level=level,
            machine_certifiable=machine,
            sub_scores=sub_scores,
            blocking_conditions=blocking,
            needs_human=needs_human,
            profile=profile_name,
        )

    if acceptance is None:
        return result("L0", ["evaluation_error"], machine=False)
    if not acceptance.openable:
        return result("L0", ["not_openable"], machine=False)
    if not probe.has_text:
        return result("L0", ["no_text_layer"])
    if not (probe.has_heading_structure or probe.has_table_header_marks or probe.has_alt_text_signal):
        return result("L1", ["no_structural_signal"])

    failed = [r.rule_id for r in acceptance.checker_failures]
    if failed:
        return result("L2", failed)

    # L3 reached: all deterministic rules pass. L4 = L3 + quality layer green
    # (audit_office_quality's QualityResult, attached by the caller — FR3).
    l4_blockers: list[str] = []
    if acceptance.quality_result is None:
        l4_blockers.append("quality_layer_not_run")
    elif not acceptance.quality_result.overall_pass:
        l4_blockers.append("quality_failed")
    if l4_blockers:
        return result("L3", l4_blockers)
    return result("L4", [])


def _build_sub_scores(
    acceptance: OfficeAcceptanceResult | None, probe: OfficeStructureProbe
) -> dict[str, Any]:
    failed = len(acceptance.checker_failures) if acceptance is not None else 0
    manual = (
        sum(1 for r in acceptance.checker_report.results if r.status == "Manual Check Needed")
        if acceptance is not None
        else 0
    )
    return {
        "failed_rule_count": failed,
        "manual_check_count": manual,
        "paragraph_count": probe.paragraph_count,
        "table_count": probe.table_count,
        "image_count": probe.image_count,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_levels.py -q`
Expected: PASS. If `QualityResult(format="docx", overall_pass=False)` raises in `__post_init__`, check `DIMENSIONS_BY_FORMAT` includes `"docx"` (it does — the office judges use it); adjust only the constructor kwargs, never the classifier.

- [ ] **Step 5: Commit**

```bash
git add src/project_remedy/office_levels.py tests/unit/test_office_levels.py
git commit -m "feat: office_levels L0-L4 classifier + structure probe (never-L5 invariant, AC3)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: FR5 — acceptance gate after Office remediation

**Files:**
- Modify: `src/project_remedy/office_acceptance.py` (add `summarize_office_acceptance`)
- Modify: `backend/app/engine_service.py:277` (`_remediate_office`)
- Test: `tests/unit/test_office_remediate_gate.py`

**Interfaces:**
- Consumes: `evaluate_office_acceptance`, `OfficeAcceptanceResult`; `Job` dataclass (`backend/app/jobs.py:43` — fields `id, kind, status, stage, progress, input_path, output_path, report_path, error, created_at, updated_at, result_media_type, metadata_json`).
- Produces: `summarize_office_acceptance(result: OfficeAcceptanceResult) -> dict[str, Any]`; `_remediate_office` writes an `"acceptance"` key into the job's `metadata_json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_office_remediate_gate.py`:

```python
"""FR5: Office remediation output is validated before being reported done."""

from __future__ import annotations

import json
from types import SimpleNamespace

from backend.app.engine_service import _remediate_office
from backend.app.jobs import JOB_KIND_REMEDIATE_OFFICE, Job
from project_remedy.office_acceptance import evaluate_office_acceptance, summarize_office_acceptance
from tests.unit.office_fixtures import make_docx


def test_summarize_office_acceptance(tmp_path):
    path = make_docx(tmp_path / "bad.docx")  # no title/language/headings
    summary = summarize_office_acceptance(evaluate_office_acceptance(path))
    assert summary["passed"] is False
    assert "docx-title" in summary["failed_rule_ids"]
    assert summary["package_valid"] is True
    assert isinstance(summary["manual_check_rule_ids"], list)


class _FakeStore:
    def __init__(self):
        self.updates: list[dict] = []

    async def update(self, job_id, **kwargs):
        self.updates.append({"job_id": job_id, **kwargs})


async def test_remediate_office_attaches_acceptance_metadata(tmp_path):
    input_path = make_docx(tmp_path / "input.docx",
                           body_paragraphs=["Some body text for the remediator to work with."])
    job = Job(
        id="job-test-1", kind=JOB_KIND_REMEDIATE_OFFICE, status="running", stage="",
        progress=0.0, input_path=str(input_path), output_path="", report_path="",
        error="", created_at="", updated_at="", metadata_json="{}",
    )
    store = _FakeStore()
    settings = SimpleNamespace(job_dir=tmp_path / "jobs")

    await _remediate_office(job, store, settings)

    final = store.updates[-1]
    assert final.get("status") == "done"
    meta = json.loads(final["metadata_json"])
    assert "acceptance" in meta
    assert set(meta["acceptance"]) >= {"passed", "failed_rule_ids", "summary"}
    # remediation sets title/language/headings, so those must not be in the failures
    assert "docx-title" not in meta["acceptance"]["failed_rule_ids"]
    stages = [u.get("stage") for u in store.updates]
    assert "evaluating_acceptance" in stages
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_office_remediate_gate.py -q`
Expected: FAIL — `ImportError: cannot import name 'summarize_office_acceptance'`

- [ ] **Step 3: Add `summarize_office_acceptance` to `office_acceptance.py`**

```python
def summarize_office_acceptance(result: OfficeAcceptanceResult) -> dict[str, Any]:
    """JSON-safe acceptance summary for job metadata / API responses (FR5)."""
    return {
        "passed": result.passed,
        "summary": result.summary(),
        "failed_rule_ids": [r.rule_id for r in result.checker_failures],
        "manual_check_rule_ids": [
            r.rule_id for r in result.checker_report.results if r.status == "Manual Check Needed"
        ],
        "screen_reader_error_count": len(result.screen_reader_errors),
        "package_valid": result.package_result.passed,
    }
```

- [ ] **Step 4: Wire the gate into `_remediate_office`**

In `backend/app/engine_service.py`, inside `_remediate_office`, after the `await remediator.remediate(...)` line and *before* the existing `meta = _json.loads(...)` block, restructure so the acceptance gate runs and its summary lands in `metadata_json`:

```python
    await store.update(job.id, stage="remediating", progress=0.30)
    remediator = OfficeRemediator()
    await remediator.remediate(input_path, output_path, title=input_path.stem)

    try:
        meta = _json.loads(job.metadata_json or "{}")
    except Exception:  # noqa: BLE001
        meta = {}

    # FR5 (office-verify): validate remediation output before reporting done —
    # the same role evaluate_pdf_acceptance plays for the PDF path above.
    await store.update(job.id, stage="evaluating_acceptance", progress=0.70)
    if ft in (FileType.DOCX, FileType.PPTX, FileType.XLSX):
        from project_remedy.office_acceptance import (
            evaluate_office_acceptance,
            summarize_office_acceptance,
        )

        try:
            acceptance = await asyncio.to_thread(
                evaluate_office_acceptance, output_path, file_type=ft
            )
            meta["acceptance"] = summarize_office_acceptance(acceptance)
        except Exception as exc:  # noqa: BLE001 - gate failure must not lose the output
            meta["acceptance"] = {"passed": False, "error": str(exc)}
    else:
        meta["acceptance"] = {"passed": False, "error": f"unsupported legacy type {ft.value}"}
```

Keep the existing `if meta.get("quality"):` block after this (it appends `quality_result` to the same `meta`), and change the final `store.update` to persist the metadata:

```python
    await store.update(
        job.id,
        status="done",
        stage="complete",
        progress=1.0,
        output_path=str(output_path),
        result_media_type=media_type_for(ft),
        metadata_json=_json.dumps(meta),
    )
```

Also delete the now-redundant `await store.update(job.id, metadata_json=_json.dumps(meta))` inside the quality block (the final update persists it).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_office_remediate_gate.py -q`
Expected: PASS. If `_FakeStore` lacks a method `_remediate_office` calls, add the same async-recording stub for it. If `JobStore` type annotations cause import errors, they won't at runtime — `engine_service` only calls `store.update` here.

- [ ] **Step 6: Full suite + commit**

Run: `uv run pytest tests/unit -q` — expected PASS.

```bash
git add src/project_remedy/office_acceptance.py backend/app/engine_service.py tests/unit/test_office_remediate_gate.py
git commit -m "feat: FR5 acceptance gate after office remediation + summarize_office_acceptance

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: `cli_office.py` — `check` + `classify-level` with FR8 legacy guard

**Files:**
- Create: `src/project_remedy/cli_office.py`
- Modify: `pyproject.toml:62-63` (`[project.scripts]`)
- Test: `tests/unit/test_cli_office.py`

**Interfaces:**
- Consumes: `evaluate_office_acceptance`, `summarize_office_acceptance`, `probe_office_structure`, `classify_level`, `_infer_file_type`.
- Produces: click group `office_group` with `check` and `classify-level` subcommands; console script `remedy-office`. (The PRD's third subcommand `report` ships with `office_compliance_report.py` in the Phase 4 plan.)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cli_office.py`:

```python
"""CLI tests: exit codes, JSON output, FR8 fail-closed legacy guard."""

from __future__ import annotations

import json

from click.testing import CliRunner

from project_remedy.cli_office import office_group
from tests.unit.office_fixtures import make_docx, make_fake_ole2


def test_check_passes_on_good_docx(tmp_path):
    path = make_docx(
        tmp_path / "good.docx", title="Good", language="en-US",
        headings=[("Good", 0)],
        body_paragraphs=["Body text following the title paragraph."],
    )
    result = CliRunner().invoke(office_group, ["check", str(path), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is True
    assert len(payload["checks"]) == 12


def test_check_fails_on_bad_docx(tmp_path):
    path = make_docx(tmp_path / "bad.docx")
    result = CliRunner().invoke(office_group, ["check", str(path), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert "docx-title" in payload["failed_rule_ids"]


def test_classify_level_outputs_level(tmp_path):
    path = make_docx(tmp_path / "doc.docx", title="T", headings=[("T", 0)])
    result = CliRunner().invoke(office_group, ["classify-level", str(path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["level"] in {"L0", "L1", "L2", "L3", "L4"}
    assert payload["profile"] == "LACCD-DistrictUA1-Office"


def test_fr8_legacy_ole2_fails_closed(tmp_path):
    doc = make_fake_ole2(tmp_path / "legacy.doc")
    result = CliRunner().invoke(office_group, ["check", str(doc)])
    assert result.exit_code != 0
    assert "OOXML conversion" in result.output

    # OLE2 bytes hiding behind a modern suffix must also fail closed
    disguised = tmp_path / "disguised.docx"
    disguised.write_bytes(doc.read_bytes())
    result = CliRunner().invoke(office_group, ["check", str(disguised)])
    assert result.exit_code != 0
    assert "OOXML conversion" in result.output


def test_non_zip_garbage_fails_closed(tmp_path):
    junk = tmp_path / "junk.docx"
    junk.write_bytes(b"\x00\x01\x02 not a package")
    result = CliRunner().invoke(office_group, ["check", str(junk)])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_cli_office.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_remedy.cli_office'`

- [ ] **Step 3: Implement `cli_office.py`**

```python
"""Click ``office`` subgroup — office-verify check and level classification.

Commands::

    remedy-office check <file> [--json]
    remedy-office classify-level <file>

FR8: legacy binary formats (.doc/.ppt/.xls, OLE2 magic) fail closed with a
clear conversion-required error — never silently mis-parsed as ZIP.
(The ``report`` subcommand ships with office_compliance_report in Phase 4.)
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from project_remedy.models import FileType
from project_remedy.office_acceptance import (
    _infer_file_type,
    evaluate_office_acceptance,
    summarize_office_acceptance,
)
from project_remedy.office_levels import classify_level, probe_office_structure

console = Console()

_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_LEGACY_SUFFIXES = {".doc", ".ppt", ".xls"}
_CONVERT_MSG = "unsupported legacy format — requires OOXML conversion first (.docx/.pptx/.xlsx)"


def _guard_ooxml(path: Path) -> FileType:
    """FR8 fail-closed guard: reject legacy/OLE2/non-ZIP input before parsing."""
    if path.suffix.lower() in _LEGACY_SUFFIXES:
        raise click.ClickException(f"{_CONVERT_MSG} (got '{path.suffix}')")
    head = path.open("rb").read(8)
    if head.startswith(_OLE2_MAGIC):
        raise click.ClickException(f"{_CONVERT_MSG} (OLE2 container detected)")
    if not head.startswith(b"PK"):
        raise click.ClickException("not an OOXML package (missing ZIP signature)")
    try:
        return _infer_file_type(path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group("office")
def office_group() -> None:
    """office-verify: deterministic OOXML accessibility validation."""


@office_group.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def check(file: Path, as_json: bool) -> None:
    """Run the full deterministic rule catalog against FILE."""
    file_type = _guard_ooxml(file)
    result = evaluate_office_acceptance(file, file_type=file_type)
    summary = summarize_office_acceptance(result)
    if as_json:
        payload = dict(summary)
        payload["file_type"] = file_type.value
        payload["checks"] = [asdict(r) for r in result.checker_report.results]
        click.echo(json.dumps(payload, indent=2))
    else:
        table = Table(title=f"office-verify: {file.name}")
        table.add_column("Rule")
        table.add_column("Status")
        table.add_column("Details")
        for r in result.checker_report.results:
            table.add_row(r.rule_id, r.status, "; ".join(r.details))
        console.print(table)
        console.print(f"[bold]{'PASS' if result.passed else 'FAIL'}[/bold] — {result.summary()}")
    sys.exit(0 if result.passed else 1)


@office_group.command("classify-level")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def classify_level_cmd(file: Path) -> None:
    """Classify FILE onto the L0-L4 remediation ladder (never L5)."""
    file_type = _guard_ooxml(file)
    if file_type != FileType.DOCX:
        raise click.ClickException("classify-level supports .docx only in Phase 1 (pptx/xlsx: Phase 2/3)")
    acceptance = evaluate_office_acceptance(file, file_type=file_type)
    probe = probe_office_structure(file, file_type)
    level = classify_level(acceptance, probe)
    click.echo(json.dumps(asdict(level), indent=2, default=str))
```

- [ ] **Step 4: Register the console script**

In `pyproject.toml` `[project.scripts]` (line 62), add:

```toml
remedy-office = "project_remedy.cli_office:office_group"
```

- [ ] **Step 5: Run tests + smoke the entry point**

Run: `uv run pytest tests/unit/test_cli_office.py -q`
Expected: PASS.
Run: `uv run remedy-office --help`
Expected: usage text listing `check` and `classify-level`. (If the script isn't found, `uv sync` to refresh the editable install.)

- [ ] **Step 6: Commit**

```bash
git add src/project_remedy/cli_office.py pyproject.toml tests/unit/test_cli_office.py uv.lock
git commit -m "feat: remedy-office CLI (check, classify-level) with FR8 fail-closed guard

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: Acceptance-criteria sweep (AC1 coverage, AC6 dependency check, full suite)

**Files:**
- Modify: `pyproject.toml` (dev group only, if `pytest-cov` is absent)

**Interfaces:**
- Consumes: everything above.
- Produces: verified AC1/AC2/AC3/AC6/AC7 evidence; Phase 0+1 complete.

- [ ] **Step 1: Ensure pytest-cov (dev dependency only)**

```bash
uv run python -c "import pytest_cov" 2>/dev/null || uv add --dev pytest-cov
```

- [ ] **Step 2: AC1 — branch coverage of the rule engine ≥95%**

```bash
uv run pytest tests/unit -q \
  --cov=project_remedy.office_checker \
  --cov=project_remedy.office_rules \
  --cov=project_remedy.office_levels \
  --cov-branch --cov-report=term-missing
```

Expected: total coverage for these three modules ≥95%. If a rule function has an uncovered branch, add the missing Pass/Fail fixture case to `test_office_rules_docx.py` — do not exclude lines.

- [ ] **Step 3: AC6 — zero new runtime dependencies**

```bash
git diff 50da047 -- pyproject.toml
```

Expected: the only changes are the `remedy-office` script entry and (optionally) `pytest-cov` in the **dev** group. Nothing added under `[project.dependencies]`.

- [ ] **Step 4: Full suite, twice (NFR1 sanity)**

```bash
uv run pytest tests/unit -q && uv run pytest tests/unit -q
```

Expected: identical PASS results both runs.

- [ ] **Step 5: Verify AC7 checklist explicitly**

- The 5 legacy docx rule ids still emitted and behaving identically: `tests/unit/test_office_acceptance_baseline.py` green, unmodified since Task 2 (`git log --oneline tests/unit/test_office_acceptance_baseline.py` shows exactly one commit).
- ≥6 new rule ids evaluated: golden test asserts 12 results including `OOXML-DOCX-2.2/2.3/3.2/4.2/5.1/6.1/7.1`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: dev coverage tooling + Phase 0/1 acceptance-criteria sweep (AC1/AC6/AC7)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-Review Notes (performed at plan-writing time)

- **Spec coverage:** G1→Task 3; G2/NFR1/NFR3→Tasks 4-9 (stdlib+vendored only, determinism test in Task 9); G3→status vocabulary everywhere; G4 (levels half)→Task 10, (VPAT half FR4)→explicitly deferred to Phase 4 plan; G5/FR5→Task 11; G6/FR6→fixable flags in Task 3; G8/AC7→Tasks 2+9+13. FR2→`xml_refs` in Task 3. FR7→Task 12 (minus `report`, deferred with FR4). FR8→Task 12 guard. NFR2 is satisfied by construction (single in-memory parse; no test added — subsecond on fixture-sized files is not meaningfully assertable in unit tests). NFR4→Task 3 defaulted fields + Task 2/9 baseline. NFR5→Tasks 1-2. NFR6→`details` cite paragraph/table/image ordinals. AC4/AC5→deferred (corpus + VPAT plans).
- **Type consistency check:** `OfficeCheckResult` fields (`rule_id/description/status/details/fixable/checkpoint/wcag_ref`) used identically in Tasks 3-12; `DocxContext.load` classmethod referenced consistently; `classify_level(acceptance, probe, *, profile_name=...)` signature matches between Task 10 impl and Task 12 CLI call; `summarize_office_acceptance` keys (`passed/summary/failed_rule_ids/manual_check_rule_ids/screen_reader_error_count/package_valid`) match between Task 11 impl and Task 11/12 tests.
- **Known judgment calls encoded:** legacy-id emission for the 5 pre-existing rules (grounded in `_heuristics.py:35` consumers); heading-skip sequence starts at virtual level 0; 2.3/2.2/3.2 vacuous-pass semantics; `Manual Check Needed` never blocks `passed`.
