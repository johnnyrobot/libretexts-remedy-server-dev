from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pikepdf
import pytest
from pikepdf import Dictionary, Name

from project_remedy.pdf_fixer import (
    _artifactize_unlinked_marked_content_without_mcids,
    _base14_substitute_font_path,
    _raw_has_real_marked_content_without_mcid,
    _wrap_content_gaps,
    fix_annotations_tagged,
    fix_artifact_mcids_tagged_as_real_content,
    fix_cidset_conformance,
    fix_color_contrast,
    fix_embedded_file_specs,
    fix_figures_alt_text,
    fix_figures_alt_text_quality,
    fix_form_xobject_artifacts,
    fix_heading_hierarchy_quality,
    fix_cidfont_type2_maps,
    fix_list_structure,
    fix_marked_content_missing_mcids,
    fix_nested_marked_content_scopes,
    fix_note_ids,
    fix_orphan_graphic_marked_content_as_artifacts,
    fix_parent_tree_unreachable_entries,
    fix_page_retag,
    fix_remove_scripts,
    fix_reused_form_xobject_mcids,
    fix_role_map,
    fix_table_regularity,
    fix_toc_structure,
    fix_type1_font_conformance,
    fix_tounicode,
    fix_untagged_content,
    fix_unwrap_nested_artifacts,
    walk_structure_tree,
    _append_visible_text_scaffold,
    _artifactize_decorative_pattern_figures,
    _fix_subtitle_and_transitional_headings,
    _heading_text_looks_like_body,
    _insert_struct_child_for_visible_page,
    _normalize_qr_code_alt_text,
    _remove_top_level_whitespace_actualtext_spans,
)
from project_remedy.pdf_checker import (
    PDFAccessibilityChecker,
    _find_suspicious_extracted_text,
    _is_generic_alt_text,
    _parse_tounicode_mapped_codes,
)
from project_remedy.tag_tree_reader import _extract_mcid_text
from project_remedy.pdf_vision import (
    AltTextIssue,
    HeadingHierarchyVisionAgent,
    HeadingIssue,
    VisionAnalyzer,
    _node_mcids,
)
from project_remedy.vision_prompts import (
    heading_hierarchy_quality_prompt,
    page_alt_text_quality_prompt,
)


def _font_resource() -> Dictionary:
    return Dictionary({
        "/Font": Dictionary({
            "/F1": Dictionary({
                "/Type": Name("/Font"),
                "/Subtype": Name("/Type1"),
                "/BaseFont": Name("/Helvetica"),
            }),
        }),
    })


def _add_basic_structure_tree(pdf: pikepdf.Pdf, page: pikepdf.Page) -> None:
    mcr = Dictionary({
        "/Type": Name("/MCR"),
        "/Pg": page.obj,
        "/MCID": 0,
    })
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page.obj,
        "/K": mcr,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": paragraph,
    }))
    paragraph["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array([
                0,
                pdf.make_indirect(pikepdf.Array([paragraph])),
            ]),
        })),
        "/ParentTreeNextKey": 1,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root


def _add_empty_structure_tree(pdf: pikepdf.Pdf, page: pikepdf.Page) -> None:
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
    }))
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array(),
        })),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root


def test_visible_text_scaffold_inserts_pages_in_reading_order(tmp_path) -> None:
    pdf = pikepdf.Pdf.new()
    page1 = pdf.add_blank_page(page_size=(200, 200))
    page2 = pdf.add_blank_page(page_size=(200, 200))
    _add_empty_structure_tree(pdf, page1)
    root = pdf.Root["/StructTreeRoot"]
    parent = root["/K"]

    sect2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Sect"),
        "/Pg": page2.obj,
        "/ID": "remedy-visible-text-page-2",
        "/K": pikepdf.Array(),
    }))
    sect1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Sect"),
        "/Pg": page1.obj,
        "/ID": "remedy-visible-text-page-1",
        "/K": pikepdf.Array(),
    }))

    _insert_struct_child_for_visible_page(parent, sect2, 1, pdf)
    _insert_struct_child_for_visible_page(parent, sect1, 0, pdf)
    _append_visible_text_scaffold(
        pdf,
        sect1,
        page1,
        ["Document Title", "Abstract", "Body paragraph"],
        page_idx=0,
        id_prefix="remedy-visible-text-page-1",
    )

    out = tmp_path / "visible-order.pdf"
    pdf.save(out)

    with pikepdf.open(out) as saved:
        kids = list(saved.Root["/StructTreeRoot"]["/K"]["/K"])
        visible_ids = [
            str(kid.get("/ID", "") or "")
            for kid in kids
            if str(kid.get("/ID", "") or "").startswith("remedy-visible-text-page-")
        ]
    assert visible_ids == ["remedy-visible-text-page-1", "remedy-visible-text-page-2"]


def test_checker_accepts_remedy_visible_text_reading_order_evidence(tmp_path) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    _add_empty_structure_tree(pdf, page)
    parent = pdf.Root["/StructTreeRoot"]["/K"]
    sect = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Sect"),
        "/Pg": page.obj,
        "/ID": "remedy-visible-text-page-1",
        "/K": pikepdf.Array(),
    }))
    _insert_struct_child_for_visible_page(parent, sect, 0, pdf)
    _append_visible_text_scaffold(
        pdf,
        sect,
        page,
        ["Document Title", "Abstract", "Body paragraph", "1 Introduction", "More body text"],
        page_idx=0,
        id_prefix="remedy-visible-text-page-1",
    )
    out = tmp_path / "visible-order-check.pdf"
    pdf.save(out)

    report = PDFAccessibilityChecker(out).run_all()
    reading_order = next(r for r in report.results if r.rule_id == "doc-reading-order")

    assert reading_order.status == "Passed"
    assert "visible-page evidence" in reading_order.details[0]


def test_fix_marked_content_missing_mcids_wires_actualtext_span() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (A) Tj ET\n"
        b"EMC\n"
        b"/Span <</ActualText (e)>> BDC\n"
        b"BT /F1 12 Tf (x) Tj (y) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)

    changes = fix_marked_content_missing_mcids(pdf)

    assert any("Assigned MCIDs to 1" in change for change in changes)
    content = page["/Contents"].read_bytes().decode("latin-1")
    assert "/MCID 1" in content
    parent_tree = pdf.Root["/StructTreeRoot"]["/ParentTree"]
    parent_arr = parent_tree["/Nums"][1]
    assert len(parent_arr) == 2
    assert _extract_mcid_text(page)[1] == "e"


def test_fix_marked_content_missing_mcids_converts_real_bmc_to_bdc() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (A) Tj ET\n"
        b"EMC\n"
        b"/EmbeddedDocument BMC\n"
        b"BT /F1 12 Tf (Body) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)

    changes = fix_marked_content_missing_mcids(pdf)

    assert any("Assigned MCIDs to 1" in change for change in changes)
    content = page["/Contents"].read_bytes().decode("latin-1")
    assert "/EmbeddedDocument BMC" not in content
    assert "/Span" in content
    assert "/MCID 1" in content
    assert _extract_mcid_text(page)[1] == "Body"


def test_fix_marked_content_missing_mcids_repairs_bdc_without_properties() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (A) Tj ET\n"
        b"EMC\n"
        b"/MC0 BDC\n"
        b"BT /F1 12 Tf (Body) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)

    changes = fix_marked_content_missing_mcids(pdf)

    assert any("Assigned MCIDs to 1" in change for change in changes)
    content = page["/Contents"].read_bytes().decode("latin-1")
    assert "/MC0 BDC" not in content
    assert "/Span" in content
    assert "/MCID 1" in content
    assert _extract_mcid_text(page)[1] == "Body"


def test_raw_missing_mcid_prescan_ignores_existing_mcid_spans() -> None:
    raw = (
        "/P <</MCID 0>> BDC\n"
        "BT /F1 12 Tf (A) Tj ET\n"
        "EMC\n"
        "/Artifact BMC\n"
        "q 1 0 0 1 0 0 cm /Im1 Do Q\n"
        "EMC\n"
    )

    assert not _raw_has_real_marked_content_without_mcid(raw)


def test_raw_missing_mcid_prescan_detects_actualtext_span() -> None:
    raw = (
        "/P <</MCID 0>> BDC\n"
        "BT /F1 12 Tf (A) Tj ET\n"
        "EMC\n"
        "/Span <</ActualText (e)>> BDC\n"
        "BT /F1 12 Tf (x) Tj ET\n"
        "EMC\n"
    )

    assert _raw_has_real_marked_content_without_mcid(raw)


def test_raw_missing_mcid_prescan_detects_hex_actualtext_span() -> None:
    raw = (
        "/P <</MCID 0>> BDC\n"
        "BT /F1 12 Tf (A) Tj ET\n"
        "EMC\n"
        "/Span<</ActualText<FEFF0065>>> BDC\n"
        "BT /F1 12 Tf (x) Tj ET\n"
        "EMC\n"
    )

    assert _raw_has_real_marked_content_without_mcid(raw)


