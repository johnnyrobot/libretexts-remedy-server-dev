"""Vision-driven STRUCTURE-TREE reading-order reorder.

The engine's deterministic reading-order fixes (XY-Cut++ geometry, within-parent
vision) cannot recover the intended reading order of designed multi-column pages
(career "Major Sheets", brochures): the correct order crosses struct-parent
boundaries, which the page-region pass declines, and the semantic pass requests a
full ``reading_order`` permutation from the vision model but discards it.

This module closes that gap. For each page it shows the rendered image + a
numbered list of the page's atomic tagged units to the vision model and asks for
the correct reading order as a permutation. The permutation is validated (must
cover every unit exactly once) and applied by REBUILDING the container's ``/K``
in that order — cross-parent — re-wrapping runs of list items in fresh ``/L``
and clamping heading levels so they never skip (PDF/UA-1 7.4.2).

Only existing element OBJECTS are moved (never recreated), so every MCID's
``/ParentTree`` entry, the content streams, fonts and tags stay valid — only the
logical ORDER changes. A struct-leaf-count integrity check aborts the rebuild if
it would drop content; pages with ``/Table`` structure and single-unit pages are
left untouched. Any invalid/garbled model output leaves that page's order as-is.

This is the engine-native port of the proven offline reorder; it is driven
through a provider-agnostic ``vision_fn`` so it uses the engine's own
``VisionProvider`` (see :func:`fix_struct_reading_order_vision`).
"""

from __future__ import annotations

import json
import logging
import re

import pikepdf

logger = logging.getLogger(__name__)

GROUPING = {"/Document", "/Part", "/Sect", "/Art", "/Div"}
LIST_WRAP = {"/L"}

PROMPT = (
    "This image is one PDF page. Below are its tagged content blocks, each a "
    "NUMBER and its text.\n\nBLOCKS:\n{listing}\n\n"
    "Output the correct reading order for a screen reader as JSON: "
    '{{"order": [numbers]}}.\n'
    "Requirements: include EVERY block number EXACTLY ONCE (a permutation). "
    "Title/main heading first; each section heading immediately followed by ITS "
    "OWN list items; read one full column top-to-bottom before moving to the "
    "next column; footer/boilerplate last. For a data table, read row by row. "
    "Output ONLY the JSON object."
)


# --------------------------------------------------------------------------- #
# struct-tree helpers (pure pikepdf)
# --------------------------------------------------------------------------- #
def _kids(n):
    if not isinstance(n, pikepdf.Dictionary) or "/K" not in n:
        return []
    k = n.get("/K")
    return list(k) if isinstance(k, pikepdf.Array) else [k]


def _is_mcid(it):
    if isinstance(it, int):
        return True
    try:
        if it.is_integer:
            return True
    except Exception:
        pass
    return isinstance(it, pikepdf.Dictionary) and str(it.get("/Type", "")) == "/MCR"


def _has_mcid(n):
    return any(_is_mcid(it) for it in _kids(n))


def _stype(n):
    return str(n.get("/S")) if (isinstance(n, pikepdf.Dictionary) and "/S" in n) else None


def _page_index_map(pdf):
    return {pg.obj.objgen: i for i, pg in enumerate(pdf.pages)}


def _count_leaves(root):
    """Total MCID-bearing struct elements reachable (integrity check)."""
    n = 0

    def walk(node):
        nonlocal n
        if isinstance(node, pikepdf.Dictionary) and _stype(node) and _has_mcid(node):
            n += 1
        for it in _kids(node):
            if isinstance(it, pikepdf.Dictionary):
                walk(it)

    walk(root)
    return n


def _node_page(n, pidx, inherited):
    if isinstance(n, pikepdf.Dictionary) and "/Pg" in n:
        try:
            return pidx.get(n["/Pg"].objgen, inherited)
        except Exception:
            return inherited
    return inherited


def _descend_to_container(pdf):
    """Lowest grouping element that holds the document content blocks."""
    node = pdf.Root.StructTreeRoot
    while True:
        gk = [c for c in _kids(node) if isinstance(c, pikepdf.Dictionary)]
        grouping = [c for c in gk if _stype(c) in GROUPING]
        if len(gk) == 1 and len(grouping) == 1:
            node = grouping[0]
            continue
        if _stype(node) is None and len(grouping) == 1:
            node = grouping[0]
            continue
        return node


