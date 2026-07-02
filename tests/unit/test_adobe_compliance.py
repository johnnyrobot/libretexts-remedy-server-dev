"""Tests for the Adobe-compliance post-pass (src/project_remedy/adobe_compliance.py).

Builds synthetic PDFs whose StructElem shapes mirror the residual Acrobat-checker
failures seen on the LAMC corpus, then asserts the pass rewrites them into the
shape Adobe accepts — and is idempotent.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name, String

from project_remedy.adobe_compliance import (
    ComplianceCounts,
    apply_compliance_pass,
    process_directory,
)


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _write_pdf(path: Path, elems: list[Dictionary]) -> None:
    """Save a one-page PDF whose StructTreeRoot references *elems*."""
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    kids = Array([pdf.make_indirect(e) for e in elems])
    pdf.Root.StructTreeRoot = pdf.make_indirect(
        Dictionary(Type=Name("/StructTreeRoot"), K=kids)
    )
    pdf.Root.MarkInfo = Dictionary(Marked=True)
    pdf.save(str(path))
    pdf.close()


def _key(node):
    """objgen identity for indirect objects, id() fallback for inline — mirrors
    the module's _obj_key so shared/indirect nodes are deduped faithfully."""
    try:
        og = node.objgen
        if og and og[0] != 0:
            return og
    except Exception:
        pass
    return ("id", id(node))


def _snapshot(path: Path) -> list[dict]:
    """Capture the relevant keys of every structure element as plain dicts.

    Walks the StructTree keyed on ``/S`` (not ``/Type``) so it sees elements that
    omit the optional ``/Type`` key AND inline (direct) elements — i.e. exactly
    what the pass itself processes."""
    rows: list[dict] = []
    with pikepdf.open(path) as pdf:
        root = pdf.Root.get("/StructTreeRoot")
        seen: set = set()
        stack = [(root, 0)] if root is not None else []
        while stack:
            node, depth = stack.pop()
            if not isinstance(node, Dictionary) or depth > 1000 or _key(node) in seen:
                continue
            seen.add(_key(node))
            if "/S" in node:
                a = node.get("/A")
                rows.append(
                    {
                        "S": str(node.get("/S", "")),
                        "has_alt": "/Alt" in node,
                        "has_actualtext": "/ActualText" in node,
                        "has_e": "/E" in node,
                        "has_summary_key": "/Summary" in node,
                        "a_o": str(a.get("/O", "")) if isinstance(a, Dictionary) else None,
                        "a_summary": str(a.get("/Summary", "")) if isinstance(a, Dictionary) else None,
                    }
                )
            k = node.get("/K")
            items = k if isinstance(k, Array) else ([k] if k is not None else [])
            for child in items:
                stack.append((child, depth + 1))
    return rows


def _first(path: Path, s: str) -> dict:
    """First snapshot row whose structure type is *s* (e.g. '/Table')."""
    return next(r for r in _snapshot(path) if r["S"] == s)


def _table_A_info(path: Path) -> dict:
    """Inspect the first /Table's /A entry: owners, summary, layout survival."""
    with pikepdf.open(path) as pdf:
        root = pdf.Root.get("/StructTreeRoot")
        seen: set = set()
        stack = [root]
        while stack:
            node = stack.pop()
            if not isinstance(node, Dictionary) or _key(node) in seen:
                continue
            seen.add(_key(node))
            if str(node.get("/S", "")) == "/Table":
                a = node.get("/A")
                owners = [a] if isinstance(a, Dictionary) else (
                    [m for m in a if isinstance(m, Dictionary)] if isinstance(a, Array) else []
                )
                return {
                    "a_is_array": isinstance(a, Array),
                    "owners": [str(o.get("/O", "")) for o in owners],
                    "has_layout": any(str(o.get("/O", "")) == "/Layout" for o in owners),
                    "table_summary": next(
                        (str(o.get("/Summary", "")) for o in owners
                         if str(o.get("/O", "")) == "/Table" and "/Summary" in o), None),
                    "direct_summary": "/Summary" in node,
                    "direct_actualtext": "/ActualText" in node,
                }
            k = node.get("/K")
            for c in (k if isinstance(k, Array) else ([k] if k is not None else [])):
                stack.append(c)
    return {}