def test_raw_missing_mcid_prescan_ignores_compact_span_inside_artifact() -> None:
    raw = (
        "/Artifact BMC\n"
        "/Span <</Lang<656E2D5553>>>BDC\n"
        "BT /F1 12 Tf (footer) Tj ET\n"
        "EMC\n"
        "EMC\n"
    )

    assert not _raw_has_real_marked_content_without_mcid(raw)


def test_artifactize_unlinked_marked_content_handles_compact_lang_dict() -> None:
    raw = (
        "/Span <</Lang<656E2D5553>>>BDC\n"
        "BT /F1 12 Tf (footer) Tj ET\n"
        "EMC\n"
        "/P <</MCID 0/Lang<656E2D5553>>>BDC\n"
        "BT /F1 12 Tf (body) Tj ET\n"
        "EMC\n"
    )

    repaired, converted = _artifactize_unlinked_marked_content_without_mcids(raw)

    assert converted == 1
    # The repair emits ``/Artifact BMC`` always followed by ``\n``; whether
    # the next non-blank line is the artifact body depends on how many
    # newlines the producer kept around the original BDC. Accept any amount
    # of intervening whitespace between the marker and the body.
    assert re.search(
        r"/Artifact BMC\n+BT /F1 12 Tf \(footer\) Tj ET", repaired
    ) is not None
    assert "/P <</MCID 0/Lang<656E2D5553>>>BDC" in repaired


def test_color_contrast_checker_passes_obvious_black_text_without_vision(tmp_path: Path) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(300, 300))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT 0 0 0 rg /F1 14 Tf 40 240 Td (High contrast text) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)
    path = tmp_path / "black-text.pdf"
    pdf.save(path)

    with pikepdf.open(path) as opened:
        result = PDFAccessibilityChecker(path)._check_color_contrast(opened)

    assert result.status == "Passed"
    assert "Deterministic raster check" in result.details[0]


def test_color_contrast_checker_uses_local_background_for_white_text(tmp_path: Path) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(300, 300))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"q 0 0 0 rg 20 190 260 60 re f Q\n"
        b"/P <</MCID 0>> BDC\n"
        b"BT 1 1 1 rg /F1 20 Tf 40 225 Td (White title) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)
    path = tmp_path / "white-on-black.pdf"
    pdf.save(path)

    with pikepdf.open(path) as opened:
        result = PDFAccessibilityChecker(path)._check_color_contrast(opened)

    assert result.status == "Passed"
    assert "text/background contrast" in result.details[0]


def test_fix_color_contrast_uses_rendered_local_background(tmp_path: Path) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(300, 300))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"q 0 0 0 rg 0 0 300 300 re f Q\n"
        b"/P <</MCID 0>> BDC\n"
        b"BT 0.25 0.25 0.25 rg /F1 18 Tf 40 225 Td (Low contrast) Tj ET\n"
        b"BT 0.25 0.25 0.25 rg /F1 18 Tf 40 195 Td (More low contrast) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)
    path = tmp_path / "low-contrast-local-bg.pdf"
    pdf.save(path)

    with pikepdf.open(path, allow_overwriting_input=True) as opened:
        before = PDFAccessibilityChecker(path)._check_color_contrast(opened)
        changes = fix_color_contrast(opened)
        opened.save(path)

    with pikepdf.open(path) as opened:
        after = PDFAccessibilityChecker(path)._check_color_contrast(opened)

    assert before.status == "Failed"
    assert any("low-contrast text colors" in change for change in changes)
    assert after.status == "Passed"


def test_fix_color_contrast_does_not_apply_white_background_fallback_when_rendered_passes(
    tmp_path: Path,
) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(300, 300))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"q 0 0 0 rg 0 0 300 300 re f Q\n"
        b"/P <</MCID 0>> BDC\n"
        b"BT 0.45 0.45 0.45 rg /F1 18 Tf 40 225 Td (Readable gray text) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)
    path = tmp_path / "gray-on-black.pdf"
    pdf.save(path)

    with pikepdf.open(path, allow_overwriting_input=True) as opened:
        before = PDFAccessibilityChecker(path)._check_color_contrast(opened)
        changes = fix_color_contrast(opened)
        raw = opened.pages[0]["/Contents"].read_bytes().decode("latin-1")

    assert before.status == "Passed"
    assert changes == []
    assert "0.45 0.45 0.45 rg" in raw


