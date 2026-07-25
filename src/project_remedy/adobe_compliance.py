"""Adobe-compliance post-pass — deterministic Acrobat-checker fixes.

Clears the *structural* Acrobat / PDF-UA checks that the LLM + veraPDF
remediation pipeline leaves behind, without re-running any model. Adobe's
checker keys off the exact PDF object *shape*; the engine's own fixers target
veraPDF clauses and produce a shape Adobe still rejects, so these residuals
survive to the Adobe report. This pass rewrites them into the shape Adobe wants.

Structure elements are found by walking the ``/StructTreeRoot`` hierarchy and
keying on ``/S`` (structure type), NOT on the optional ``/Type /StructElem`` key.
Much of this corpus omits ``/Type`` on its struct elements; a ``/Type``-only
filter silently skips them (this was the original scratchpad script's bug — it
left ``/Type``-less tables with a bare ``/Summary`` key that Adobe rejects).

Fixes (all idempotent — a second run is a no-op):

  * **Associated with content** — orphan ``/Alt`` / ``/ActualText`` / ``/E`` on a
    StructElem that wraps no marked content (no ``/K``, or ``/K`` empty) → strip
    those keys. Adobe fails alt text that "will never be read".
  * **Hides annotation** — ``/Alt`` on a StructElem whose subtree wraps an
    annotation (``/OBJR``) → strip ``/Alt`` so the annotation's own accessible
    name is exposed.
  * **Nested alternate text** — ``/Alt`` on a non-leaf element (one that has its
    own child structure elements) → strip ``/Alt``. Adobe never reads alt on a
    non-leaf ("alternate text that will never be read"); the children carry the
    content. Leaf figures keep their alt.
  * **Non-leaf figure** — a ``/Figure`` that has child structure elements is a
    catch-22 (keep alt → "nested alt"; drop alt → "figure needs alt"), because a
    figure must be atomic. Retag ``/S`` to ``/Div`` (a generic grouping element)
    and drop ``/Alt`` — this clears BOTH checks. Leaf figures are untouched.
  * **Summary** — a table description stored as a bare ``/Summary`` or ``/Alt``
    key on the Table StructElem (or absent entirely) → normalize into the ``/A``
    attribute dictionary ``{/O /Table /Summary ...}``, injecting a generic
    ``"Data table"`` summary when none exists. Adobe only reads the summary from
    the ``/A`` attribute dict with ``/O == /Table``.

NOT fixable here: **Character encoding** (font ToUnicode) failures. Those are a
font-embedding problem requiring the font-rebuild tier — see
``HANDOFF_simple_font_replacement.md`` and ``levels.is_font_clause_only``.
Logical-reading-order and color-contrast are Adobe "needs manual check" items
and can never auto-pass.

See ``RESEARCH_remedy_server_ADA_refactor.md`` for the level taxonomy this
supports (it clears L3→L4 structural residue; it does not assign L5).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pikepdf
from pikepdf import Array, Dictionary, Name, String

logger = logging.getLogger(__name__)

#: Keys that constitute "alternate text" on a StructElem. Orphaned (i.e. on a
#: contentless element) they trip Adobe's "Associated with content" check.
_ALT_KEYS = ("/Alt", "/ActualText", "/E")

#: Generic table summary injected when a Table StructElem has none. Adobe's
#: "Summary" check only requires a non-empty summary; it does not grade quality.
_GENERIC_TABLE_SUMMARY = "Data table"

#: Direct keys on a Table StructElem that may carry its description. We move the
#: text into the /A /Table owner and strip these so Adobe reads it from /A.
_TABLE_DESC_KEYS = ("/Summary", "/Alt", "/ActualText", "/E")

#: Cap on recursion when scanning a StructElem subtree for an annotation.
_OBJR_SCAN_MAX_DEPTH = 6

#: Depth bound for the structure-tree walk. Cycle safety comes from the visited
#: set (keyed on object identity), not this cap; it only guards pathological
#: depth. The deepest tree observed in the corpus is ~21, far below this.
_TREE_WALK_MAX_DEPTH = 1000


@dataclass(frozen=True)
class ComplianceCounts:
    """How many of each fix were applied to one document."""

    orphan_attrs: int = 0          # /Alt//ActualText//E keys stripped from contentless elems
    tables_normalized: int = 0     # Table StructElems moved to canonical /A summary shape
    hides_annotation: int = 0      # /Alt stripped from elements that wrap an annotation
    nested_alt: int = 0            # /Alt stripped from non-leaf non-figure elements (never read)
    figures_retagged: int = 0      # non-leaf /Figure retagged to /Div (+ /Alt dropped)

    @property
    def total(self) -> int:
        return (
            self.orphan_attrs + self.tables_normalized + self.hides_annotation
            + self.nested_alt + self.figures_retagged
        )

    def __add__(self, other: "ComplianceCounts") -> "ComplianceCounts":
        return ComplianceCounts(
            orphan_attrs=self.orphan_attrs + other.orphan_attrs,
            tables_normalized=self.tables_normalized + other.tables_normalized,
            hides_annotation=self.hides_annotation + other.hides_annotation,
            nested_alt=self.nested_alt + other.nested_alt,
            figures_retagged=self.figures_retagged + other.figures_retagged,
        )


def _has_content(node: Dictionary) -> bool:
    """True if a StructElem wraps real content (marked content / annotation /
    child StructElem) and therefore legitimately carries alt text."""
    k = node.get("/K")
    if k is None:
        return False

    def is_content(x: object) -> bool:
        # A non-dict child (e.g. an integer MCID) is marked content.
        if not isinstance(x, Dictionary):
            return True
        # A dict child is content if it is a marked-content / object reference,
        # or a nested StructElem (identified by its /S structure type).
        return str(x.get("/Type", "")) in ("/MCR", "/OBJR") or "/S" in x

    if isinstance(k, Array):
        return len(k) > 0 and any(is_content(x) for x in k)
    return is_content(k)


def _has_child_struct_elem(node: Dictionary) -> bool:
    """True if a StructElem has at least one *child structure element* (a /K child
    that is itself a struct elem, identified by /S). Such a node is a non-leaf, so
    any ``/Alt`` on it is 'nested' and never read by Adobe."""
    k = node.get("/K")
    items = k if isinstance(k, Array) else ([k] if k is not None else [])
    return any(isinstance(x, Dictionary) and "/S" in x for x in items)


def _subtree_has_objr(node: object, depth: int = 0) -> bool:
    """True if *node*'s ``/K`` subtree contains an annotation reference (/OBJR)."""
    if depth > _OBJR_SCAN_MAX_DEPTH or not isinstance(node, Dictionary):
        return False
    k = node.get("/K")
    items = k if isinstance(k, Array) else ([k] if k is not None else [])
    for x in items:
        if isinstance(x, Dictionary):
            if str(x.get("/Type", "")) == "/OBJR":
                return True
            if _subtree_has_objr(x, depth + 1):
                return True
    return False