def _write_pdf_all_indirect(path: Path, build) -> None:
    """Save a one-page PDF whose StructTree is built by *build(pdf)* -> top node,
    with EVERY struct node made indirect (mirrors the real corpus, where child
    struct elements are always indirect — exercises the objgen dedup path)."""
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    top = build(pdf)
    pdf.Root.StructTreeRoot = pdf.make_indirect(Dictionary(Type=Name("/StructTreeRoot"), K=Array([top])))
    pdf.Root.MarkInfo = Dictionary(Marked=True)
    pdf.save(str(path))
    pdf.close()


def _figure(**extra) -> Dictionary:
    return Dictionary(Type=Name("/StructElem"), S=Name("/Figure"), **extra)


def _table(**extra) -> Dictionary:
    return Dictionary(Type=Name("/StructElem"), S=Name("/Table"), **extra)


def _figure_no_type(**extra) -> Dictionary:
    """A figure StructElem that OMITS the optional /Type key."""
    return Dictionary(S=Name("/Figure"), **extra)


def _table_no_type(**extra) -> Dictionary:
    """A table StructElem that OMITS the optional /Type key."""
    return Dictionary(S=Name("/Table"), **extra)


def _tr_child() -> Array:
    """A /K value that counts as real content (a child TR StructElem)."""
    return Array([Dictionary(Type=Name("/StructElem"), S=Name("/TR"))])


def _objr_child() -> Array:
    """A /K value wrapping an annotation reference."""
    return Array([Dictionary(Type=Name("/OBJR"))])


# --------------------------------------------------------------------------- #
# orphan alt text ("Associated with content")                                 #
# --------------------------------------------------------------------------- #
def test_orphan_alt_on_contentless_elem_is_stripped(tmp_path: Path):
    p = tmp_path / "orphan.pdf"
    # No /K → contentless → all three alt keys are orphans.
    _write_pdf(p, [_figure(Alt=String("x"), ActualText=String("y"), E=String("z"))])

    counts = apply_compliance_pass(p)

    assert counts.orphan_attrs == 3
    assert counts.tables_normalized == 0
    assert counts.hides_annotation == 0
    row = _first(p, "/Figure")
    assert not row["has_alt"] and not row["has_actualtext"] and not row["has_e"]


def test_alt_on_elem_with_content_is_preserved(tmp_path: Path):
    p = tmp_path / "content.pdf"
    # /K = 0 is a marked-content id → real content → alt text is legitimate.
    _write_pdf(p, [_figure(Alt=String("a real description"), K=0)])

    counts = apply_compliance_pass(p)

    assert counts.total == 0
    assert _first(p, "/Figure")["has_alt"] is True


# --------------------------------------------------------------------------- #
# table summary                                                               #
# --------------------------------------------------------------------------- #
def test_table_summary_key_moved_into_attribute_dict(tmp_path: Path):
    p = tmp_path / "table_summary.pdf"
    _write_pdf(p, [_table(Summary=String("Quarterly enrollment"), K=_tr_child())])

    counts = apply_compliance_pass(p)

    assert counts.tables_normalized == 1
    row = _first(p, "/Table")
    assert row["has_summary_key"] is False  # no bare /Summary key left
    assert row["a_o"] == "/Table"
    assert row["a_summary"] == "Quarterly enrollment"


def test_table_alt_used_as_summary_when_no_summary_key(tmp_path: Path):
    p = tmp_path / "table_alt.pdf"
    _write_pdf(p, [_table(Alt=String("Fees by term"), K=_tr_child())])

    apply_compliance_pass(p)

    row = _first(p, "/Table")
    assert row["has_alt"] is False
    assert row["a_summary"] == "Fees by term"