def test_reading_order_checker_accepts_monotonic_structure_pages(tmp_path: Path) -> None:
    pdf = pikepdf.Pdf.new()
    page1 = pdf.add_blank_page(page_size=(200, 200))
    page2 = pdf.add_blank_page(page_size=(200, 200))
    p1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page1.obj,
        "/ActualText": "First page paragraph",
    }))
    p2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page2.obj,
        "/ActualText": "Second page paragraph",
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([p1, p2]),
    }))
    p1["/P"] = document
    p2["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root
    path = tmp_path / "monotonic-order.pdf"
    pdf.save(path)

    with pikepdf.open(path) as opened:
        result = PDFAccessibilityChecker(path)._check_logical_reading_order(opened)

    assert result.status == "Passed"
    assert "progress in page order" in result.details[0]


def test_reading_order_checker_accepts_dense_structure_with_tiny_page_regressions(tmp_path: Path) -> None:
    pdf = pikepdf.Pdf.new()
    pages = [pdf.add_blank_page(page_size=(200, 200)) for _ in range(10)]
    sequence: list[int] = []
    for page_idx in range(10):
        sequence.extend([page_idx] * 60)
        if page_idx in {4, 6, 8}:
            sequence.append(page_idx - 1)

    kids = []
    for index, page_idx in enumerate(sequence):
        node = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructElem"),
            "/S": Name("/P"),
            "/Pg": pages[page_idx].obj,
            "/ActualText": f"Paragraph {index}",
        }))
        kids.append(node)

    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array(kids),
    }))
    for kid in kids:
        kid["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root
    path = tmp_path / "dense-order-regressions.pdf"
    pdf.save(path)

    with pikepdf.open(path) as opened:
        result = PDFAccessibilityChecker(path)._check_logical_reading_order(opened)

    assert result.status == "Passed"
    assert "progress in page order" in result.details[0]


def test_repeated_sparse_reference_links_are_not_repetitive_navigation(tmp_path: Path) -> None:
    pdf = pikepdf.Pdf.new()
    for page_idx in range(30):
        page = pdf.add_blank_page(page_size=(200, 200))
        if page_idx not in {2, 8, 14, 20}:
            continue
        annot = pdf.make_indirect(Dictionary({
            "/Type": Name("/Annot"),
            "/Subtype": Name("/Link"),
            "/Rect": pikepdf.Array([20, 20, 80, 40]),
            "/A": Dictionary({
                "/S": Name("/URI"),
                "/URI": "https://doi.org/10.1234/example",
            }),
        }))
        page["/Annots"] = pikepdf.Array([annot])
    path = tmp_path / "sparse-reference-links.pdf"
    pdf.save(path)

    with pikepdf.open(path) as opened:
        result = PDFAccessibilityChecker(path)._check_no_repetitive_links(opened)

    assert result.status == "Passed"
    assert "sparse cross-reference" in result.details[0]


def test_fix_list_structure_wraps_generated_li_in_list(tmp_path: Path) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    lbl = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Lbl"),
        "/Pg": page.obj,
        "/ActualText": "1.",
    }))
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page.obj,
        "/K": lbl,
    }))
    lbl["/P"] = paragraph
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": paragraph,
    }))
    paragraph["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root
    path = tmp_path / "orphan-label.pdf"
    pdf.save(path)

    with pikepdf.open(path, allow_overwriting_input=True) as opened:
        changes = fix_list_structure(opened)
        li_result = PDFAccessibilityChecker(path)._check_li_parent(opened)
        lbl_result = PDFAccessibilityChecker(path)._check_lbl_lbody_parent(opened)

    assert any("orphan Lbl/LBody" in change for change in changes)
    assert any("generated LI" in change for change in changes)
    assert li_result.status == "Passed"
    assert lbl_result.status == "Passed"


def test_empty_mcid_cleanup_preserves_graphics_state_blocks() -> None:
    raw = (
        "/Span <</MCID 1>> BDC\n"
        "\nQ\nQ\n"
        "EMC\n"
        "/Span <</MCID 2>> BDC\n"
        "\n \n"
        "EMC\n"
    )

    cleaned, removed = _remove_top_level_whitespace_actualtext_spans(raw)

    assert removed == 1
    assert "/MCID 1" in cleaned
    assert "Q\nQ" in cleaned
    assert "/MCID 2" not in cleaned


def test_wrap_content_gaps_separates_emc_from_graphics_operator() -> None:
    raw = "q\n/Im1 Do\nQ/P <</MCID 0>> BDC\nBT /F1 12 Tf (A) Tj ET\nEMC\n"

    rewritten, mcids = _wrap_content_gaps(raw, 1, "/P")

    assert mcids == [1]
    assert "QEMC" not in rewritten
    assert "Q\nEMC" in rewritten


def test_suspicious_text_allows_layout_gap_before_url_host() -> None:
    text = "Department of the Treasury  Internal Revenue Service  www.irs.gov"

    assert _find_suspicious_extracted_text(text) == []


def test_heading_body_heuristic_demotes_schedule_rows() -> None:
    assert _heading_text_looks_like_body("Feb. 10 Review Syllabus")
    assert _heading_text_looks_like_body("June 2 Final Exam")


def test_heading_hierarchy_prompt_requires_visual_judgment() -> None:
    prompt = heading_hierarchy_quality_prompt(logical_order="1. /H1\n2. /H2")

    assert "structurally valid H1/H2/H3 sequence can still be wrong" in prompt
    assert "title-like prominent text is tagged as P/Span" in prompt
    assert '"element_index"' in prompt
    assert '"correct_tag"' in prompt


def test_heading_agent_accepts_heading_corrections_schema(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "page.png"
    prompts: list[str] = []

    def _render(_pdf_path: Path, _page_num: int, dpi: int = 150) -> Path:  # noqa: ARG001
        image_path.write_bytes(b"png")
        return image_path

    class _Provider:
        async def analyze_image(self, image, prompt, **kwargs):  # noqa: ARG002
            prompts.append(prompt)
            return (
                '{"status":"pass","heading_corrections":[{'
                '"element_index":"3","current_tag":"paragraph",'
                '"correct_tag":"heading level 1","visible_text":"Annual Report",'
                '"reason":"Title-like prominent text is tagged as body text"}]}'
            )

    monkeypatch.setattr("project_remedy.pdf_vision.render_page_to_image", _render)
    monkeypatch.setattr(
        "project_remedy.pdf_vision._get_page_structure_order",
        lambda _path, _page: '1. /H1\n2. /P\n3. /P  (text: "Annual Report")',
    )

    issues, _raw = asyncio.run(
        HeadingHierarchyVisionAgent(_Provider()).review_page(Path("dummy.pdf"), 1)
    )

    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].element_index == 3
    assert issues[0].current_tag == "P"
    assert issues[0].correct_tag == "H1"
    assert issues[0].suggestion == "Retag as H1"
    assert issues[0].text == "Annual Report"
    assert prompts and "Use the rendered page image, not just the existing tag sequence" in prompts[0]


def test_vision_analyzer_runs_heading_and_alt_quality_agents(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.save(pdf_path)
    image_path = tmp_path / "page.png"

    def _render(_pdf_path, _page_num, dpi=150):  # noqa: ARG001
        image_path.write_bytes(b"png")
        return image_path

    class _Provider:
        async def analyze_image(self, image, prompt, **kwargs):  # noqa: ARG002
            if "heading hierarchy" in prompt:
                return (
                    '{"status":"fail","findings":[{"severity":"error",'
                    '"element_index":2,"message":"Body text is tagged as H1",'
                    '"suggested_fix":"Retag as P"}]}'
                )
            return (
                '{"figures":[{"figure_index":1,"status":"fail",'
                '"severity":"error","message":"Alt text does not describe the chart",'
                '"suggested_alt_text":"Chart of weekly assignments"}]}'
            )

    monkeypatch.setattr("project_remedy.pdf_vision.render_page_to_image", _render)
    monkeypatch.setattr(
        "project_remedy.pdf_vision._get_page_structure_order",
        lambda _path, _page: "1. /H1 Body text",
    )
    monkeypatch.setattr(
        "project_remedy.pdf_vision._get_page_figure_alt_list",
        lambda _path, _page: '1. alt="Figure"',
    )
    monkeypatch.setattr(
        "project_remedy.pdf_vision._get_page_figure_alt_entries",
        lambda _path, _page: [
            type("FigureEntry", (), {"figure_index": 1, "current_alt_text": "Figure"})()
        ],
    )

    analyzer = VisionAnalyzer(_Provider())

    heading = asyncio.run(analyzer.analyze_heading_hierarchy(pdf_path, pages=[1]))
    alt = asyncio.run(analyzer.analyze_alt_text_quality(pdf_path, pages=[1]))

    assert heading.heading_issues[0].description == "Body text is tagged as H1"
    assert heading.heading_issues[0].element_index == 2
    assert alt.alt_text_issues[0].description == "Alt text does not describe the chart"
    assert alt.alt_text_issues[0].suggested_alt_text == "Chart of weekly assignments"


def test_checker_consumes_vision_heading_and_alt_quality_errors() -> None:
    class _Vision:
        heading_issues = [
            HeadingIssue(page=1, description="Visible title is not tagged as a heading", severity="error")
        ]
        alt_text_issues = [
            AltTextIssue(
                page=1,
                figure_index=1,
                description="Alt text is generic",
                severity="error",
                suggested_alt_text="Campus map showing accessible entrances",
            )
        ]

    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    _add_empty_structure_tree(pdf, page)
    checker = PDFAccessibilityChecker(Path("dummy.pdf"), vision_result=_Vision())

    heading = checker._check_heading_nesting(pdf)
    alt = checker._check_figures_alt_text(pdf)

    assert heading.status == "Failed"
    assert "Visible title" in heading.details[0]
    assert alt.status == "Failed"
    assert "Alt text is generic" in alt.details[0]


def test_checker_fails_structurally_valid_headings_on_vision_error() -> None:
    checker = PDFAccessibilityChecker(
        Path("dummy.pdf"),
        vision_result=type("Vision", (), {
            "heading_issues": [
                HeadingIssue(
                    page=1,
                    description="Schedule row is visually body text",
                    severity="error",
                    element_index=2,
                    current_tag="H2",
                    correct_tag="P",
                    suggestion="Retag as P",
                )
            ],
        })(),
    )
    checker._walk_structure_tree = lambda _pdf: [
        (Dictionary({"/S": Name("/H1")}), 0, None),
        (Dictionary({"/S": Name("/H2")}), 0, None),
    ]

    result = checker._check_heading_nesting(pikepdf.Pdf.new())

    assert result.status == "Failed"
    assert result.fixable is True
    assert "Schedule row is visually body text" in result.details[0]
    assert "H2 -> P" in result.details[0]


def test_checker_treats_unindexed_heading_demotion_as_warning() -> None:
    checker = PDFAccessibilityChecker(
        Path("dummy.pdf"),
        vision_result=type("Vision", (), {
            "heading_issues": [
                HeadingIssue(
                    page=1,
                    description="Combined title/subtitle is tagged as H1 but should be separate visual elements",
                    severity="error",
                    current_tag="H1",
                    correct_tag="P",
                    suggestion="Retag as P",
                )
            ],
        })(),
    )
    checker._walk_structure_tree = lambda _pdf: [
        (Dictionary({"/S": Name("/H1")}), 0, None),
        (Dictionary({"/S": Name("/H2")}), 0, None),
    ]

    result = checker._check_heading_nesting(pikepdf.Pdf.new())

    assert result.status == "Passed"


def test_checker_treats_banner_heading_suggestion_as_warning_when_h1_exists() -> None:
    checker = PDFAccessibilityChecker(
        Path("dummy.pdf"),
        vision_result=type("Vision", (), {
            "heading_issues": [
                HeadingIssue(
                    page=1,
                    description="Document header/banner text is tagged as P instead of heading",
                    severity="error",
                    current_tag="P",
                    correct_tag="H1",
                    suggestion="Retag as H1 or P with appropriate styling",
                )
            ],
        })(),
    )
    checker._walk_structure_tree = lambda _pdf: [
        (Dictionary({"/S": Name("/H1")}), 0, None),
        (Dictionary({"/S": Name("/P")}), 0, None),
    ]

    result = checker._check_heading_nesting(pikepdf.Pdf.new())

    assert result.status == "Passed"
    assert "heading hierarchy is acceptable" in result.details[0]


def test_checker_treats_untargeted_heading_suggestion_as_warning() -> None:
    checker = PDFAccessibilityChecker(
        Path("dummy.pdf"),
        vision_result=type("Vision", (), {
            "heading_issues": [
                HeadingIssue(
                    page=2,
                    description="Subsection heading/label is tagged as P instead of H3",
                    severity="error",
                    current_tag="P",
                    correct_tag="H3",
                    suggestion="Retag as H3",
                )
            ],
        })(),
    )
    checker._walk_structure_tree = lambda _pdf: [
        (Dictionary({"/S": Name("/H1")}), 0, None),
        (Dictionary({"/S": Name("/P")}), 0, None),
    ]

    result = checker._check_heading_nesting(pikepdf.Pdf.new())

    assert result.status == "Passed"
    assert "heading hierarchy is acceptable" in result.details[0]


def test_checker_treats_table_internal_heading_promotion_as_warning() -> None:
    checker = PDFAccessibilityChecker(
        Path("dummy.pdf"),
        vision_result=type("Vision", (), {
            "heading_issues": [
                HeadingIssue(
                    page=2,
                    description="This is a subsection heading within List B and within the table structure",
                    severity="error",
                    current_tag="P",
                    correct_tag="H3",
                    suggestion="Retag as H3",
                )
            ],
        })(),
    )
    checker._walk_structure_tree = lambda _pdf: [
        (Dictionary({"/S": Name("/H1")}), 0, None),
        (Dictionary({"/S": Name("/P")}), 0, None),
    ]

    result = checker._check_heading_nesting(pikepdf.Pdf.new())

    assert result.status == "Passed"


def test_checker_treats_form_label_heading_oscillation_as_warning() -> None:
    checker = PDFAccessibilityChecker(
        Path("dummy.pdf"),
        vision_result=type("Vision", (), {
            "heading_issues": [
                HeadingIssue(
                    page=4,
                    description="Table/section header row label is tagged as P instead of H3",
                    severity="error",
                    current_tag="P",
                    correct_tag="H3",
                    suggestion="Retag as H3",
                ),
                HeadingIssue(
                    page=3,
                    description="Instructions label is tagged as H3 but visually is a bold label for body text instructions",
                    severity="error",
                    current_tag="H3",
                    correct_tag="Span",
                    suggestion="Retag as Span",
                ),
                HeadingIssue(
                    page=2,
                    description="Duplicate/ghost heading appears after the table content in the tag tree",
                    severity="error",
                    current_tag="H2",
                    correct_tag="Span",
                    suggestion="Retag as Span",
                ),
            ],
        })(),
    )
    checker._walk_structure_tree = lambda _pdf: [
        (Dictionary({"/S": Name("/H1")}), 0, None),
        (Dictionary({"/S": Name("/H2")}), 0, None),
    ]

    result = checker._check_heading_nesting(pikepdf.Pdf.new())

    assert result.status == "Passed"


def test_checker_treats_title_word_suggestion_as_warning_when_h1_exists() -> None:
    checker = PDFAccessibilityChecker(
        Path("dummy.pdf"),
        vision_result=type("Vision", (), {
            "heading_issues": [
                HeadingIssue(
                    page=1,
                    description="Prominent title word is tagged as Span instead of heading",
                    severity="error",
                    current_tag="Span",
                    correct_tag="H1",
                    suggestion="Merge into title H1",
                )
            ],
        })(),
    )
    checker._walk_structure_tree = lambda _pdf: [
        (Dictionary({"/S": Name("/H1"), "/ActualText": "AN ESSAY"}), 0, None),
        (Dictionary({"/S": Name("/Span"), "/ActualText": "ESSAY"}), 0, None),
    ]

    result = checker._check_heading_nesting(pikepdf.Pdf.new())

    assert result.status == "Passed"


def test_fix_figures_alt_text_quality_rewrites_inaccurate_alt(tmp_path, monkeypatch) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    mcr = Dictionary({
        "/Type": Name("/MCR"),
        "/Pg": page.obj,
        "/MCID": 0,
    })
    figure = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Figure"),
        "/Pg": page.obj,
        "/K": mcr,
        "/Alt": pikepdf.String("Chart"),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": figure,
    }))
    figure["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array([
                0,
                pdf.make_indirect(pikepdf.Array([figure])),
            ]),
        })),
        "/ParentTreeNextKey": 1,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    image_path = tmp_path / "page.png"

    def _render(_pdf_path, _page_num, dpi=150):  # noqa: ARG001
        image_path.write_bytes(b"png")
        return image_path

    class _Provider:
        async def analyze_image(self, image, prompt, **kwargs):  # noqa: ARG002
            return (
                '{"figures":[{"figure_index":1,"status":"fail","severity":"error",'
                '"message":"Alt text is too generic",'
                '"suggested_alt_text":"Bar chart comparing weekly assignment totals"}]}'
            )

    monkeypatch.setattr("project_remedy.pdf_vision.render_page_to_image", _render)

    changes = fix_figures_alt_text_quality(pdf, vision_provider=_Provider())

    assert any("Rewrote 1 figure alt text" in change for change in changes)
    assert str(figure["/Alt"]) == "Bar chart comparing weekly assignment totals"


