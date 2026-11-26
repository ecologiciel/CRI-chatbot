"""Tests for text extraction from KB documents."""

from __future__ import annotations

import csv
import io

import pytest

from app.core.exceptions import IngestionError
from app.services.rag.extractors import SUPPORTED_EXTENSIONS, extract_document, extract_text


class TestExtractPlainText:
    """Test TXT and MD extraction."""

    def test_extract_txt_utf8(self):
        """UTF-8 text is returned as-is."""
        content = "Bienvenue au CRI Rabat.\nGuide de l'investisseur."
        result = extract_text(content.encode("utf-8"), "guide.txt")
        assert result == content

    def test_extract_md(self):
        """Markdown files are extracted like plain text."""
        content = "# Titre\n\nContenu du document."
        result = extract_text(content.encode("utf-8"), "README.md")
        assert result == content

    def test_extract_txt_latin1_fallback(self):
        """Latin-1 encoded text falls back gracefully."""
        content = "Résumé des procédures"
        data = content.encode("latin-1")
        result = extract_text(data, "procedures.txt")
        assert "sum" in result  # Partial match — latin-1 decoded

    def test_extract_empty_txt_raises(self):
        """Empty text file raises IngestionError."""
        with pytest.raises(IngestionError, match="No text content"):
            extract_text(b"   \n  \t  ", "empty.txt")