def _find_page(elem, pidx, inherited):
    """Page of a unit = /Pg of itself or its first descendant that has one
    (/Pg usually lives on the leaf, not on /LI containers)."""
    if isinstance(elem, pikepdf.Dictionary) and "/Pg" in elem:
        try:
            return pidx.get(elem["/Pg"].objgen, inherited)
        except Exception:
            return inherited
    for it in _kids(elem):
        if isinstance(it, pikepdf.Dictionary):
            r = _find_page(it, pidx, None)
            if r is not None:
                return r
    return inherited


def _collect_units(container, pdf, pidx):
    """Walk container subtree; yield atomic units {elem, kind, page}.

    kind 'li'    -> a list item (/LI), moved whole.
    kind 'block' -> a content leaf (H*/P/Span/Figure/…) not inside an /LI.
    """
    units = []

    def walk(n, inherited_pg):
        s = _stype(n)
        pg = _node_page(n, pidx, inherited_pg)
        if s == "/LI":
            units.append({"elem": n, "kind": "li",
                          "page": _find_page(n, pidx, pg)})
            return
        if s and _has_mcid(n) and s not in LIST_WRAP:
            units.append({"elem": n, "kind": "block",
                          "page": _find_page(n, pidx, pg)})
            return
        for it in _kids(n):
            if isinstance(it, pikepdf.Dictionary):
                walk(it, pg)

    for it in _kids(container):
        if isinstance(it, pikepdf.Dictionary):
            walk(it, _node_page(container, pidx, None))
    return units


def _page_has_table(container, pidx, page_idx):
    found = [False]

    def walk(n, inh):
        pg = _node_page(n, pidx, inh)
        if _stype(n) == "/Table" and pg == page_idx:
            found[0] = True
        for it in _kids(n):
            if isinstance(it, pikepdf.Dictionary):
                walk(it, pg)

    walk(container, None)
    return found[0]


def _renormalize_headings(ordered_by_page):
    """Clamp heading levels in final reading order so they never skip down by
    >1 (PDF/UA-1 7.4.2). Returns count changed."""
    prev = 0
    changed = 0
    for page_idx in sorted(ordered_by_page):
        for u in ordered_by_page[page_idx]:
            s = str(u["elem"].get("/S")) if "/S" in u["elem"] else ""
            m = re.match(r"/H([1-6])$", s)
            if not m:
                continue
            lvl = int(m.group(1))
            new = max(1, min(lvl, prev + 1))
            if new != lvl:
                u["elem"]["/S"] = pikepdf.Name(f"/H{new}")
                changed += 1
            prev = new
    return changed


def _rebuild(container, pdf, ordered_by_page):
    """Rebuild container /K from page-ordered unit lists, re-wrapping LI runs."""
    new_k = pikepdf.Array()
    for page_idx in sorted(ordered_by_page):
        units = ordered_by_page[page_idx]
        i = 0
        while i < len(units):
            u = units[i]
            if u["kind"] == "li":
                run = [u]
                j = i + 1
                while j < len(units) and units[j]["kind"] == "li":
                    run.append(units[j])
                    j += 1
                lst = pdf.make_indirect(pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/L"),
                    "/P": container,
                    "/K": pikepdf.Array(),
                }))
                for li in run:
                    li["elem"]["/P"] = lst
                    lst["/K"].append(li["elem"])
                new_k.append(lst)
                i = j
            else:
                u["elem"]["/P"] = container
                new_k.append(u["elem"])
                i += 1
    container["/K"] = new_k


