"""Content-stream BT/ET repair — makes remediated PDFs render in strict viewers.

The remediation engine's tag-injection corrupts page content streams: it emits
tagged text as ``BDC /Tag <</MCID n>> BT <text> EMC`` but DROPS the closing
``ET`` (and some intermediate ``BT``), leaving text objects unbalanced. Lenient
renderers (Preview/Quartz, poppler) auto-repair this, so the page looks fine;
Acrobat and Ghostscript enforce the spec and reject it ("invalid operator in
text block" / "text operator outside text block"), so the page fails to render.

This renormalizes each page's content stream so that:
  * every text-showing/-positioning/-state operator sits inside a balanced
    ``BT … ET`` (a dropped ``BT`` is re-opened),
  * no illegal operator (path/graphics/XObject) sits inside a text object
    (a dropped ``ET`` is re-inserted before it),
  * marked-content sequences stay properly nested with text objects.

ONLY ``BT``/``ET`` operators are inserted or removed. Operands, fonts, marked
content (``/MCID``), positioning, resources, and the structure tree are
untouched — text extraction and PDF/UA-1 compliance are preserved.

Idempotent: an already-balanced stream is left byte-for-byte unchanged.

This fixes *rendering*; it is independent of and complementary to
``adobe_compliance`` (which fixes the accessibility *structure tree*).
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pikepdf

logger = logging.getLogger(__name__)

#: Text-showing / -positioning / -state operators. These REQUIRE a text object;
#: if one appears outside BT/ET the engine dropped the BT, so we re-open one.
_TEXT_TRIGGER = set(
    """Tj TJ ' " Td TD Tm T* Tc Tw Tz TL Tf Tr Ts""".split()
)
#: Operators additionally legal INSIDE a text object (colour + general graphics
#: state). These are legal outside too, so they neither open nor close a block.
_TEXT_OK = _TEXT_TRIGGER | set(
    """g G rg RG k K cs CS sc scn SC SCN gs w J j M d ri i d0 d1""".split()
)

_BT = pikepdf.ContentStreamInstruction([], pikepdf.Operator("BT"))
_ET = pikepdf.ContentStreamInstruction([], pikepdf.Operator("ET"))


@dataclass
class RepairResult:
    """Aggregate outcome of repairing one or more PDFs."""

    files: int = 0
    files_changed: int = 0
    ops_changed: int = 0          # BT/ET inserted or dropped across all pages
    errors: int = 0
    error_files: list[str] = None  # type: ignore[assignment]
    changed_files: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.error_files is None:
            self.error_files = []
        if self.changed_files is None:
            self.changed_files = []


def _renormalize(instructions) -> tuple[list, int]:
    """Return (new_instructions, n_changes) with balanced, well-formed BT/ET.

    Pure transform over a list of pikepdf content-stream instructions, so it is
    unit-testable without a PDF. *n_changes* counts BT/ET inserted or dropped.
    """
    out = []
    in_text = False
    mc_stack: list[bool] = []   # per open BDC/BMC: was it opened while in_text?
    changes = 0
    for instr in instructions:
        s = str(instr.operator)
        if s in ("BDC", "BMC"):
            mc_stack.append(in_text)
            out.append(instr)
            continue
        if s == "EMC":
            opened_in_text = mc_stack.pop() if mc_stack else False
            # A marked-content sequence opened OUTSIDE the text object must not
            # close inside it: end the text object first.
            if in_text and not opened_in_text:
                out.append(_ET); changes += 1; in_text = False
            out.append(instr)
            continue
        if s in ("MP", "DP"):
            out.append(instr)
            continue
        if s == "BT":
            if not in_text:
                out.append(instr); in_text = True
            else:
                changes += 1   # redundant nested BT -> drop
            continue
        if s == "ET":
            if in_text:
                out.append(instr); in_text = False
            else:
                changes += 1   # orphaned ET (no open text object) -> drop
            continue
        if s in _TEXT_TRIGGER:
            if not in_text:
                out.append(_BT); changes += 1; in_text = True  # engine dropped the BT
            out.append(instr)
            continue
        if s in _TEXT_OK:
            out.append(instr)   # colour / graphics-state: legal either side
            continue
        # any other operator (q Q cm path-ops Do sh BI …) is illegal in a text object
        if in_text:
            out.append(_ET); changes += 1; in_text = False
        out.append(instr)
    if in_text:
        out.append(_ET); changes += 1
    return out, changes


def repair_page(pdf: pikepdf.Pdf, page) -> int:
    """Renormalize one page's content stream. Returns # of BT/ET ops changed
    (0 → already well-formed, stream left untouched)."""
    new_instructions, changes = _renormalize(pikepdf.parse_content_stream(page))
    if changes:
        page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(new_instructions))
    return changes


def repair_pdf(
    pdf_path: Path | str,
    *,
    out_path: Path | str | None = None,
    dry_run: bool = False,
) -> int:
    """Repair every page of one PDF. Returns total BT/ET ops changed.

    By default rewrites in place; pass *out_path* to write elsewhere or
    *dry_run=True* to count changes without writing. Raises on unopenable PDFs.
    """
    pdf_path = Path(pdf_path)
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        total = sum(repair_page(pdf, page) for page in pdf.pages)
        if total and not dry_run:
            pdf.save(Path(out_path) if out_path else pdf_path)
    return total


def process_directory(
    directory: Path | str,
    *,
    pattern: str = "*.pdf",
    dry_run: bool = False,
) -> RepairResult:
    """Repair every PDF in *directory* (non-recursive, sorted)."""
    directory = Path(directory)
    result = RepairResult()
    for pdf_path in sorted(directory.glob(pattern)):
        try:
            changed = repair_pdf(pdf_path, dry_run=dry_run)
            result.files += 1
            result.ops_changed += changed
            if changed:
                result.files_changed += 1
                result.changed_files.append(pdf_path.name)
        except Exception as exc:  # noqa: BLE001 - one bad file must not abort the batch
            result.errors += 1
            result.error_files.append(pdf_path.name)
            logger.warning("content_stream_repair failed for %s: %s", pdf_path, exc)
    return result


def run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="repair_content_streams",
        description="Repair unbalanced BT/ET in PDF page content streams so they "
                    "render in Acrobat/Ghostscript (not just Preview).",
    )
    parser.add_argument("path", type=Path, help="a PDF file or a directory of PDFs")
    parser.add_argument("--dry-run", action="store_true",
                        help="report changes that would be made without writing")
    parser.add_argument("--glob", default="*.pdf",
                        help="glob when PATH is a directory (default: *.pdf)")
    args = parser.parse_args(argv)

    if not args.path.exists():
        parser.error(f"path does not exist: {args.path}")

    if args.path.is_dir():
        r = process_directory(args.path, pattern=args.glob, dry_run=args.dry_run)
        print(json.dumps({
            "mode": "dry-run" if args.dry_run else "applied",
            "directory": str(args.path),
            "files": r.files,
            "files_changed": r.files_changed,
            "ops_changed": r.ops_changed,
            "errors": r.errors,
            "error_files": r.error_files,
        }, indent=2))
        return 1 if r.errors else 0

    try:
        changed = repair_pdf(args.path, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"file": str(args.path), "error": str(exc)}))
        return 1
    print(json.dumps({
        "file": str(args.path),
        "mode": "dry-run" if args.dry_run else "applied",
        "ops_changed": changed,
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_cli())