def test_bare_table_gets_generic_summary(tmp_path: Path):
    p = tmp_path / "table_bare.pdf"
    _write_pdf(p, [_table(K=_tr_child())])

    counts = apply_compliance_pass(p)

    assert counts.tables_normalized == 1
    assert _first(p, "/Table")["a_summary"] == "Data table"


# --------------------------------------------------------------------------- #
# array-form /A (ISO 32000 allows /A to be an array of attribute owners)        #
# --------------------------------------------------------------------------- #
def test_array_A_with_existing_table_summary_is_left_alone(tmp_path: Path):
    """A table whose summary already lives in an array-form /A (alongside a
    /Layout owner) must be recognized as canonical and NOT clobbered."""
    p = tmp_path / "array_canonical.pdf"
    a = Array([
        Dictionary(O=Name("/Layout"), Placement=Name("/Block")),
        Dictionary(O=Name("/Table"), Summary=String("Enrollment by term, 2019-2023")),
    ])
    _write_pdf(p, [_table(A=a, K=_tr_child())])

    counts = apply_compliance_pass(p)

    assert counts.tables_normalized == 0  # already canonical -> no-op
    info = _table_A_info(p)
    assert info["table_summary"] == "Enrollment by term, 2019-2023"  # real summary preserved
    assert info["has_layout"] is True                                # /Layout owner survives


def test_array_A_layout_plus_bare_summary_moves_summary_keeping_layout(tmp_path: Path):
    """A table with a /Layout owner in array /A and a BARE /Summary key: the
    summary moves into a /Table owner in the array; the /Layout owner survives."""
    p = tmp_path / "array_move.pdf"
    a = Array([Dictionary(O=Name("/Layout"), Placement=Name("/Block"))])
    _write_pdf(p, [_table(A=a, Summary=String("Fees by program"), K=_tr_child())])

    counts = apply_compliance_pass(p)

    assert counts.tables_normalized == 1
    info = _table_A_info(p)
    assert info["direct_summary"] is False
    assert info["has_layout"] is True               # layout NOT destroyed
    assert "/Table" in info["owners"]
    assert info["table_summary"] == "Fees by program"


def test_table_actualtext_used_as_summary_and_stripped(tmp_path: Path):
    """A table carrying its description in /ActualText: text is used as the
    summary and the stray /ActualText key is removed."""
    p = tmp_path / "table_actualtext.pdf"
    _write_pdf(p, [_table(ActualText=String("Scores by section"), K=_tr_child())])

    apply_compliance_pass(p)

    info = _table_A_info(p)
    assert info["table_summary"] == "Scores by section"
    assert info["direct_actualtext"] is False


# --------------------------------------------------------------------------- #
# indirect-children path (what the real corpus uses; objgen dedup branch)       #
# --------------------------------------------------------------------------- #
def test_indirect_table_under_sect_is_normalized_and_idempotent(tmp_path: Path):
    """Mirror the corpus: all struct nodes indirect, table nested under a /Sect.
    Exercises the objgen dedup branch (not the inline id() fallback)."""
    p = tmp_path / "indirect.pdf"

    def build(pdf):
        tr = pdf.make_indirect(Dictionary(S=Name("/TR")))
        table = pdf.make_indirect(Dictionary(S=Name("/Table"), Summary=String("Indirect tbl"), K=Array([tr])))
        return pdf.make_indirect(Dictionary(S=Name("/Sect"), K=Array([table])))

    _write_pdf_all_indirect(p, build)

    first = apply_compliance_pass(p)
    assert first.tables_normalized == 1
    assert _first(p, "/Table")["a_summary"] == "Indirect tbl"

    second = apply_compliance_pass(p)
    assert second == ComplianceCounts()  # idempotent on the indirect path too