# --------------------------------------------------------------------------- #
# text extraction for unit labels (ToUnicode-aware; subset-font safe)
# --------------------------------------------------------------------------- #
def _parse_tounicode(stream_bytes):
    try:
        data = stream_bytes.decode("latin-1", "ignore")
    except Exception:
        return {}
    m = {}

    def utf16(hexstr):
        try:
            return bytes.fromhex(hexstr).decode("utf-16-be", "ignore")
        except Exception:
            return ""

    for blk in re.findall(r"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            try:
                m[int(src, 16)] = utf16(dst)
            except Exception:
                pass
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            try:
                l, h, base = int(lo, 16), int(hi, 16), int(dst, 16)
                for i, code in enumerate(range(l, h + 1)):
                    m[code] = chr(base + i) if base + i < 0x110000 else ""
            except Exception:
                pass
    return m


def _font_maps(page):
    maps = {}
    try:
        res = page.get("/Resources")
        fonts = res.get("/Font") if res and "/Font" in res else None
    except Exception:
        fonts = None
    if not fonts:
        return maps
    for key, font in fonts.items():
        try:
            tu = font.get("/ToUnicode")
            if tu is not None:
                maps[str(key)] = _parse_tounicode(tu.read_bytes())
        except Exception:
            pass
    return maps


def _decode(codes, fmap):
    if not fmap:
        return codes.decode("latin-1", "ignore")
    out, miss = [], 0
    for byte in codes:
        if byte in fmap:
            out.append(fmap[byte])
        else:
            miss += 1
            out.append("")
    if miss > len(codes) * 0.5 and len(codes) >= 2:
        out = []
        for i in range(0, len(codes) - 1, 2):
            out.append(fmap.get((codes[i] << 8) | codes[i + 1], ""))
    return "".join(out)


def page_narration(page):
    """mcid -> decoded text for one page (subset-font / ToUnicode aware)."""
    fmaps = _font_maps(page)
    cur_font = cur_mc = None
    buf, out = [], {}

    def flush():
        nonlocal cur_mc, buf
        if cur_mc is not None:
            out[cur_mc] = out.get(cur_mc, "") + "".join(buf)
        buf = []

    try:
        toks = pikepdf.parse_content_stream(page)
    except Exception:
        return {}
    for ins in toks:
        op = str(ins.operator)
        o = ins.operands
        if op == "Tf":
            try:
                cur_font = str(o[0])
            except Exception:
                cur_font = None
        elif op == "BDC":
            pr = o[1] if len(o) > 1 else None
            mc = None
            try:
                if pr is not None and "/MCID" in pr:
                    mc = int(pr["/MCID"])
            except Exception:
                mc = None
            if mc is not None:
                flush()
                cur_mc = mc
        elif op == "EMC":
            flush()
            cur_mc = None
        elif op in ("Tj", "'"):
            try:
                buf.append(_decode(bytes(o[0]), fmaps.get(cur_font, {})))
            except Exception:
                pass
        elif op == "TJ":
            for el in o[0]:
                if isinstance(el, pikepdf.String):
                    try:
                        buf.append(_decode(bytes(el), fmaps.get(cur_font, {})))
                    except Exception:
                        pass
    flush()
    return out


def _unit_text(u, mt):
    t = ""

    def walk(n):
        nonlocal t
        for it in _kids(n):
            if _is_mcid(it) and not t:
                mc = None
                if isinstance(it, int):
                    mc = it
                elif getattr(it, "is_integer", False):
                    mc = int(it)
                elif isinstance(it, pikepdf.Dictionary) and "/MCID" in it:
                    mc = int(it["/MCID"])
                if mc is not None and mc in mt:
                    t = mt[mc]
            elif isinstance(it, pikepdf.Dictionary):
                walk(it)

    walk(u["elem"])
    return re.sub(r"\s+", " ", t).strip()


# --------------------------------------------------------------------------- #
# vision permutation
# --------------------------------------------------------------------------- #
def _ask_order(vision_fn, image_path, labeled):
    listing = "\n".join(f"{num}. {t[:70] or '[blank]'}" for num, t in labeled)
    try:
        txt = vision_fn(image_path, PROMPT.format(listing=listing)) or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("vision reorder call failed: %s", exc)
        return None
    for cand in re.findall(r"\{.*?\}", txt, re.S) or re.findall(r"\{.*\}", txt, re.S):
        try:
            o = json.loads(cand)
            if isinstance(o.get("order"), list):
                return [int(x) for x in o["order"]]
        except Exception:
            continue
    return None


def _render_page(pdf_path, page_num, dpi):
    """Render 1-based *page_num* to an image path. Prefers the engine renderer;
    falls back to pdftoppm."""
    try:
        from project_remedy.pdf_vision import render_page_to_image
        p = render_page_to_image(str(pdf_path), page_num, dpi=dpi)
        if p:
            return str(p)
    except Exception:
        pass
    import subprocess
    import tempfile
    from pathlib import Path
    tmp = tempfile.NamedTemporaryFile(suffix="", delete=False)
    base = tmp.name
    tmp.close()
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page_num),
                    "-l", str(page_num), "-singlefile", str(pdf_path), base],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p = Path(base + ".png")
    return str(p) if p.exists() else None