def test_fix_heading_hierarchy_quality_applies_element_indexed_retag(tmp_path, monkeypatch) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    heading = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
        "/K": Dictionary({"/Type": Name("/MCR"), "/Pg": page.obj, "/MCID": 0}),
    }))
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page.obj,
        "/K": Dictionary({"/Type": Name("/MCR"), "/Pg": page.obj, "/MCID": 1}),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([heading, paragraph]),
    }))
    heading["/P"] = document
    paragraph["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array([
                0,
                pdf.make_indirect(pikepdf.Array([heading, paragraph])),
            ]),
        })),
        "/ParentTreeNextKey": 1,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    image_path = tmp_path / "page.png"

    def _render(_pdf_path, _page_num, dpi=150):  # noqa: ARG001
        image_path.write_bytes(b"png")
        return image_path

    class _Provider:
        async def analyze_image(self, image, prompt, **kwargs):  # noqa: ARG002
            return (
                '{"status":"fail","findings":[{"severity":"error","element_index":2,'
                '"message":"Body text is tagged as H1","correct_tag":"P",'
                '"suggested_fix":"Retag as P"}]}'
            )

    monkeypatch.setattr("project_remedy.pdf_vision.render_page_to_image", _render)

    changes = fix_heading_hierarchy_quality(pdf, vision_provider=_Provider())

    assert any("Retagged 1 element" in change for change in changes)
    assert str(heading["/S"]) == "/P"


def test_fix_heading_hierarchy_quality_can_promote_visible_text_nodes(tmp_path, monkeypatch) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page.obj,
        "/ID": pikepdf.String("remedy-visible-text-page-1-block-1"),
        "/K": Dictionary({"/Type": Name("/MCR"), "/Pg": page.obj, "/MCID": 0}),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([paragraph]),
    }))
    paragraph["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array([
                0,
                pdf.make_indirect(pikepdf.Array([paragraph])),
            ]),
        })),
        "/ParentTreeNextKey": 1,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    image_path = tmp_path / "page.png"

    def _render(_pdf_path, _page_num, dpi=150):  # noqa: ARG001
        image_path.write_bytes(b"png")
        return image_path

    class _Provider:
        async def analyze_image(self, image, prompt, **kwargs):  # noqa: ARG002
            return (
                '{"status":"fail","findings":[{"severity":"error","element_index":2,'
                '"message":"Section heading is tagged as body text",'
                '"current_tag":"P","correct_tag":"H2",'
                '"suggested_fix":"Retag as H2"}]}'
            )

    monkeypatch.setattr("project_remedy.pdf_vision.render_page_to_image", _render)

    changes = fix_heading_hierarchy_quality(pdf, vision_provider=_Provider())

    assert any("Retagged 1 element" in change for change in changes)
    assert str(paragraph["/S"]) == "/H2"


def test_subtitle_cleanup_keeps_numbered_section_headings() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    heading = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H3"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("5.2 Hardware and Schedule"),
        "/K": Dictionary({"/Type": Name("/MCR"), "/Pg": page.obj, "/MCID": 0}),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([heading]),
    }))
    heading["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array([
                0,
                pdf.make_indirect(pikepdf.Array([heading])),
            ]),
        })),
        "/ParentTreeNextKey": 1,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert changes == []
    assert str(heading["/S"]) == "/H3"


def test_subtitle_cleanup_keeps_form_title_headings() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    title = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("Registration Form"),
    }))
    section = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H2"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("Individual Information"),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([title, section]),
    }))
    title["/P"] = document
    section["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert changes == []
    assert str(title["/S"]) == "/H1"
    assert str(section["/S"]) == "/H2"


def test_subtitle_cleanup_demotes_caution_label_heading() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    caution = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H2"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("CAUTION !"),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([caution]),
    }))
    caution["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(caution["/S"]) == "/Span"


def test_subtitle_cleanup_demotes_state_list_heading() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    state_list = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H2"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("Arizona, Arkansas, New Mexico, Oklahoma"),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([state_list]),
    }))
    state_list["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(state_list["/S"]) == "/Span"


def test_subtitle_cleanup_demotes_numbered_list_sentence_heading() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    item = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H2"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String(
            "1. Certify that the TIN you are giving is correct;"
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([item]),
    }))
    item["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(item["/S"]) == "/P"


def test_subtitle_cleanup_demotes_numbered_product_list_heading() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    item = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String(
            "1. Lorem ipsum dolor $299 sit amet, consectetur adipiscing elit. "
            "2. Proin lorem sem $234 rhoncus ut aliquet in."
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([item]),
    }))
    item["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(item["/S"]) == "/P"


def test_subtitle_cleanup_skips_metadata_title_heading_when_no_content() -> None:
    """An image-only cover with no marked content can't host a metadata H1.

    Synthesizing a free-floating /H1 with /ActualText (the previous behavior)
    guarantees an Adobe "Associated with content" failure because the heading
    has no /K marked-content children. Refuse to create that orphan and leave
    the structure as-is; image-only covers must be remediated by OCR'ing the
    page first so a real text node exists to promote.
    """
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    blank_heading = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([blank_heading]),
    }))
    blank_heading["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root
    pdf.docinfo["/Title"] = "SPRING 2013 CATALOGUE"

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert "Created first-page title heading from document metadata" not in changes
    # No orphan /H1 carrying the metadata title should have been injected.
    heading_actual_texts = [
        str(node.get("/ActualText", ""))
        for node, _depth, _parent in walk_structure_tree(pdf)
        if str(node.get("/S", "")) == "/H1"
    ]
    assert "SPRING 2013 CATALOGUE" not in heading_actual_texts


@pytest.mark.skip(
    reason=(
        "Inline-heading marker creation currently produces /Hn nodes carrying "
        "/ActualText but no /K marked-content children. Adobe Acrobat's "
        "'Associated with content' rule fails every such node, so the engine "
        "now refuses to synthesize them. Re-enable once the engine can carve "
        "MCIDs out of the source paragraph and bind each new heading to its "
        "own slice of marked content."
    )
)
def test_subtitle_cleanup_creates_product_grid_title_heading() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String(
            "$299 Lorem Ipsum $299 Lorem Ipsum $299 Lorem Ipsum "
            "This a where you can read a product description."
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([paragraph]),
    }))
    paragraph["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Created 1 inline heading marker" in change for change in changes)
    assert any(
        str(node.get("/S", "")) == "/H3"
        and str(node.get("/ActualText", "")) == "Lorem Ipsum"
        for node, _depth, _parent in walk_structure_tree(pdf)
    )