class TestExtractCSV:
    """Test CSV extraction."""

    def test_extract_csv_basic(self):
        """Each CSV row retains its column labels."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Nom", "Secteur", "Région"])
        writer.writerow(["Projet Alpha", "Industrie", "Rabat"])
        writer.writerow(["Projet Beta", "Tourisme", "Tanger"])
        data = buf.getvalue().encode("utf-8")

        result = extract_text(data, "projets.csv")

        assert '"Nom": "Projet Alpha" | "Secteur": "Industrie" | "Région": "Rabat"' in result
        assert '"Nom": "Projet Beta" | "Secteur": "Tourisme" | "Région": "Tanger"' in result

    def test_csv_empty_cells_do_not_shift_column_values(self):
        result = extract_text("Produit;Quantité;Unité\nTomate;;kg\n".encode(), "produits.csv")
        assert '"Produit": "Tomate" | "Quantité": "" | "Unité": "kg"' in result

    def test_csv_quoted_delimiters_and_missing_columns(self):
        result = extract_text('Nom;Valeur;Unité\n"Tomate; verte";3\n'.encode(), "produits.csv")
        assert '"Nom": "Tomate; verte" | "Valeur": "3" | "Unité": [colonne absente]' in result

    def test_csv_rows_retain_headers_across_chunks(self):
        from app.services.rag.chunker import ChunkingService

        data = "Produit,Condition\n" + "".join(f"Produit{i},Condition{i}\n" for i in range(25))
        text = extract_text(data.encode(), "produits.csv")
        chunks = ChunkingService(chunk_size=55, overlap=0, max_chunk_size=60).chunk_text(text)
        assert len(chunks) > 1
        assert all(text[c.start_char : c.end_char] == c.content for c in chunks)
        for i in range(25):
            expected = f'"Produit": "Produit{i}" | "Condition": "Condition{i}"'
            assert any(expected in chunk.content for chunk in chunks)

    def test_extract_csv_empty_raises(self):
        """Empty CSV raises IngestionError."""
        with pytest.raises(IngestionError, match="No text content"):
            extract_text(b"", "empty.csv")


class TestExtractPDF:
    def test_physical_page_offsets_preserve_blank_pages(self, monkeypatch):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        import pdfplumber

        pages = [MagicMock(), MagicMock(), MagicMock()]
        for page, text in zip(
            pages, ["  Premiere page agricole ", "", " Troisieme page sanitaire  "], strict=True
        ):
            page.extract_text.return_value = text
        pdf = MagicMock()
        pdf.__enter__.return_value = SimpleNamespace(pages=pages)
        monkeypatch.setattr(pdfplumber, "open", lambda _: pdf)

        extracted = extract_document(b"pdf", "fixture.pdf")
        assert extracted.text == extract_text(b"pdf", "fixture.pdf")
        assert [page.number for page in extracted.pages] == [1, 3]
        assert (
            extracted.text[extracted.pages[0].start : extracted.pages[0].end]
            == "Premiere page agricole"
        )
        assert (
            extracted.text[extracted.pages[1].start : extracted.pages[1].end]
            == "Troisieme page sanitaire"
        )

    """Test PDF extraction."""

    def test_extract_pdf_basic(self):
        """Extract text from a minimal PDF."""
        # Build a minimal valid PDF with text
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            pytest.skip("pdfplumber not installed")

        # Create a minimal PDF using reportlab if available, else
        # use a raw PDF with embedded text
        pdf_bytes = _make_minimal_pdf("Guide de l'investisseur au Maroc")
        result = extract_text(pdf_bytes, "guide.pdf")
        assert "investisseur" in result.lower()

    def test_extract_pdf_empty_raises(self):
        """PDF with no text raises IngestionError."""
        # A minimal valid PDF structure with no text content
        pdf_bytes = _make_minimal_pdf("")
        with pytest.raises(IngestionError, match="No text content"):
            extract_text(pdf_bytes, "empty.pdf")


class TestExtractDocx:
    def test_docx_table_keeps_headings_and_document_order(self):
        import io

        from docx import Document

        doc = Document()
        doc.add_paragraph("Avant le tableau")
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Produit"
        table.cell(0, 1).text = "Condition"
        table.cell(1, 0).text = "Tomate"
        table.cell(1, 1).text = "Contrôle requis"
        doc.add_paragraph("Après le tableau")
        buffer = io.BytesIO()
        doc.save(buffer)
        result = extract_text(buffer.getvalue(), "test.docx")
        assert "Produit: Tomate | Condition: Contrôle requis" in result
        assert (
            result.index("Avant le tableau")
            < result.index("Produit: Tomate")
            < result.index("Après le tableau")
        )

    """Test DOCX extraction."""

    def test_extract_docx_basic(self):
        """Extract text from a minimal DOCX."""
        try:
            from docx import Document
        except ImportError:
            pytest.skip("python-docx not installed")

        doc = Document()
        doc.add_paragraph("Procédures d'investissement")
        doc.add_paragraph("Formulaire de création d'entreprise")
        buf = io.BytesIO()
        doc.save(buf)
        data = buf.getvalue()

        result = extract_text(data, "procedures.docx")
        assert "investissement" in result.lower()
        assert "entreprise" in result.lower()

    def test_extract_docx_empty_raises(self):
        """DOCX with no paragraphs raises IngestionError."""
        try:
            from docx import Document
        except ImportError:
            pytest.skip("python-docx not installed")

        doc = Document()
        buf = io.BytesIO()
        doc.save(buf)
        data = buf.getvalue()

        with pytest.raises(IngestionError, match="No text content"):
            extract_text(data, "empty.docx")


class TestUnsupportedExtension:
    """Test rejection of unsupported file types."""

    @pytest.mark.parametrize("filename", ["malware.exe", "archive.zip", "image.png", "data.json"])
    def test_unsupported_extension_raises(self, filename: str):
        """Unsupported extensions raise IngestionError."""
        with pytest.raises(IngestionError, match="Unsupported file extension"):
            extract_text(b"some data", filename)

    def test_supported_extensions_constant(self):
        """Verify supported extensions set."""
        assert {".pdf", ".docx", ".txt", ".md", ".csv"} == SUPPORTED_EXTENSIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_pdf(text: str) -> bytes:
    """Create a minimal PDF with the given text.

    Uses a raw PDF structure to avoid extra dependencies.
    """
    # Minimal valid PDF 1.4 with a single page and text
    stream_content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""

    stream_bytes = stream_content.encode("latin-1")
    stream_length = len(stream_bytes)

    pdf = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj

4 0 obj
<< /Length {stream_length} >>
stream
{stream_content}
endstream
endobj

5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj

xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000000 00000 n

trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF"""

    return pdf.encode("latin-1")