def reorder_struct_vision(pdf, vision_fn, *, pdf_path=None, target_pages=None,
                          max_units=64, dpi=110):
    """Reorder the struct tree to the vision-derived reading order, in place.

    *vision_fn(image_path, prompt) -> str* performs the model call. *pdf_path*
    is the on-disk path used for rendering (defaults to ``pdf.filename``).
    Returns a report dict. A struct-leaf-count integrity check reverts the whole
    rebuild (by not saving — the caller decides) if content would be dropped;
    here we restore the original /K on integrity failure.
    """
    rep = {"pages_vision": 0, "pages_skipped": 0, "pages_table": 0,
           "changed": False, "notes": []}
    if "/StructTreeRoot" not in pdf.Root:
        return rep
    if pdf_path is None:
        pdf_path = getattr(pdf, "filename", None)
    if not pdf_path:
        rep["notes"].append("no pdf_path for rendering")
        return rep

    pidx = _page_index_map(pdf)
    container = _descend_to_container(pdf)
    original_k = container.get("/K")
    all_units = _collect_units(container, pdf, pidx)

    ordered_by_page = {}
    any_change = False
    for idx in range(len(pdf.pages)):
        pu = [u for u in all_units if u["page"] == idx]
        if not pu:
            continue
        if target_pages is not None and (idx + 1) not in target_pages:
            ordered_by_page[idx] = pu
            continue
        if _page_has_table(container, pidx, idx):
            rep["pages_table"] += 1
            ordered_by_page[idx] = pu
            continue
        if len(pu) < 3 or len(pu) > max_units:
            ordered_by_page[idx] = pu
            rep["pages_skipped"] += 1
            continue
        mt = page_narration(pdf.pages[idx])
        labeled = [(i + 1, _unit_text(u, mt) or f"[{u['kind']}]")
                   for i, u in enumerate(pu)]
        image_path = _render_page(pdf_path, idx + 1, dpi)
        order = _ask_order(vision_fn, image_path, labeled) if image_path else None
        if order and sorted(order) == list(range(1, len(pu) + 1)):
            new = [pu[i - 1] for i in order]
            ordered_by_page[idx] = new
            rep["pages_vision"] += 1
            if [id(u["elem"]) for u in new] != [id(u["elem"]) for u in pu]:
                any_change = True
        else:
            ordered_by_page[idx] = pu
            rep["pages_skipped"] += 1

    rep["changed"] = any_change
    if not any_change:
        return rep
    before = _count_leaves(pdf.Root.StructTreeRoot)
    hc = _renormalize_headings(ordered_by_page)
    if hc:
        rep["notes"].append(f"renormalized {hc} heading levels")
    _rebuild(container, pdf, ordered_by_page)
    after = _count_leaves(pdf.Root.StructTreeRoot)
    if after != before:
        if original_k is not None:
            container["/K"] = original_k   # integrity failure -> restore
        rep["changed"] = False
        rep["notes"].append(f"ABORTED: leaf count {before}->{after}")
    return rep


def _provider_vision_fn(vision_provider):
    """Adapt the engine's VisionProvider.analyze_image (async) to a blocking
    ``vision_fn(image_path, prompt) -> str``."""
    from pathlib import Path

    def fn(image_path, prompt):
        try:
            from project_remedy.pdf_fixer import _run_async_callable_blocking
            return _run_async_callable_blocking(
                vision_provider.analyze_image, Path(image_path), prompt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("provider vision_fn failed: %s", exc)
            return ""

    return fn


def fix_struct_reading_order_vision(pdf, vision_provider=None, *,
                                    thorough=False) -> list:
    """fix_all-compatible wrapper: vision-driven cross-parent struct reorder.

    Runs only when a *vision_provider* is supplied. Returns a list of
    human-readable change messages.
    """
    if vision_provider is None:
        return []
    try:
        vision_fn = _provider_vision_fn(vision_provider)
        rep = reorder_struct_vision(pdf, vision_fn)
    except Exception as exc:  # never abort remediation
        logger.warning("vision struct reorder failed: %s", exc)
        return []
    if rep.get("changed"):
        note = f"; {'; '.join(rep['notes'])}" if rep.get("notes") else ""
        return [f"Reordered structure-tree reading order on {rep['pages_vision']} "
                f"page(s) via vision-driven cross-parent ordering{note}"]
    return []