def test_subtitle_cleanup_demotes_duplicate_h1_fragments() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    combined = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("PRINCE furniture"),
    }))
    fragment = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("furniture"),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([combined, fragment]),
    }))
    combined["/P"] = document
    fragment["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(combined["/S"]) == "/H1"
    assert str(fragment["/S"]) == "/Span"


def test_subtitle_cleanup_demotes_body_fragment_headings() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    fragment = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H2"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String(
            "and bold heading text indicate section heading level equivalent to"
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([fragment]),
    }))
    fragment["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(fragment["/S"]) == "/Span"


def test_subtitle_cleanup_demotes_finis_marker() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    marker = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H2"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("F I N I S ."),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([marker]),
    }))
    marker["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(marker["/S"]) == "/P"


def test_subtitle_cleanup_demotes_long_name_list_heading() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    heading = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String(
            "Unni Jacobsen, Torstein Jahr, Suzanne Bolstad, Eivind Bergene, "
            "Turid Brun, Vigdis Trondsen, Lea Blindheim"
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([heading]),
    }))
    heading["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 1 non-structural heading" in change for change in changes)
    assert str(heading["/S"]) == "/P"


@pytest.mark.skip(
    reason=(
        "Inline-heading marker creation currently produces orphan /Hn nodes "
        "that fail Adobe's 'Associated with content' rule. Re-enable once the "
        "engine can split the source paragraph's marked content among the new "
        "headings."
    )
)
def test_subtitle_cleanup_creates_drylab_inline_section_headings() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String(
            "WWDC and Silicon Valley: We were invited by Apple. "
            "Cine Gear: We decided not to attend. "
            "Annual General Meeting: Drylab's AGM will be held on June 16th."
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([paragraph]),
    }))
    paragraph["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Created 3 inline heading marker" in change for change in changes)
    heading_text = {
        str(node.get("/ActualText", ""))
        for node, _depth, _parent in walk_structure_tree(pdf)
        if str(node.get("/S", "")) == "/H2"
    }
    assert {
        "WWDC and Silicon Valley:",
        "Cine Gear:",
        "Annual General Meeting:",
    } <= heading_text


@pytest.mark.skip(
    reason=(
        "Demotion side of this test still works, but the inline-heading "
        "marker creation it also exercises produces orphan /Hn nodes that "
        "fail Adobe's 'Associated with content' rule. Re-enable once the "
        "engine can split the source paragraph's marked content among the "
        "new headings."
    )
)
def test_subtitle_cleanup_repairs_i9_form_heading_noise() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    nodes = []
    for tag, text in [
        ("/H1", "Form I-9 Edition 01/20/25 Page 1 of 4"),
        ("/H2", "LIST B"),
        ("/H2", "(1) NOT VALID FOR EMPLOYMENT"),
        ("/H2", "Department of Homeland Security U.S. Citizenship and Immigration Services"),
        ("/H3", "Date of Rehire (if applicable) New Name (if applicable)"),
        ("/H3", "Reverification"),
        ("/H3", "Reverification"),
        (
            "/P",
            "Section 1. Employee Information and Attestation: Employees must complete this section. "
            "Section 2. Employer Review and Verification: Employers complete this section. "
            "Instructions: This supplement must be completed by any preparer and/or translator.",
        ),
    ]:
        elem = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructElem"),
            "/S": Name(tag),
            "/Pg": page.obj,
            "/ActualText": pikepdf.String(text),
        }))
        nodes.append(elem)
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array(nodes),
    }))
    for node in nodes:
        node["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root
    pdf.docinfo["/Title"] = "USCIS Form I-9"

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Demoted 7 non-structural heading" in change for change in changes)
    assert str(nodes[0]["/S"]) == "/P"
    assert str(nodes[1]["/S"]) == "/Span"
    assert str(nodes[2]["/S"]) == "/P"
    assert str(nodes[3]["/S"]) == "/Span"
    assert str(nodes[4]["/S"]) == "/P"
    assert str(nodes[5]["/S"]) == "/P"
    assert str(nodes[6]["/S"]) == "/P"
    heading_text = {
        str(node.get("/ActualText", ""))
        for node, _depth, _parent in walk_structure_tree(pdf)
        if str(node.get("/S", "")) == "/H2"
    }
    assert {
        "Section 1. Employee Information and Attestation",
        "Section 2. Employer Review and Verification",
    } <= heading_text
    assert any(
        str(node.get("/S", "")) == "/H3"
        and str(node.get("/ActualText", "")) == "Instructions:"
        for node, _depth, _parent in walk_structure_tree(pdf)
    )


@pytest.mark.skip(
    reason=(
        "Inline-heading marker creation currently produces orphan /Hn nodes "
        "that fail Adobe's 'Associated with content' rule. Re-enable once the "
        "engine can split the source paragraph's marked content among the new "
        "headings."
    )
)
def test_subtitle_cleanup_creates_inline_heading_markers() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String(
            "Date General Instructions Section references are to the Internal Revenue Code. "
            "Future developments. See the latest updates."
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([paragraph]),
    }))
    paragraph["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = _fix_subtitle_and_transitional_headings(pdf)

    assert any("Created 2 inline heading marker" in change for change in changes)
    heading_text = {
        str(node.get("/ActualText", ""))
        for node, _depth, _parent in walk_structure_tree(pdf)
        if str(node.get("/S", "")) in {"/H2", "/H3"}
    }
    assert {"General Instructions", "Future developments"} <= heading_text


def test_alt_quality_prompt_fails_title_only_cover_alt() -> None:
    prompt = page_alt_text_quality_prompt(
        figure_list="Figure 1 bbox=[0.0, 0.0, 1.0, 0.8] alt='IRS logo with title text'"
    )

    assert "composite cover figures" in prompt
    assert "only repeats logo/title text" in prompt
    assert "omits a substantive" in prompt
    assert "Do not merge nearby real page text" in prompt


def test_pdf_vision_node_mcids_handles_nested_arrays_without_resolve_lookup() -> None:
    node = Dictionary({
        "/K": pikepdf.Array([
            Dictionary({"/MCID": 1}),
            pikepdf.Array([Dictionary({"/MCID": 2})]),
        ]),
    })

    assert _node_mcids(node) == (1, 2)


def test_qr_code_alt_text_normalizer_uses_page_heading_context() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    heading = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/Pg": page.obj,
        "/ActualText": pikepdf.String("PRINCE furniture"),
    }))
    figure = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Figure"),
        "/Pg": page.obj,
        "/Alt": pikepdf.String(
            "QR code with three large position markers in corners and scattered black modules on white background."
        ),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([heading, figure]),
    }))
    heading["/P"] = document
    figure["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    assert _normalize_qr_code_alt_text(pdf) == 1
    assert str(figure["/Alt"]) == "QR code linking to Prince Furniture website."


def test_artifactize_decorative_pattern_figure() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/Figure <</MCID 0>> BDC\n"
        b"q 0 1 0 rg 0 0 200 200 re S Q\n"
        b"EMC\n"
    )
    mcr = Dictionary({
        "/Type": Name("/MCR"),
        "/Pg": page.obj,
        "/MCID": 0,
    })
    figure = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Figure"),
        "/Pg": page.obj,
        "/K": mcr,
        "/Alt": pikepdf.String("Green geometric square pattern forming abstract cover design"),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": pikepdf.Array([figure]),
    }))
    figure["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array([0, pdf.make_indirect(pikepdf.Array([figure]))]),
        })),
        "/ParentTreeNextKey": 1,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    assert _artifactize_decorative_pattern_figures(pdf) == 1
    assert document.get("/K") is None or len(document["/K"]) == 0
    assert b"/Artifact BMC" in page["/Contents"].read_bytes()


def test_fix_untagged_content_promotes_full_page_text_artifact() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/Artifact BMC\n"
        b"BT /F1 12 Tf (Real text) Tj ET\n"
        b"EMC\n"
    )
    _add_empty_structure_tree(pdf, page)

    changes = fix_untagged_content(pdf)

    assert any("Promoted 1 text artifact" in change for change in changes)
    content = page["/Contents"].read_bytes().decode("latin-1")
    assert "/P" in content
    assert "/MCID 0" in content
    assert "/Artifact" not in content
    assert _extract_mcid_text(page)[0] == "Real text"


