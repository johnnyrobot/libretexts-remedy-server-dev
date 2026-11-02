"""Real PDF compatibility and bounded, locally constructed malformed inputs."""

import os
import subprocess
import sys
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas


def test_pdf_append_write_extract_and_encryption_round_trip(tmp_path):
    writer = PdfWriter()
    for text in ("First PDF sentinel", "Second PDF sentinel"):
        source = BytesIO()
        canvas = Canvas(source)
        canvas.drawString(72, 720, text)
        canvas.save()
        writer.append(BytesIO(source.getvalue()))
    writer.add_metadata({"/Title": "Retained PDF order"})
    writer.encrypt("fixture-password")
    output = tmp_path / "merged.pdf"
    writer.write(output)
    reader = PdfReader(output)
    assert reader.is_encrypted
    assert reader.decrypt("fixture-password")
    assert len(reader.pages) == 2
    assert reader.metadata.title == "Retained PDF order"
    assert [page.extract_text().strip() for page in reader.pages] == [
        "First PDF sentinel", "Second PDF sentinel",
    ]


def test_missing_xref_trailer_fails_without_parser_loop():
    # Tiny synthetic input from upstream PR4289 (CVE-2026-119203); no
    # downloaded exploit. Isolate it so vulnerable versions cannot hang pytest.
    script = r'''
import resource
from io import BytesIO
from pypdf import PdfReader
from pypdf.errors import PdfReadError
resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
try:
    PdfReader(BytesIO(b"%PDF-1.4\nstartxref\n28\n%%EOF\nxref\n1 0\naaa"))
except PdfReadError:
    pass
else:
    raise AssertionError("Malformed PDF unexpectedly accepted")
'''
    result = subprocess.run(
        [sys.executable, "-c", script], timeout=5,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert result.returncode == 0, "Malformed PDF must fail within the parser budget"


@pytest.mark.skipif(
    os.environ.get("REMEDY_FULL_RUNTIME_TESTS") != "1",
    reason="real OCR merge requires the shipping Tesseract runtime",
)
def test_real_ocr_rebuild_keeps_both_pdf_pages_and_searchable_text(tmp_path):
    import fitz
    from reportlab.lib.utils import ImageReader
    from project_remedy.pdf_fixer import fix_all

    source = tmp_path / "image-only.pdf"
    canvas = Canvas(str(source), pagesize=(600, 800))
    for text in ("FIRST PDF SENTINEL", "SECOND PDF SENTINEL"):
        with fitz.open() as document:
            page = document.new_page(width=600, height=800)
            page.insert_text((60, 100), text, fontsize=28)
            image = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
        canvas.drawImage(ImageReader(BytesIO(image)), 0, 0, 600, 800)
        canvas.showPage()
    canvas.save()
    output = tmp_path / "searchable.pdf"
    report = fix_all(source, output, only="doc-not-image-only")
    assert any("Rebuilt image-only PDF" in change for change in report.changes)
    reader = PdfReader(output)
    assert len(reader.pages) == 2
    assert "FIRST PDF SENTINEL" in reader.pages[0].extract_text()
    assert "SECOND PDF SENTINEL" in reader.pages[1].extract_text()
