"""Markdown to rebuild-AST block tree.

Consumes the extractor's ``ocr_markdown`` output and emits a list of
rebuild-AST Block instances, plus transient ImagePlaceholder blocks
that ast_builder later replaces with FigureBlock or ArtifactBlock
after consulting the vision pipeline's classification.

Pure function. No I/O. Uses markdown-it-py for a CommonMark-compliant
tokenization, then walks the token stream.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

from project_remedy.rebuild.ast import (
    Block,
    HeadingBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    Run,
    SimpleTableBlock,
    TableCell,
    TableRow,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImagePlaceholder:
    """Transient block. Replaced by FigureBlock/ArtifactBlock in ast_builder.

    Not registered in the Block union because it never escapes the composer.
    """
    filename: str
    alt_hint: str


_PAGE_MARKER = re.compile(r"<!--\s*Page\s+\d+\s*-->")


def parse(ocr_markdown: str) -> list:
    """Parse extractor's ocr_markdown into a rebuild-AST block tree.

    Returns list of Block | ImagePlaceholder.
    """
    if not ocr_markdown or not ocr_markdown.strip():
        return []
    stripped = _PAGE_MARKER.sub("", ocr_markdown)
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    try:
        tokens = md.parse(stripped)
    except Exception as exc:  # noqa: BLE001
        logger.warning("rebuild.markdown_parse_failed: %s", exc)
        return []
    return list(_walk(tokens))


def _walk(tokens: list[Token]):
    """Top-level walker. Yields Block | ImagePlaceholder."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            level = int(tok.tag[1])
            inline = tokens[i + 1]
            close = i + 2
            yield HeadingBlock(level=level, runs=_inline_runs(inline))
            i = close + 1
        elif tok.type == "paragraph_open":
            inline = tokens[i + 1]
            close = i + 2
            # Image-only paragraphs become placeholders; else a normal paragraph
            # with embedded image placeholders dropped in line.
            para_items = list(_paragraph_items(inline))
            if len(para_items) == 1 and isinstance(para_items[0], ImagePlaceholder):
                yield para_items[0]
            else:
                runs = [item for item in para_items if isinstance(item, Run)]
                if runs:
                    yield ParagraphBlock(runs=runs)
                for item in para_items:
                    if isinstance(item, ImagePlaceholder):
                        yield item
            i = close + 1
        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            ordered = tok.type == "ordered_list_open"
            list_block, consumed = _parse_list(tokens, i, ordered)
            yield list_block
            i += consumed
        elif tok.type == "table_open":
            table_block, consumed = _parse_table(tokens, i)
            yield table_block
            i += consumed
        else:
            i += 1


def _inline_runs(inline: Token) -> list[Run]:
    """Convert an inline token's children into list[Run]."""
    runs: list[Run] = []
    bold = italic = False
    for child in inline.children or []:
        if child.type == "strong_open":
            bold = True
        elif child.type == "strong_close":
            bold = False
        elif child.type == "em_open":
            italic = True
        elif child.type == "em_close":
            italic = False
        elif child.type == "text":
            if child.content:
                runs.append(Run(text=child.content, bold=bold, italic=italic))
        # Ignore image/link within headings - rare; falls through silently.
    return runs or [Run(text="")]


def _paragraph_items(inline: Token):
    """Yield Run | ImagePlaceholder from a paragraph's inline token."""
    bold = italic = False
    for child in inline.children or []:
        if child.type == "strong_open":
            bold = True
        elif child.type == "strong_close":
            bold = False
        elif child.type == "em_open":
            italic = True
        elif child.type == "em_close":
            italic = False
        elif child.type == "text":
            if child.content:
                yield Run(text=child.content, bold=bold, italic=italic)
        elif child.type == "image":
            src = child.attrs.get("src", "") if child.attrs else ""
            alt = "".join(
                c.content for c in (child.children or []) if c.type == "text"
            )
            yield ImagePlaceholder(filename=src, alt_hint=alt)
        elif child.type == "softbreak" or child.type == "hardbreak":
            yield Run(text=" ", bold=bold, italic=italic)


def _parse_list(tokens: list[Token], start: int, ordered: bool) -> tuple[ListBlock, int]:
    """Parse list_open ... list_close. Returns (ListBlock, tokens_consumed)."""
    i = start + 1
    items: list[ListItem] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.type in ("bullet_list_close", "ordered_list_close"):
            return ListBlock(ordered=ordered, items=items), (i - start + 1)
        if tok.type == "list_item_open":
            item, consumed = _parse_list_item(
                tokens, i, ordered, ordinal=len(items) + 1
            )
            items.append(item)
            i += consumed
        else:
            i += 1
    return ListBlock(ordered=ordered, items=items), (i - start)


def _parse_list_item(
    tokens: list[Token],
    start: int,
    ordered: bool,
    *,
    ordinal: int = 1,
) -> tuple[ListItem, int]:
    i = start + 1
    body: list = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "list_item_close":
            label = Run(text=f"{ordinal}.") if ordered else Run(text="\u2022")
            return ListItem(label_runs=[label], body=body), (i - start + 1)
        if tok.type == "paragraph_open":
            inline = tokens[i + 1]
            para_items = list(_paragraph_items(inline))
            runs = [it for it in para_items if isinstance(it, Run)]
            if runs:
                body.append(ParagraphBlock(runs=runs))
            for it in para_items:
                if isinstance(it, ImagePlaceholder):
                    body.append(it)
            i += 3  # paragraph_open, inline, paragraph_close
        elif tok.type in ("bullet_list_open", "ordered_list_open"):
            nested_ordered = tok.type == "ordered_list_open"
            nested, consumed = _parse_list(tokens, i, nested_ordered)
            body.append(nested)
            i += consumed
        else:
            i += 1
    # Fallthrough (malformed input): use bullet for unordered, ordinal for ordered
    label = Run(text=f"{ordinal}.") if ordered else Run(text="\u2022")
    return ListItem(label_runs=[label], body=body), (i - start)


def _parse_table(tokens: list[Token], start: int) -> tuple[SimpleTableBlock, int]:
    i = start + 1
    rows: list[TableRow] = []
    in_header = False
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "table_close":
            return SimpleTableBlock(rows=rows), (i - start + 1)
        if tok.type == "thead_open":
            in_header = True
            i += 1
        elif tok.type == "thead_close":
            in_header = False
            i += 1
        elif tok.type == "tr_open":
            row, consumed = _parse_table_row(tokens, i, header=in_header)
            rows.append(row)
            i += consumed
        else:
            i += 1
    return SimpleTableBlock(rows=rows), (i - start)


def _parse_table_row(tokens: list[Token], start: int, *, header: bool) -> tuple[TableRow, int]:
    i = start + 1
    cells: list[TableCell] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "tr_close":
            return TableRow(cells=cells), (i - start + 1)
        if tok.type in ("th_open", "td_open"):
            # Next token is inline; th is always header for the col.
            inline = tokens[i + 1]
            text = _inline_plain_text(inline)
            cells.append(
                TableCell(
                    text=text,
                    header="col" if (header or tok.type == "th_open") else "none",
                )
            )
            i += 3  # open, inline, close
        else:
            i += 1
    return TableRow(cells=cells), (i - start)


def _inline_plain_text(inline: Token) -> str:
    parts = []
    for child in inline.children or []:
        if child.type == "text":
            parts.append(child.content)
    return "".join(parts).strip()