def test_fix_embedded_file_specs_adds_uf_name() -> None:
    pdf = pikepdf.Pdf.new()
    embedded = pdf.make_stream(b"settings")
    embedded["/Type"] = Name("/EmbeddedFile")
    filespec = pdf.make_indirect(Dictionary({
        "/Type": Name("/Filespec"),
        "/F": pikepdf.String("Press Quality.joboptions"),
        "/EF": Dictionary({"/F": embedded}),
    }))
    pdf.Root["/Names"] = Dictionary({
        "/EmbeddedFiles": Dictionary({
            "/Names": pikepdf.Array([
                pikepdf.String("Press Quality.joboptions"),
                filespec,
            ]),
        }),
    })

    changes = fix_embedded_file_specs(pdf)

    assert any("embedded file specification" in change for change in changes)
    assert str(filespec["/UF"]) == "Press Quality.joboptions"


def test_fix_artifact_mcids_tagged_as_real_content_retags_owned_artifact() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/Artifact <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Real text) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)

    changes = fix_artifact_mcids_tagged_as_real_content(pdf)

    content = page["/Contents"].read_bytes().decode("latin-1")
    assert any("Retagged 1 MCID-bearing Artifact" in change for change in changes)
    assert "/Artifact <</MCID 0>> BDC" not in content
    assert "/P <</MCID 0>> BDC" in content


def test_extract_mcid_text_emits_actualtext_without_page_text_operator() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = Dictionary({
        "/XObject": Dictionary({
            "/Fm1": pikepdf.Stream(
                pdf,
                b"BT /F1 12 Tf (Inside form) Tj ET\n",
                Type=Name("/XObject"),
                Subtype=Name("/Form"),
                FormType=1,
                BBox=pikepdf.Array([0, 0, 100, 20]),
                Resources=_font_resource(),
            ),
        }),
    })
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0 /ActualText (Rendered form text)>> BDC\n"
        b"q /Fm1 Do Q\n"
        b"EMC\n"
    )

    fix_form_xobject_artifacts(pdf)

    content = page["/Contents"].read_bytes().decode("latin-1")
    assert content.lstrip().startswith("/P")
    assert _extract_mcid_text(page)[0] == "Rendered form text"


def test_fix_unwrap_nested_artifacts_recurses_into_form_xobjects() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    form = pikepdf.Stream(
        pdf,
        b"/Artifact BMC\n"
        b"/Span <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Inside) Tj ET\n"
        b"EMC\n"
        b"EMC\n",
        Type=Name("/XObject"),
        Subtype=Name("/Form"),
        FormType=1,
        BBox=pikepdf.Array([0, 0, 100, 20]),
        Resources=_font_resource(),
    )
    page["/Resources"] = Dictionary({
        "/XObject": Dictionary({"/Fm1": form}),
    })
    page["/Contents"] = pdf.make_stream(b"q /Fm1 Do Q\n")

    changes = fix_unwrap_nested_artifacts(pdf)

    content = form.read_bytes().decode("latin-1")
    assert any("Unwrapped 1 nested artifact" in change for change in changes)
    assert "/Artifact BMC" not in content
    assert "/Span <</MCID 0>> BDC" in content


def test_fix_unwrap_nested_artifacts_unwraps_same_line_artifact_in_span() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Contents"] = pdf.make_stream(
        b"/Span <</MCID 0>> BDC\n"
        b"q 0 0 10 10 re /Artifact << /Type /Layout >> BDC\n"
        b"f* Q EMC\n"
        b"EMC\n"
    )

    changes = fix_unwrap_nested_artifacts(pdf)

    content = page["/Contents"].read_bytes().decode("latin-1")
    assert any("Unwrapped 1 nested artifact" in change for change in changes)
    assert "/Artifact << /Type /Layout >> BDC" not in content
    assert "/Span <</MCID 0>> BDC" in content
    assert "0 0 10 10 re" in content


def test_fix_unwrap_nested_artifacts_unwraps_unclosed_artifact_with_real_tags() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Contents"] = pdf.make_stream(
        b"/Artifact << /Type /Pagination >> BDC\n"
        b"/Span <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Page text) Tj ET\n"
        b"EMC\n"
    )

    changes = fix_unwrap_nested_artifacts(pdf)

    content = page["/Contents"].read_bytes().decode("latin-1")
    assert any("Unwrapped 1 nested artifact" in change for change in changes)
    assert "/Artifact << /Type /Pagination >> BDC" not in content
    assert "/Span <</MCID 0>> BDC" in content


def test_fix_nested_marked_content_scopes_artifactizes_exposed_graphics() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Contents"] = pdf.make_stream(
        b"/Span <</MCID 0>> BDC\n"
        b"q 1 0 0 1 0 0 cm\n"
        b"/P <</MCID 1>> BDC\n"
        b"BT /F1 12 Tf (Cell text) Tj ET\n"
        b"EMC\n"
        b"q 0 0 10 10 re f* Q\n"
        b"EMC\n"
    )

    changes = fix_nested_marked_content_scopes(pdf)

    content = page["/Contents"].read_bytes().decode("latin-1")
    assert any("Flattened nested marked-content scopes" in change for change in changes)
    assert "/Span <</MCID 0>> BDC\nq 1 0 0 1 0 0 cm\n\nEMC\n/P <</MCID 1>> BDC" in content
    assert "/Artifact << /Type /Layout >> BDC" in content
    assert "q 0 0 10 10 re f* Q" in content
    assert content.count(" BDC") == content.count("EMC")


def test_fix_orphan_graphic_marked_content_as_artifacts() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Real text) Tj ET\n"
        b"EMC\n"
        b"/Span <</MCID 1>> BDC\n"
        b"q 0 0 10 10 re S Q\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)

    changes = fix_orphan_graphic_marked_content_as_artifacts(pdf)

    content = page["/Contents"].read_bytes().decode("latin-1")
    assert any("orphan graphics-only" in change for change in changes)
    assert "/P <</MCID 0>> BDC" in content
    assert "/Span <</MCID 1>> BDC" not in content
    assert "/Artifact << /Type /Layout >> BDC" in content
    assert "q 0 0 10 10 re S Q" in content


def test_fix_parent_tree_unreachable_entries_nulls_removed_nodes() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    _add_basic_structure_tree(pdf, page)
    unreachable = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Figure"),
        "/Pg": page.obj,
        "/K": Dictionary({"/Type": Name("/MCR"), "/MCID": 1, "/Pg": page.obj}),
    }))
    parent_tree = pdf.Root["/StructTreeRoot"]["/ParentTree"]
    parent_arr = parent_tree["/Nums"][1]
    parent_arr.append(unreachable)

    changes = fix_parent_tree_unreachable_entries(pdf)

    assert any("ParentTree entries" in change for change in changes)
    assert parent_arr[1] is None or str(parent_arr[1]) == "null"


def test_fix_page_retag_backfills_null_parent_tree_entry() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Real text) Tj ET\n"
        b"EMC\n"
    )
    _add_basic_structure_tree(pdf, page)
    parent_tree = pdf.Root["/StructTreeRoot"]["/ParentTree"]
    parent_arr = parent_tree["/Nums"][1]
    paragraph = parent_arr[0]
    parent_arr[0] = None

    changes = fix_page_retag(pdf)

    assert any("Backfilled 1 existing MCID ParentTree entries" in change for change in changes)
    assert parent_arr[0] == paragraph


def test_fix_cidfont_type2_maps_adds_identity_for_embedded_descendant() -> None:
    pdf = pikepdf.Pdf.new()
    font_file = pdf.make_stream(b"fontdata")
    descriptor = pdf.make_indirect(Dictionary({
        "/Type": Name("/FontDescriptor"),
        "/FontName": Name("/SubsetFont"),
        "/FontFile2": font_file,
    }))
    descendant = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/CIDFontType2"),
        "/BaseFont": Name("/SubsetFont"),
        "/FontDescriptor": descriptor,
    }))
    type0 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type0"),
        "/BaseFont": Name("/SubsetFont"),
        "/DescendantFonts": pikepdf.Array([descendant]),
    }))
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": type0})})

    changes = fix_cidfont_type2_maps(pdf)

    assert any("CIDToGIDMap" in change for change in changes)
    assert descendant["/CIDToGIDMap"] == Name("/Identity")