# --------------------------------------------------------------------------- #
# /Type-less structure elements (regression for the original script's bug)     #
# --------------------------------------------------------------------------- #
def test_type_less_table_is_normalized(tmp_path: Path):
    """A /Table that omits /Type /StructElem must still be fixed (this was the
    bug: the corpus omits /Type, so /Type-only filtering skipped these and left
    a bare /Summary key that Adobe rejects)."""
    p = tmp_path / "typeless_table.pdf"
    _write_pdf(p, [_table_no_type(Summary=String("Schedule grid"), K=_tr_child())])

    counts = apply_compliance_pass(p)

    assert counts.tables_normalized == 1
    row = _first(p, "/Table")
    assert row["has_summary_key"] is False
    assert row["a_o"] == "/Table"
    assert row["a_summary"] == "Schedule grid"


def test_type_less_orphan_alt_is_stripped(tmp_path: Path):
    p = tmp_path / "typeless_orphan.pdf"
    _write_pdf(p, [_figure_no_type(Alt=String("x"), ActualText=String("y"))])

    counts = apply_compliance_pass(p)

    assert counts.orphan_attrs == 2
    row = _first(p, "/Figure")
    assert not row["has_alt"] and not row["has_actualtext"]


def test_type_less_nested_table_under_section_is_reached(tmp_path: Path):
    """Tables nested below a /Sect (also /Type-less) must be reached by the
    tree walk, not just top-level elements."""
    p = tmp_path / "nested.pdf"
    sect = Dictionary(
        S=Name("/Sect"),
        K=Array([Dictionary(S=Name("/Table"), Summary=String("Nested"), K=_tr_child())]),
    )
    _write_pdf(p, [sect])

    counts = apply_compliance_pass(p)

    assert counts.tables_normalized == 1
    assert _first(p, "/Table")["a_summary"] == "Nested"


# --------------------------------------------------------------------------- #
# hides annotation                                                            #
# --------------------------------------------------------------------------- #
def test_alt_stripped_when_subtree_wraps_annotation(tmp_path: Path):
    p = tmp_path / "hides.pdf"
    _write_pdf(p, [_figure(Alt=String("button"), K=_objr_child())])

    counts = apply_compliance_pass(p)

    assert counts.hides_annotation == 1
    # OBJR counts as content, so the orphan path must NOT also fire.
    assert counts.orphan_attrs == 0
    assert _first(p, "/Figure")["has_alt"] is False


# --------------------------------------------------------------------------- #
# nested alternate text                                                        #
# --------------------------------------------------------------------------- #
def test_non_leaf_figure_is_retagged_to_div(tmp_path: Path):
    """A /Figure with child struct elements is mis-typed: it must be retagged to
    /Div with alt dropped (clears BOTH 'nested alt' and 'figure needs alt').
    The leaf child figure keeps its own alt."""
    p = tmp_path / "nonleaf_fig.pdf"
    container = _figure(
        Alt=String("container caption"),
        K=Array([Dictionary(S=Name("/Figure"), Alt=String("leaf child alt"), K=0)]),
    )
    _write_pdf(p, [container])

    counts = apply_compliance_pass(p)

    assert counts.figures_retagged == 1
    assert counts.nested_alt == 0
    # parent is now a /Div with no alt; there is no /Figure parent anymore
    div = _first(p, "/Div")
    assert div["has_alt"] is False
    # the leaf child figure survives WITH its alt
    leaf = _first(p, "/Figure")
    assert leaf["has_alt"] is True


def test_non_leaf_non_figure_loses_alt_but_keeps_type(tmp_path: Path):
    """A non-figure non-leaf element (e.g. /Span) just loses its nested alt; it is
    NOT retagged (no 'requires alt' rule applies to it)."""
    p = tmp_path / "nonleaf_span.pdf"
    span = Dictionary(
        Type=Name("/StructElem"), S=Name("/Span"),
        Alt=String("nested span alt"),
        K=Array([Dictionary(S=Name("/Span"), K=0)]),
    )
    _write_pdf(p, [span])

    counts = apply_compliance_pass(p)

    assert counts.nested_alt == 1
    assert counts.figures_retagged == 0
    parent = next(r for r in _snapshot(p) if r["S"] == "/Span" and not r["has_alt"])
    assert parent["has_alt"] is False


