"""Pydantic AST schema for the QuestPDF rebuild sidecar.

This schema is the contract between the Python engine and the .NET
sidecar. The C# record tree in sidecar/QuestPdfRenderer/Ast.cs must
mirror it field-for-field.

Full tier: metadata, page, conformance, and content blocks of kind
heading (H1-H6), paragraph, list, simple_table, figure, artifact.
Figures and artifacts reference assets via asset_ref keys resolved
against the request-level ``assets`` dict.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Run(_Frozen):
    text: str
    bold: bool = False
    italic: bool = False


class Metadata(_Frozen):
    title: str
    language: str
    subject: str | None = None


class Margin(_Frozen):
    top: float
    right: float
    bottom: float
    left: float
    unit: Literal["in", "cm", "mm", "pt"]


class PageSettings(_Frozen):
    size: Literal["Letter", "A4"]
    margin: Margin


class Conformance(_Frozen):
    pdfua: Literal["PDFUA_1"] | None = None
    pdfa: Literal["PDFA_3A", "PDFA_3B"] | None = None


class HeadingBlock(_Frozen):
    kind: Literal["heading"] = "heading"
    level: int = Field(ge=1, le=6)
    runs: list[Run]


class ParagraphBlock(_Frozen):
    kind: Literal["paragraph"] = "paragraph"
    runs: list[Run]


class ListItem(_Frozen):
    label_runs: list[Run]
    body: list["Block"]


class ListBlock(_Frozen):
    kind: Literal["list"] = "list"
    ordered: bool
    items: list[ListItem]


class TableCell(_Frozen):
    text: str
    header: Literal["none", "col", "row", "both"] = "none"


class TableRow(_Frozen):
    cells: list[TableCell]


class SimpleTableBlock(_Frozen):
    kind: Literal["simple_table"] = "simple_table"
    rows: list[TableRow]


class FigureBlock(_Frozen):
    kind: Literal["figure"] = "figure"
    asset_ref: str
    alt: str = Field(min_length=1)
    caption: list[Run] | None = None


class ArtifactBlock(_Frozen):
    kind: Literal["artifact"] = "artifact"
    asset_ref: str


Block = Annotated[
    Union[
        HeadingBlock,
        ParagraphBlock,
        ListBlock,
        SimpleTableBlock,
        FigureBlock,
        ArtifactBlock,
    ],
    Field(discriminator="kind"),
]


class AssetRef(_Frozen):
    path: str
    mime: Literal["image/png", "image/jpeg"]


ListItem.model_rebuild()


class RebuildRequest(_Frozen):
    metadata: Metadata
    page: PageSettings
    conformance: Conformance
    content: list[Block]
    assets: dict[str, AssetRef] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _pdfua_requires_language(self) -> "RebuildRequest":
        if self.conformance.pdfua == "PDFUA_1" and not self.metadata.language.strip():
            raise ValueError("conformance.pdfua == PDFUA_1 requires metadata.language")
        return self

    @model_validator(mode="after")
    def _asset_refs_resolve(self) -> "RebuildRequest":
        """Every FigureBlock/ArtifactBlock asset_ref must appear in assets."""
        refs_needed: set[str] = set()

        def _walk(blocks: list[Block]) -> None:
            for b in blocks:
                if isinstance(b, (FigureBlock, ArtifactBlock)):
                    refs_needed.add(b.asset_ref)
                elif isinstance(b, ListBlock):
                    for item in b.items:
                        _walk(item.body)

        _walk(self.content)
        missing = refs_needed - set(self.assets.keys())
        if missing:
            raise ValueError(
                f"dangling asset_ref(s) not in assets dict: {sorted(missing)}"
            )
        return self
