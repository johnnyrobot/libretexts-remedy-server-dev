using System.Text.Json;
using QuestPDF;
using QuestPDF.Infrastructure;
using QuestPdfRenderer;

QuestPDF.Settings.License = LicenseType.Community;

try
{
    using var stdin = Console.OpenStandardInput();
    var req = await JsonSerializer.DeserializeAsync(stdin, AstJsonContext.Default.RebuildRequest);
    if (req is null)
    {
        Console.Error.WriteLine("{\"error\":\"empty_input\"}");
        return 1;
    }

    byte[] pdf = Renderer.Render(req);

    using var stdout = Console.OpenStandardOutput();
    await stdout.WriteAsync(pdf);
    return 0;
}
catch (JsonException ex)
{
    Console.Error.WriteLine($"{{\"error\":\"json_parse\",\"message\":{JsonSerializer.Serialize(ex.Message, AstJsonContext.Default.String)}}}");
    return 1;
}
catch (InvariantViolation ex)
{
    Console.Error.WriteLine($"{{\"error\":\"invariant\",\"message\":{JsonSerializer.Serialize(ex.Message, AstJsonContext.Default.String)}}}");
    return 2;
}
catch (Exception ex)
{
    Console.Error.WriteLine($"{{\"error\":\"render\",\"message\":{JsonSerializer.Serialize(ex.Message, AstJsonContext.Default.String)}}}");
    return 3;
}
