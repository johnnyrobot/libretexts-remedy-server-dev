using System.Text.Json.Serialization;

namespace QuestPdfRenderer;

public sealed record RebuildRequest(
    Metadata Metadata,
    PageSettings Page,
    Conformance Conformance,
    List<Block> Content,
    Dictionary<string, AssetRef> Assets
);

public sealed record Metadata(string Title, string Language, string? Subject = null);

public sealed record PageSettings(string Size, Margin Margin);

public sealed record Margin(double Top, double Right, double Bottom, double Left, string Unit);

public sealed record Conformance(string? Pdfua, string? Pdfa);

[JsonPolymorphic(TypeDiscriminatorPropertyName = "kind")]
[JsonDerivedType(typeof(HeadingBlock), "heading")]
[JsonDerivedType(typeof(ParagraphBlock), "paragraph")]
[JsonDerivedType(typeof(ListBlock), "list")]
[JsonDerivedType(typeof(SimpleTableBlock), "simple_table")]
[JsonDerivedType(typeof(FigureBlock), "figure")]
[JsonDerivedType(typeof(ArtifactBlock), "artifact")]
public abstract record Block;

public sealed record HeadingBlock(int Level, List<Run> Runs) : Block;
public sealed record ParagraphBlock(List<Run> Runs) : Block;
public sealed record ListBlock(bool Ordered, List<ListItem> Items) : Block;
public sealed record SimpleTableBlock(List<TableRow> Rows) : Block;
public sealed record FigureBlock(string AssetRef, string Alt, List<Run>? Caption = null) : Block;
public sealed record ArtifactBlock(string AssetRef) : Block;

public sealed record Run(string Text, bool Bold = false, bool Italic = false);
public sealed record ListItem(List<Run> LabelRuns, List<Block> Body);
public sealed record TableRow(List<TableCell> Cells);
public sealed record TableCell(string Text, string Header = "none");
public sealed record AssetRef(string Path, string Mime);

public sealed class InvariantViolation : Exception
{
    public InvariantViolation(string message) : base(message) { }
}

[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.SnakeCaseLower,
    UseStringEnumConverter = true)]
[JsonSerializable(typeof(RebuildRequest))]
[JsonSerializable(typeof(string))]
[JsonSerializable(typeof(ListBlock), TypeInfoPropertyName = "RemedyListBlock")]
internal partial class AstJsonContext : JsonSerializerContext { }