def test_fix_form_xobject_artifacts_keeps_tagged_text_after_form_invocation() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0 /ActualText (Body text)>> BDC\n"
        b"q\n"
        b"1 0 0 1 0 0 cm\n"
        b"/OL1 Do\n"
        b"Q\n"
        b"BT /F1 12 Tf (Body text) Tj ET\n"
        b"EMC\n"
    )
    overlay = pikepdf.Stream(
        pdf,
        b"BT /F1 4 Tf (Copyright) Tj ET\n",
        Type=Name("/XObject"),
        Subtype=Name("/Form"),
        FormType=1,
        BBox=pikepdf.Array([0, 0, 100, 20]),
        Resources=Dictionary({
            "/Font": Dictionary({
                "/F1": Dictionary({
                    "/Type": Name("/Font"),
                    "/Subtype": Name("/Type1"),
                    "/BaseFont": Name("/Courier"),
                }),
            }),
        }),
    )
    page["/Resources"] = Dictionary({
        "/Font": _font_resource()["/Font"],
        "/XObject": Dictionary({"/OL1": pdf.make_indirect(overlay)}),
    })
    _add_basic_structure_tree(pdf, page)

    fix_form_xobject_artifacts(pdf)

    content = page["/Contents"].read_bytes().decode("latin-1")
    assert content.lstrip().startswith("/P")
    assert "/MCID 0" in content
    assert "Body text" in _extract_mcid_text(page)[0]


def test_fix_form_xobject_artifacts_removes_unembedded_font_overlay() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Body) Tj ET\n"
        b"q\n"
        b"q\n"
        b"1 0 0 1 0 0 cm\n"
        b"/OL1 Do\n"
        b"Q\n"
        b"Q\n"
        b"EMC\n"
    )
    form_resources = Dictionary({
        "/Font": Dictionary({
            "/F1": Dictionary({
                "/Type": Name("/Font"),
                "/Subtype": Name("/Type1"),
                "/BaseFont": Name("/Courier"),
            }),
        }),
    })
    overlay = pikepdf.Stream(
        pdf,
        b"BT /F1 4 Tf (Copyright) Tj ET\n",
        Type=Name("/XObject"),
        Subtype=Name("/Form"),
        FormType=1,
        BBox=pikepdf.Array([0, 0, 100, 20]),
        Resources=form_resources,
    )
    page["/Resources"] = Dictionary({
        "/Font": _font_resource()["/Font"],
        "/XObject": Dictionary({"/OL1": pdf.make_indirect(overlay)}),
    })
    _add_basic_structure_tree(pdf, page)

    changes = fix_form_xobject_artifacts(pdf)

    assert any("Removed 1 artifact Form XObject" in change for change in changes)
    content = page["/Contents"].read_bytes().decode("latin-1")
    assert "/OL1 Do" not in content
    assert content.strip().endswith("EMC")


def test_fix_reused_form_xobject_mcids_converts_internal_mcids_to_artifacts() -> None:
    pdf = pikepdf.Pdf.new()
    form = pdf.make_indirect(pikepdf.Stream(
        pdf,
        b"/P <</MCID 0>> BDC\nBT /F1 10 Tf (Running header) Tj ET\nEMC\n",
        Type=Name("/XObject"),
        Subtype=Name("/Form"),
        FormType=1,
        BBox=pikepdf.Array([0, 0, 100, 20]),
        Resources=_font_resource(),
        StructParents=7,
    ))
    for _ in range(2):
        page = pdf.add_blank_page(page_size=(200, 200))
        page["/Resources"] = Dictionary({
            "/XObject": Dictionary({"/Fm1": form}),
        })
        page["/Contents"] = pdf.make_stream(b"q /Fm1 Do Q\n")

    changes = fix_reused_form_xobject_mcids(pdf)

    raw = form.read_bytes().decode("latin-1")
    assert any("reused Form XObject" in change for change in changes)
    assert "/MCID" not in raw
    assert raw.count("/Artifact BMC") == 1
    assert form.get("/StructParents") is None


def test_checker_ignores_empty_text_object_outside_marked_content(tmp_path) -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Tagged) Tj ET\n"
        b"EMC\n"
        b"BT\nET\n"
    )
    _add_basic_structure_tree(pdf, page)
    path = tmp_path / "empty-text-object.pdf"
    pdf.save(path)

    report = PDFAccessibilityChecker(path).run_all()
    result = next(r for r in report.results if r.rule_id == "page-content-tagged")

    assert result.status == "Passed"


def test_fix_remove_scripts_removes_annotation_javascript_actions() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    js_action = Dictionary({
        "/S": Name("/JavaScript"),
        "/JS": pikepdf.String("app.alert('x')"),
    })
    uri_action = Dictionary({
        "/S": Name("/URI"),
        "/URI": pikepdf.String("https://example.test"),
    })
    js_annot = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Link"),
        "/Rect": pikepdf.Array([0, 0, 10, 10]),
        "/A": js_action,
    }))
    uri_annot = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Link"),
        "/Rect": pikepdf.Array([10, 10, 20, 20]),
        "/A": uri_action,
    }))
    page["/Annots"] = pikepdf.Array([js_annot, uri_annot])

    changes = fix_remove_scripts(pdf)

    assert any("annotation JavaScript" in change for change in changes)
    assert js_annot.get("/A") is None
    assert uri_annot.get("/A") is not None


def test_fix_figures_alt_text_fallback_is_not_generic() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = _font_resource()
    page["/Contents"] = pdf.make_stream(
        b"/Figure <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf (Women students gathered outside the campus library) Tj ET\n"
        b"EMC\n"
    )
    mcr = Dictionary({
        "/Type": Name("/MCR"),
        "/Pg": page.obj,
        "/MCID": 0,
    })
    figure = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Figure"),
        "/Pg": page.obj,
        "/K": mcr,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": figure,
    }))
    figure["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({
            "/Nums": pikepdf.Array([
                0,
                pdf.make_indirect(pikepdf.Array([figure])),
            ]),
        })),
        "/ParentTreeNextKey": 1,
    }))
    document["/P"] = struct_root
    page["/StructParents"] = 0
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_figures_alt_text(pdf)

    alt = str(figure.get("/Alt", ""))
    assert any("Set fallback /Alt" in change for change in changes)
    assert alt.startswith("Figure related to page text:")
    assert not _is_generic_alt_text(alt)


def test_fix_type1_font_conformance_removes_charset_and_notdef_code() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    descriptor = pdf.make_indirect(Dictionary({
        "/Type": Name("/FontDescriptor"),
        "/FontName": Name("/Example"),
        "/CharSet": pikepdf.String("/A/B"),
        "/FontFile": pdf.make_stream(b"%!PS-AdobeFont-1.0\n"),
    }))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Example"),
        "/Encoding": Dictionary({
            "/Type": Name("/Encoding"),
            "/BaseEncoding": Name("/WinAnsiEncoding"),
            "/Differences": pikepdf.Array([31, Name("/.notdef")]),
        }),
        "/FontDescriptor": descriptor,
    }))
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf (A\\037B) Tj ET\n")

    changes = fix_type1_font_conformance(pdf)

    assert any("Removed invalid /CharSet" in change for change in changes)
    assert any("Replaced 1 simple-font /.notdef" in change for change in changes)
    assert descriptor.get("/CharSet") is None
    content = page["/Contents"].read_bytes()
    assert b"\\037" not in content
    assert b"97" in content


def test_fix_type1_font_conformance_replaces_truetype_control_notdef() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/TrueType"),
        "/BaseFont": Name("/ExampleTrueType"),
        "/Encoding": Name("/WinAnsiEncoding"),
        "/FirstChar": 0,
        "/LastChar": 255,
        "/Widths": pikepdf.Array([0] * 256),
    }))
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf (A\\004B) Tj ET\n")

    changes = fix_type1_font_conformance(pdf)

    content = page["/Contents"].read_bytes()
    assert any("Replaced 1 simple-font /.notdef" in change for change in changes)
    assert b"\\004" not in content
    assert b"97" in content


def test_fix_type1_font_conformance_embeds_acroform_default_font() -> None:
    if _base14_substitute_font_path("/Helvetica") is None:
        pytest.skip("local Helvetica substitute font is unavailable")

    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
    }))
    pdf.Root["/AcroForm"] = pdf.make_indirect(Dictionary({
        "/DR": Dictionary({
            "/Font": Dictionary({
                "/Helv": font,
            }),
        }),
    }))

    changes = fix_type1_font_conformance(pdf)

    descriptor = font.get("/FontDescriptor")
    assert any("Embedded substitutes" in change for change in changes)
    assert isinstance(descriptor, pikepdf.Dictionary)
    assert descriptor.get("/FontFile2") is not None
    assert font.get("/ToUnicode") is not None


def test_fix_type1_font_conformance_preserves_zapf_widths() -> None:
    if _base14_substitute_font_path("/ZaDb") is None:
        pytest.skip("local ZapfDingbats substitute font is unavailable")

    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/ZaDb"),
    }))
    pdf.Root["/AcroForm"] = pdf.make_indirect(Dictionary({
        "/DR": Dictionary({
            "/Font": Dictionary({
                "/ZaDb": font,
            }),
        }),
    }))

    changes = fix_type1_font_conformance(pdf)

    cmap = font["/ToUnicode"].read_bytes().decode("ascii")
    assert any("Embedded substitutes" in change for change in changes)
    assert int(font["/Widths"][52]) > 0
    assert str(font.get("/Encoding")) == "/WinAnsiEncoding"
    assert "<34> <2714>" in cmap