def _a_owners(a: object) -> list[Dictionary]:
    """The attribute-owner dicts inside an /A entry, which may be a single dict or
    an ARRAY of dicts (ISO 32000-1 §14.7.5.2 permits both)."""
    if isinstance(a, Dictionary):
        return [a]
    if isinstance(a, Array):
        return [m for m in a if isinstance(m, Dictionary)]
    return []


def _a_table_summary(a: object) -> str | None:
    """The /Summary text from the /O == /Table owner inside /A (dict or array), or None."""
    for owner in _a_owners(a):
        if str(owner.get("/O", "")) == "/Table":
            s = str(owner.get("/Summary", "")).strip()
            if s:
                return s
    return None


def _table_is_canonical(elem: Dictionary) -> bool:
    """True if a Table StructElem already has the exact shape Adobe wants: a
    non-empty summary inside the ``/A`` ``/O == /Table`` owner (dict OR array
    form) and no stray direct description keys. Keeps the pass idempotent and —
    crucially — avoids re-normalizing (and clobbering) a table whose summary
    already lives in an array-form /A alongside other owners (e.g. /Layout)."""
    if any(k in elem for k in _TABLE_DESC_KEYS):
        return False
    return _a_table_summary(elem.get("/A")) is not None


def _set_table_summary(pdf: pikepdf.Pdf, elem: Dictionary, txt: str) -> None:
    """Write *txt* into the /A /Table owner's /Summary, PRESERVING any other
    attribute owners (array form) instead of overwriting the whole /A entry."""
    a = elem.get("/A")
    if isinstance(a, Array):
        for owner in a:
            if isinstance(owner, Dictionary) and str(owner.get("/O", "")) == "/Table":
                owner["/Summary"] = String(txt)
                return
        a.append(pdf.make_indirect(Dictionary(O=Name("/Table"), Summary=String(txt))))
        return
    if isinstance(a, Dictionary):
        if str(a.get("/O", "")) == "/Table":
            a["/Summary"] = String(txt)
        else:
            # Existing non-table owner dict: keep it, add a /Table owner alongside.
            elem["/A"] = Array([a, pdf.make_indirect(Dictionary(O=Name("/Table"), Summary=String(txt)))])
        return
    elem["/A"] = pdf.make_indirect(Dictionary(O=Name("/Table"), Summary=String(txt)))


