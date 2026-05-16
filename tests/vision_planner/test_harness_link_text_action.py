from __future__ import annotations

import pikepdf

from project_remedy.pdf_checker import walk_structure_tree
from project_remedy.vision_planner.executor import (
    _do_rewrite_link_text,
    execute_plan,
)
from project_remedy.vision_planner.harness import VisionPlannerHarness


def test_harness_declares_rewrite_link_text_action() -> None:
    harness = VisionPlannerHarness()

    prompt = harness.build_planner_prompt({}, [], {"anchors": []})[0]["content"]

    assert "- rewrite_link_text:" in prompt
    assert "replacement_text for rewrite_link_text" in prompt
    assert "link text is present but non-descriptive" in prompt


def test_rewrite_link_text_sets_accessible_name_on_link_struct_elem() -> None:
    pdf, link = _pdf_with_struct_elem("Link")
    struct_elem_id = f"obj_{link.objgen[0]}_{link.objgen[1]}"

    results = _do_rewrite_link_text(
        pdf,
        0,
        [],
        {"replacement_text": "Download the annual accessibility report"},
        struct_elem_id=struct_elem_id,
        op_id="rewrite-link",
    )

    assert len(results) == 1
    assert results[0].status == "applied"
    assert str(link["/Alt"]) == "Download the annual accessibility report"
    assert str(link["/ActualText"]) == "Download the annual accessibility report"


def test_rewrite_link_text_skips_non_link_struct_elem() -> None:
    pdf, paragraph = _pdf_with_struct_elem("P")
    struct_elem_id = f"obj_{paragraph.objgen[0]}_{paragraph.objgen[1]}"

    results = _do_rewrite_link_text(
        pdf,
        0,
        [],
        {"replacement_text": "Download the annual accessibility report"},
        struct_elem_id=struct_elem_id,
        op_id="rewrite-link",
    )

    assert len(results) == 1
    assert results[0].status == "skipped"
    assert "/Alt" not in paragraph
    assert "/ActualText" not in paragraph


def test_rewrite_link_text_rejects_blank_replacement_text() -> None:
    pdf, link = _pdf_with_struct_elem("Link")
    struct_elem_id = f"obj_{link.objgen[0]}_{link.objgen[1]}"

    results = _do_rewrite_link_text(
        pdf,
        0,
        [],
        {"replacement_text": "   "},
        struct_elem_id=struct_elem_id,
        op_id="rewrite-link",
    )

    assert len(results) == 1
    assert results[0].status == "error"
    assert results[0].detail == "replacement_text must be a non-empty string"
    assert "/Alt" not in link
    assert "/ActualText" not in link


def test_execute_plan_dispatches_rewrite_link_text(tmp_path) -> None:
    pdf, _link = _pdf_with_struct_elem("Link")
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    pdf.save(input_path)
    pdf.close()
    struct_elem_id = _first_struct_elem_id(input_path, "Link")

    result = execute_plan(
        input_path,
        output_path,
        {
            "operations": [
                {
                    "op_id": "rewrite-link",
                    "action": "rewrite_link_text",
                    "target_anchors": ["a1"],
                    "replacement_text": "Download the annual accessibility report",
                }
            ]
        },
        {
            "anchors": [
                {
                    "anchor_id": "a1",
                    "page": 0,
                    "mcids": [],
                    "struct_elem_id": struct_elem_id,
                }
            ]
        },
    )

    assert result["errors"] == []
    assert [item["action"] for item in result["applied"]] == ["rewrite_link_text"]

    with pikepdf.open(output_path) as output_pdf:
        link_nodes = [
            node
            for node, _depth, _parent in walk_structure_tree(output_pdf)
            if str(node.get("/S", "")).lstrip("/") == "Link"
        ]
        assert len(link_nodes) == 1
        assert str(link_nodes[0]["/Alt"]) == "Download the annual accessibility report"
        assert (
            str(link_nodes[0]["/ActualText"])
            == "Download the annual accessibility report"
        )


def _first_struct_elem_id(pdf_path, struct_type: str) -> str:
    with pikepdf.open(pdf_path) as pdf:
        for node, _depth, _parent in walk_structure_tree(pdf):
            if str(node.get("/S", "")).lstrip("/") == struct_type:
                return f"obj_{node.objgen[0]}_{node.objgen[1]}"
    raise AssertionError(f"{struct_type} StructElem not found")


def _pdf_with_struct_elem(
    struct_type: str,
) -> tuple[pikepdf.Pdf, pikepdf.Dictionary]:
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(72, 72))
    node = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name(f"/{struct_type}"),
                "/K": pikepdf.Array(),
            }
        )
    )
    document = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Document"),
                "/K": pikepdf.Array([node]),
            }
        )
    )
    struct_root = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructTreeRoot"),
                "/K": document,
            }
        )
    )
    node["/P"] = document
    document["/P"] = struct_root
    pdf.Root["/StructTreeRoot"] = struct_root
    return pdf, node
