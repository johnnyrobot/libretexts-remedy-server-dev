using QuestPDF.Fluent;
using QuestPDF.Helpers;
using QuestPDF.Infrastructure;

namespace QuestPdfRenderer;

public static class Renderer
{
    public static byte[] Render(RebuildRequest req)
    {
        return Document.Create(doc =>
        {
            doc.Page(page =>
            {
                page.Size(ParseSize(req.Page.Size));
                ApplyMargins(page, req.Page.Margin);

                page.Content().Column(col =>
                {
                    col.Spacing(10);
                    foreach (var block in req.Content)
                        col.Item().Element(c => RenderBlock(c, block, req));
                });
            });
        })
        .WithMetadata(new DocumentMetadata
        {
            Title = req.Metadata.Title,
            Language = req.Metadata.Language,
            Subject = req.Metadata.Subject ?? string.Empty,
        })
        .WithSettings(new DocumentSettings
        {
            PDFUA_Conformance = req.Conformance.Pdfua == "PDFUA_1"
                ? PDFUA_Conformance.PDFUA_1
                : PDFUA_Conformance.None,
            PDFA_Conformance = req.Conformance.Pdfa switch
            {
                "PDFA_3A" => PDFA_Conformance.PDFA_3A,
                "PDFA_3B" => PDFA_Conformance.PDFA_3B,
                _ => PDFA_Conformance.None,
            },
        })
        .GeneratePdf();
    }

    static void RenderBlock(IContainer container, Block block, RebuildRequest req)
    {
        switch (block)
        {
            case HeadingBlock h:
                {
                    var c = h.Level switch
                    {
                        1 => container.SemanticHeader1(),
                        2 => container.SemanticHeader2(),
                        3 => container.SemanticHeader3(),
                        4 => container.SemanticHeader4(),
                        5 => container.SemanticHeader5(),
                        6 => container.SemanticHeader6(),
                        _ => throw new InvariantViolation($"heading level must be 1..6, got {h.Level}"),
                    };
                    var size = h.Level switch { 1 => 22f, 2 => 17f, 3 => 14f, 4 => 12f, 5 => 11f, _ => 10f };
                    c.Text(t =>
                    {
                        foreach (var run in h.Runs)
                            EmitRun(t, run, defaultBold: true, size: size);
                    });
                    break;
                }

            case ParagraphBlock p:
                container.SemanticParagraph().Text(t =>
                {
                    foreach (var run in p.Runs) EmitRun(t, run);
                });
                break;

            case ListBlock l:
                container.SemanticList().Column(listCol =>
                {
                    listCol.Spacing(4);
                    foreach (var item in l.Items)
                    {
                        listCol.Item().SemanticListItem().Row(row =>
                        {
                            row.ConstantItem(18).SemanticListLabel().Text(t =>
                            {
                                foreach (var run in item.LabelRuns) EmitRun(t, run);
                            });
                            row.RelativeItem().SemanticListItemBody().Column(body =>
                            {
                                foreach (var b in item.Body)
                                    body.Item().Element(c => RenderBlock(c, b, req));
                            });
                        });
                    }
                });
                break;

            case SimpleTableBlock t:
                container.SemanticTable().Table(tbl =>
                {
                    if (t.Rows.Count == 0) return;
                    int cols = t.Rows[0].Cells.Count;
                    tbl.ColumnsDefinition(cd =>
                    {
                        for (int i = 0; i < cols; i++) cd.RelativeColumn();
                    });
                    foreach (var row in t.Rows)
                    {
                        foreach (var cell in row.Cells)
                        {
                            if (cell.Header == "col")
                            {
                                tbl.Cell()
                                    .AsSemanticHorizontalHeader()
                                    .Border(0.5f)
                                    .BorderColor(Colors.Grey.Darken1)
                                    .Background(Colors.Grey.Lighten3)
                                    .Padding(6)
                                    .Text(cell.Text).Bold();
                            }
                            else
                            {
                                tbl.Cell()
                                    .Border(0.5f)
                                    .BorderColor(Colors.Grey.Darken1)
                                    .Padding(6)
                                    .Text(cell.Text);
                            }
                        }
                    }
                });
                break;

            case FigureBlock f:
                {
                    if (!req.Assets.TryGetValue(f.AssetRef, out var asset))
                        throw new InvariantViolation($"figure asset_ref '{f.AssetRef}' not in assets dict");
                    container
                        .SemanticFigure(f.Alt)
                        .Column(col =>
                        {
                            col.Item().Image(asset.Path);
                            if (f.Caption is { Count: > 0 })
                            {
                                col.Item()
                                    .PaddingTop(5)
                                    .AlignCenter()
                                    .SemanticCaption()
                                    .Text(t =>
                                    {
                                        foreach (var run in f.Caption)
                                            EmitRun(t, run);
                                    });
                            }
                        });
                    break;
                }

            case ArtifactBlock a:
                {
                    if (!req.Assets.TryGetValue(a.AssetRef, out var asset))
                        throw new InvariantViolation($"artifact asset_ref '{a.AssetRef}' not in assets dict");
                    container.SemanticIgnore().Image(asset.Path);
                    break;
                }

            default:
                throw new InvariantViolation($"unsupported block kind: {block.GetType().Name}");
        }
    }

    static void EmitRun(TextDescriptor text, Run run, bool defaultBold = false, float? size = null)
    {
        var span = text.Span(run.Text);
        if (run.Bold || defaultBold) span.Bold();
        if (run.Italic) span.Italic();
        if (size.HasValue) span.FontSize(size.Value);
    }

    static PageSize ParseSize(string s) => s switch
    {
        "Letter" => PageSizes.Letter,
        "A4" => PageSizes.A4,
        _ => throw new InvariantViolation($"unsupported page size: {s}"),
    };

    static void ApplyMargins(PageDescriptor page, Margin m)
    {
        var unit = m.Unit switch
        {
            "in" => Unit.Inch,
            "cm" => Unit.Centimetre,
            "mm" => Unit.Millimetre,
            "pt" => Unit.Point,
            _ => throw new InvariantViolation($"unsupported margin unit: {m.Unit}"),
        };
        page.MarginTop((float)m.Top, unit);
        page.MarginRight((float)m.Right, unit);
        page.MarginBottom((float)m.Bottom, unit);
        page.MarginLeft((float)m.Left, unit);
    }
}