def _normalize_table(pdf: pikepdf.Pdf, elem: Dictionary) -> None:
    """Move a Table StructElem's description into the canonical /A /Table summary,
    preserving other /A owners. Sources the text from any direct description key
    or an existing /A summary; falls back to a generic summary if none exists."""
    txt = None
    for key in _TABLE_DESC_KEYS:
        if key in elem:
            cand = str(elem[key]).strip()
            if cand:
                txt = cand
                break
    if not txt:
        txt = _a_table_summary(elem.get("/A"))

    for key in _TABLE_DESC_KEYS:
        if key in elem:
            del elem[key]

    if not (txt and txt.strip()):
        txt = _GENERIC_TABLE_SUMMARY

    _set_table_summary(pdf, elem, txt)


def _obj_key(node: object) -> object:
    """A stable identity for de-duping struct elements during the tree walk
    (shared subtrees can reach the same indirect object twice).

    Indirect objects key on their ``(objnum, gen)``; direct/inline objects (rare
    for struct elements) fall back to Python ``id`` — good enough since inline
    objects have exactly one parent and cannot form cycles."""
    try:
        og = node.objgen  # type: ignore[attr-defined]
        if og and og[0] != 0:
            return og
    except Exception:  # noqa: BLE001 - direct objects have no objgen
        pass
    return ("id", id(node))