def test_leaf_figure_keeps_alt(tmp_path: Path):
    """A leaf figure (no child struct elements) must KEEP its alt text."""
    p = tmp_path / "leaf.pdf"
    _write_pdf(p, [_figure(Alt=String("a photo of campus"), K=0)])  # MCID content, no children

    counts = apply_compliance_pass(p)

    assert counts.nested_alt == 0
    assert counts.total == 0
    assert _first(p, "/Figure")["has_alt"] is True


# --------------------------------------------------------------------------- #
# idempotency                                                                 #
# --------------------------------------------------------------------------- #
def test_second_pass_is_a_noop(tmp_path: Path):
    p = tmp_path / "mixed.pdf"
    _write_pdf(
        p,
        [
            _figure(Alt=String("x"), ActualText=String("y"), E=String("z")),  # orphan
            _table(Summary=String("S"), K=_tr_child()),                        # table
            _figure(Alt=String("btn"), K=_objr_child()),                       # hides-annot
        ],
    )

    first = apply_compliance_pass(p)
    assert first.total > 0

    second = apply_compliance_pass(p)
    assert second == ComplianceCounts()  # nothing left to fix


def test_second_pass_noop_with_nested_alt_and_multiple_tables(tmp_path: Path):
    """Idempotency on the most complex shape: two tables + a non-leaf figure
    (retag) + a non-leaf span (nested alt) in one document."""
    p = tmp_path / "complex.pdf"
    _write_pdf(
        p,
        [
            _table(Summary=String("T1"), K=_tr_child()),
            _table(Alt=String("T2"), K=_tr_child()),
            _figure(Alt=String("container"), K=Array([Dictionary(S=Name("/Figure"), K=0)])),
            Dictionary(Type=Name("/StructElem"), S=Name("/Span"),
                       Alt=String("nested"), K=Array([Dictionary(S=Name("/Span"), K=0)])),
        ],
    )

    first = apply_compliance_pass(p)
    assert first.tables_normalized == 2
    assert first.figures_retagged == 1
    assert first.nested_alt == 1

    second = apply_compliance_pass(p)
    assert second == ComplianceCounts()


# --------------------------------------------------------------------------- #
# dry-run                                                                     #
# --------------------------------------------------------------------------- #
def test_dry_run_counts_but_does_not_modify(tmp_path: Path):
    p = tmp_path / "dry.pdf"
    _write_pdf(p, [_figure(Alt=String("x"), ActualText=String("y"), E=String("z"))])
    before = _snapshot(p)

    counts = apply_compliance_pass(p, dry_run=True)

    assert counts.orphan_attrs == 3        # it *would* fix 3
    assert _snapshot(p) == before          # ...but the file is untouched


# --------------------------------------------------------------------------- #
# directory processing + error resilience                                     #
# --------------------------------------------------------------------------- #
def test_process_directory_aggregates_and_survives_bad_files(tmp_path: Path):
    _write_pdf(tmp_path / "a.pdf", [_figure(Alt=String("x"))])  # 1 orphan
    _write_pdf(tmp_path / "b.pdf", [_table(K=_tr_child())])     # 1 table
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.7 not really a pdf")

    result = process_directory(tmp_path)

    assert result.files == 2
    assert result.errors == 1
    assert result.error_files == ["broken.pdf"]
    assert result.counts.orphan_attrs == 1
    assert result.counts.tables_normalized == 1


def test_counts_addition():
    a = ComplianceCounts(orphan_attrs=1, tables_normalized=2, hides_annotation=3)
    b = ComplianceCounts(orphan_attrs=10, tables_normalized=20, hides_annotation=30)
    assert (a + b) == ComplianceCounts(orphan_attrs=11, tables_normalized=22, hides_annotation=33)
    assert (a + b).total == 66