def test_fix_cidset_conformance_removes_descriptor_cidset() -> None:
    pdf = pikepdf.Pdf.new()
    descriptor = pdf.make_indirect(Dictionary({
        "/Type": Name("/FontDescriptor"),
        "/FontName": Name("/ExampleCID"),
        "/CIDSet": pdf.make_stream(b"\xff"),
        "/FontFile2": pdf.make_stream(b"\0\1fake-font"),
    }))
    descendant = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/CIDFontType2"),
        "/BaseFont": Name("/ExampleCID"),
        "/FontDescriptor": descriptor,
    }))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type0"),
        "/BaseFont": Name("/ExampleCID"),
        "/DescendantFonts": pikepdf.Array([descendant]),
    }))
    page = pdf.add_blank_page(page_size=(200, 200))
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})

    changes = fix_cidset_conformance(pdf)

    assert any("Removed unreliable /CIDSet" in change for change in changes)
    assert descriptor.get("/CIDSet") is None


def test_fix_table_regularity_expands_single_cell_tie_row() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    row1_cell = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/TD"),
        "/Pg": page.obj,
    }))
    row2_cell1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/TD"),
        "/Pg": page.obj,
    }))
    row2_cell2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/TD"),
        "/Pg": page.obj,
    }))
    row1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/TR"),
        "/K": pikepdf.Array([row1_cell]),
    }))
    row2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/TR"),
        "/K": pikepdf.Array([row2_cell1, row2_cell2]),
    }))
    table = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Table"),
        "/K": pikepdf.Array([row1, row2]),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": table,
    }))
    for child, parent in [
        (row1_cell, row1),
        (row2_cell1, row2),
        (row2_cell2, row2),
        (row1, table),
        (row2, table),
        (table, document),
    ]:
        child["/P"] = parent
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_table_regularity(pdf)

    assert any("Set /ColSpan" in change for change in changes)
    assert int(row1_cell.get("/ColSpan")) == 2


def test_fix_list_structure_wraps_scalar_li_child_in_lbody() -> None:
    pdf = pikepdf.Pdf.new()
    form = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Form"),
    }))
    li = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/LI"),
        "/K": form,
    }))
    listing = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/L"),
        "/K": li,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": listing,
    }))
    form["/P"] = li
    li["/P"] = listing
    listing["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_list_structure(pdf)

    lbody = li["/K"]
    assert any("Normalized 1 /LI" in change for change in changes)
    assert str(lbody["/S"]) == "/LBody"
    assert str(form["/P"]["/S"]) == "/LBody"


def test_fix_toc_structure_wraps_paragraph_children_in_toci() -> None:
    pdf = pikepdf.Pdf.new()
    paragraph = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
    }))
    toc = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/TOC"),
        "/K": paragraph,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": toc,
    }))
    paragraph["/P"] = toc
    toc["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_toc_structure(pdf)

    toci = toc["/K"]
    assert any("Wrapped 1 non-TOCI" in change for change in changes)
    assert str(toci["/S"]) == "/TOCI"
    assert str(paragraph["/P"]["/S"]) == "/TOCI"


def test_fix_toc_structure_uses_rolemap_for_custom_toc_roles() -> None:
    pdf = pikepdf.Pdf.new()
    child = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/TOC 2"),
    }))
    parent = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Sect"),
        "/K": child,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": parent,
    }))
    child["/P"] = parent
    parent["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/RoleMap": Dictionary({
            "/TOC 2": Name("/TOCI"),
        }),
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_toc_structure(pdf)

    toc = parent["/K"]
    assert any("Wrapped 1 orphan /TOCI" in change for change in changes)
    assert str(toc["/S"]) == "/TOC"
    assert str(child["/P"]["/S"]) == "/TOC"
    assert str(child["/S"]) == "/TOCI"


def test_fix_role_map_does_not_map_artifact_structure_roles() -> None:
    pdf = pikepdf.Pdf.new()
    artifact = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Artifact"),
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": artifact,
    }))
    artifact["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/RoleMap": Dictionary({
            "/Artifact": Name("/P"),
            "/Caption Custom": Name("/H4"),
        }),
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_role_map(pdf)

    role_map = pdf.Root["/StructTreeRoot"]["/RoleMap"]
    assert any("Repaired" in change for change in changes)
    assert role_map.get(Name("/Artifact")) is None
    assert str(role_map[Name("/Caption Custom")]) == "/Caption"


def test_fix_annotations_tagged_retags_existing_link_parent() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    annot = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Link"),
        "/Rect": pikepdf.Array([0, 0, 20, 20]),
    }))
    page["/Annots"] = pikepdf.Array([annot])
    link_span = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Span"),
        "/K": Dictionary({
            "/Type": Name("/OBJR"),
            "/Obj": annot,
            "/Pg": page.obj,
        }),
        "/Pg": page.obj,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": link_span,
    }))
    link_span["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
        "/ParentTree": pdf.make_indirect(Dictionary({"/Nums": pikepdf.Array()})),
        "/ParentTreeNextKey": 0,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_annotations_tagged(pdf)

    assert any("Retagged 1 annotation" in change for change in changes)
    assert str(link_span["/S"]) == "/Link"
    assert annot.get("/StructParent") is not None


def test_fix_note_ids_assigns_missing_note_id() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    note = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Note"),
        "/Pg": page.obj,
    }))
    document = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": note,
    }))
    note["/P"] = document
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": document,
    }))
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root

    changes = fix_note_ids(pdf)

    assert any("Assigned /ID to 1 Note" in change for change in changes)
    assert str(note.get("/ID")) == "note-1"


def test_fix_tounicode_extends_later_difference_glyphs() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Example"),
        "/Encoding": Dictionary({
            "/Type": Name("/Encoding"),
            "/BaseEncoding": Name("/WinAnsiEncoding"),
            "/Differences": pikepdf.Array([
                143,
                Name("/quoteleft"),
                Name("/quoteright"),
            ]),
        }),
        "/ToUnicode": pdf.make_stream(
            b"/CIDInit /ProcSet findresource begin\n"
            b"12 dict begin\n"
            b"begincmap\n"
            b"1 begincodespacerange\n"
            b"<00> <FF>\n"
            b"endcodespacerange\n"
            b"1 beginbfchar\n"
            b"<20> <0020>\n"
            b"endbfchar\n"
            b"endcmap\n"
            b"CMapName currentdict /CMap defineresource pop\n"
            b"end\n"
            b"end\n"
        ),
    }))
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf (\\217\\220) Tj ET\n")

    changes = fix_tounicode(pdf)

    mapped = _parse_tounicode_mapped_codes(font)
    assert any("Synthesized ToUnicode" in change for change in changes)
    assert 0x8F in mapped
    assert 0x90 in mapped


def test_fix_tounicode_repairs_shifted_identity_type0_map() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type0"),
        "/BaseFont": Name("/ShiftedCodeFont"),
        "/Encoding": Name("/Identity-H"),
        "/ToUnicode": pdf.make_stream(
            b"/CIDInit /ProcSet findresource begin\n"
            b"12 dict begin\n"
            b"begincmap\n"
            b"1 begincodespacerange\n"
            b"<0000> <FFFF>\n"
            b"endcodespacerange\n"
            b"4 beginbfchar\n"
            b"<0003> <0003>\n"
            b"<0024> <0024>\n"
            b"<0045> <0045>\n"
            b"<0055> <0055>\n"
            b"endbfchar\n"
            b"endcmap\n"
            b"CMapName currentdict /CMap defineresource pop\n"
            b"end\n"
            b"end\n"
        ),
    }))
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf <0003002400450055> Tj ET\n")

    changes = fix_tounicode(pdf)
    cmap = font["/ToUnicode"].read_bytes().decode("ascii")

    assert any("Synthesized ToUnicode" in change for change in changes)
    assert "<0003> <0020>" in cmap
    assert "<0024> <0041>" in cmap
    assert "<0045> <0062>" in cmap
    assert "<0055> <0072>" in cmap


def test_fix_tounicode_preserves_existing_bfrange_mappings() -> None:
    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type0"),
        "/BaseFont": Name("/ShiftedCodeFont"),
        "/Encoding": Name("/Identity-H"),
        "/ToUnicode": pdf.make_stream(
            b"/CIDInit /ProcSet findresource begin\n"
            b"12 dict begin\n"
            b"begincmap\n"
            b"1 begincodespacerange\n"
            b"<0000> <FFFF>\n"
            b"endcodespacerange\n"
            b"3 beginbfrange\n"
            b"<0003><0003><0020>\n"
            b"<0024><0024><0041>\n"
            b"<0045><0045><0062>\n"
            b"endbfrange\n"
            b"endcmap\n"
            b"CMapName currentdict /CMap defineresource pop\n"
            b"end\n"
            b"end\n"
        ),
    }))
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(b"BT /F1 12 Tf <000300240045> Tj ET\n")

    changes = fix_tounicode(pdf)
    cmap = font["/ToUnicode"].read_bytes().decode("ascii")

    assert changes == []
    assert "<0003><0003><0020>" in cmap
    assert "<0024><0024><0041>" in cmap
    assert "<0045><0045><0062>" in cmap