def _collect_struct_elems(pdf: pikepdf.Pdf) -> list[Dictionary]:
    """Return every *live* structure element, deduped.

    Walks the ``/StructTreeRoot`` ``/K`` hierarchy and collects each node that
    carries an ``/S`` (structure type) key — with OR without the optional
    ``/Type /StructElem`` key (omitting ``/Type`` is the common case in this
    corpus and the original ``/Type``-only filter's bug).

    Only the live tree is traversed: Adobe reads accessibility from the structure
    tree, so disconnected/superseded StructElem objects left in ``pdf.objects`` by
    earlier rewrites are intentionally NOT processed (editing them has no effect
    on the report and only inflates counts).
    """
    collected: dict[object, Dictionary] = {}
    root = pdf.Root.get("/StructTreeRoot")
    if root is None:
        return []

    visited: set[object] = set()
    stack: list[tuple[object, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, Dictionary) or depth > _TREE_WALK_MAX_DEPTH:
            continue
        key = _obj_key(node)
        if key in visited:  # shared subtree / cycle guard
            continue
        visited.add(key)
        if "/S" in node:  # structure element (with or without /Type)
            collected.setdefault(key, node)
        k = node.get("/K")
        items = k if isinstance(k, Array) else ([k] if k is not None else [])
        for child in items:
            stack.append((child, depth + 1))

    return list(collected.values())


def _fix_in_memory(pdf: pikepdf.Pdf) -> ComplianceCounts:
    """Apply all fixes to an open PDF. Pure mutation; does not save."""
    orphan = tables = hann = nested = retagged = 0

    # Collect first, then mutate — never mutate while traversing.
    for obj in _collect_struct_elems(pdf):
        # 1) Tables → canonical /A summary (skip if already canonical: idempotency).
        if str(obj.get("/S", "")) == "/Table" and not _table_is_canonical(obj):
            _normalize_table(pdf, obj)
            tables += 1

        # 2) Hides-annotation: alt text on an element wrapping an annotation.
        if "/Alt" in obj and _subtree_has_objr(obj):
            del obj["/Alt"]
            hann += 1

        # 3) Non-leaf elements (their /Alt is never read).
        if _has_child_struct_elem(obj):
            if str(obj.get("/S", "")) == "/Figure":
                # A non-leaf figure is mis-typed (figures must be atomic): keeping
                # alt fails "nested alt", dropping it fails "figure needs alt".
                # Retag to a grouping element so neither check applies.
                obj["/S"] = Name("/Div")
                if "/Alt" in obj:
                    del obj["/Alt"]
                retagged += 1
            elif "/Alt" in obj:
                del obj["/Alt"]
                nested += 1

        # 4) Orphan alt text on a contentless element.
        if not _has_content(obj):
            for key in _ALT_KEYS:
                if key in obj:
                    del obj[key]
                    orphan += 1

    return ComplianceCounts(
        orphan_attrs=orphan, tables_normalized=tables, hides_annotation=hann,
        nested_alt=nested, figures_retagged=retagged,
    )


def apply_compliance_pass(
    pdf_path: Path | str,
    *,
    out_path: Path | str | None = None,
    dry_run: bool = False,
) -> ComplianceCounts:
    """Apply the Adobe-compliance fixes to one PDF.

    By default rewrites *pdf_path* in place. Pass *out_path* to write elsewhere,
    or *dry_run=True* to count fixes without writing anything.

    Raises on unopenable / malformed PDFs (the caller decides how to handle).
    """
    pdf_path = Path(pdf_path)
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        counts = _fix_in_memory(pdf)
        if not dry_run:
            pdf.save(Path(out_path) if out_path else pdf_path)
    return counts


@dataclass
class DirectoryResult:
    """Aggregate outcome of running the pass over a directory."""

    files: int = 0
    errors: int = 0
    counts: ComplianceCounts = None  # type: ignore[assignment]
    error_files: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.counts is None:
            self.counts = ComplianceCounts()
        if self.error_files is None:
            self.error_files = []


def process_directory(
    directory: Path | str,
    *,
    pattern: str = "*.pdf",
    dry_run: bool = False,
) -> DirectoryResult:
    """Run the pass over every PDF in *directory* (non-recursive, sorted)."""
    directory = Path(directory)
    result = DirectoryResult()
    for pdf_path in sorted(directory.glob(pattern)):
        try:
            result.counts = result.counts + apply_compliance_pass(pdf_path, dry_run=dry_run)
            result.files += 1
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the batch
            result.errors += 1
            result.error_files.append(pdf_path.name)
            logger.warning("adobe_compliance pass failed for %s: %s", pdf_path, exc)
    return result


def run_cli(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="adobe_compliance",
        description="Apply the deterministic Adobe-compliance post-pass to a PDF or directory.",
    )
    parser.add_argument("path", type=Path, help="a PDF file or a directory of PDFs")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report fixes that would be applied without modifying any file",
    )
    parser.add_argument(
        "--glob", default="*.pdf",
        help="glob pattern when PATH is a directory (default: *.pdf)",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress per-file output")
    args = parser.parse_args(argv)

    if not args.path.exists():
        parser.error(f"path does not exist: {args.path}")

    if args.path.is_dir():
        result = process_directory(args.path, pattern=args.glob, dry_run=args.dry_run)
        summary = {
            "mode": "dry-run" if args.dry_run else "applied",
            "directory": str(args.path),
            "files": result.files,
            "errors": result.errors,
            "error_files": result.error_files,
            "orphan_attrs": result.counts.orphan_attrs,
            "tables_normalized": result.counts.tables_normalized,
            "hides_annotation": result.counts.hides_annotation,
            "nested_alt": result.counts.nested_alt,
            "figures_retagged": result.counts.figures_retagged,
        }
        print(json.dumps(summary, indent=2))
        return 1 if result.errors else 0

    # single file
    try:
        counts = apply_compliance_pass(args.path, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"file": str(args.path), "error": str(exc)}))
        return 1
    out = {"file": str(args.path), "mode": "dry-run" if args.dry_run else "applied", **asdict(counts)}
    if not args.quiet:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_cli())
