"""Text extraction from uploaded KB documents.

Supports PDF, DOCX, TXT, MD, CSV. Each extractor reads raw bytes
and returns the full text content. Raises IngestionError on failure.

Usage:
    text = extract_text(file_bytes, "guide_investisseur.pdf")
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.core.exceptions import IngestionError
from app.core.uploads import validate_docx_archive

SUPPORTED_EXTENSIONS: set[str] = {".pdf", ".docx", ".txt", ".md", ".csv"}


@dataclass(frozen=True, slots=True)
class PageSpan:
    """Physical PDF page and its half-open character span in extracted text."""

    number: int
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    text: str
    pages: tuple[PageSpan, ...] = ()


def extract_document(file_bytes: bytes, filename: str) -> ExtractedDocument:
    """Extract text plus physical page offsets when the input is a PDF."""
    if PurePosixPath(filename).suffix.lower() != ".pdf":
        return ExtractedDocument(text=extract_text(file_bytes, filename))

    import pdfplumber

    try:
        parts: list[str] = []
        raw_spans: list[PageSpan] = []
        offset = 0
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text()
                if not page_text:
                    continue
                if parts:
                    offset += 2  # The same separator used by _extract_pdf.
                start = offset
                parts.append(page_text)
                offset += len(page_text)
                if page_text.strip():
                    raw_spans.append(
                        PageSpan(
                            number,
                            start + len(page_text) - len(page_text.lstrip()),
                            offset - (len(page_text) - len(page_text.rstrip())),
                        )
                    )
        raw = "\n\n".join(parts)
        content = raw.strip()
        if not content:
            raise IngestionError(
                f"No text content extracted from {filename}",
                details={"filename": filename, "extension": ".pdf"},
            )
        removed_prefix = len(raw) - len(raw.lstrip())
        pages = tuple(
            PageSpan(
                page.number,
                max(0, page.start - removed_prefix),
                min(len(content), page.end - removed_prefix),
            )
            for page in raw_spans
            if page.end > removed_prefix and page.start < removed_prefix + len(content)
        )
        return ExtractedDocument(text=content, pages=pages)
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(
            f"Text extraction failed for {filename}: {exc}",
            details={"filename": filename, "extension": ".pdf"},
        ) from exc


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract text from file bytes based on filename extension.

    Args:
        file_bytes: Raw file content.
        filename: Original filename (used for extension detection).

    Returns:
        Extracted text content.

    Raises:
        IngestionError: If extension is unsupported, extraction fails,
                        or the result is empty.
    """
    ext = PurePosixPath(filename).suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestionError(
            f"Unsupported file extension: {ext}",
            details={"filename": filename, "supported": sorted(SUPPORTED_EXTENSIONS)},
        )

    if ext == ".docx":
        validate_docx_archive(file_bytes)

    extractors = {
        ".pdf": _extract_pdf,
        ".docx": _extract_docx,
        ".txt": _extract_plain,
        ".md": _extract_plain,
        ".csv": _extract_csv,
    }

    try:
        text = extractors[ext](file_bytes)
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(
            f"Text extraction failed for {filename}: {exc}",
            details={"filename": filename, "extension": ext},
        ) from exc

    text = text.strip()
    if not text:
        raise IngestionError(
            f"No text content extracted from {filename}",
            details={"filename": filename, "extension": ext},
        )

    return text


def _extract_pdf(data: bytes) -> str:
    """Extract text from PDF using pdfplumber."""
    import pdfplumber

    pages_text: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages_text.append(page_text)

    return "\n\n".join(pages_text)


def _extract_docx(data: bytes) -> str:
    """Extract paragraphs and tables in document order using python-docx."""
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    paragraphs: list[str] = []
    for element in doc.element.body.iterchildren():
        if isinstance(element, CT_P):
            paragraph = Paragraph(element, doc)
            if paragraph.text.strip():
                paragraphs.append(paragraph.text)
        elif isinstance(element, CT_Tbl):
            table = Table(element, doc)
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not rows:
                continue
            header = rows[0]
            if any(header):
                paragraphs.append(" | ".join(header))
            for row in rows[1:]:
                if any(row):
                    # Repeat the column names so a row remains intelligible if
                    # the chunker splits it from the original header.
                    paragraphs.append(
                        " | ".join(
                            f"{header[i]}: {value}" if i < len(header) and header[i] else value
                            for i, value in enumerate(row)
                        )
                    )

    return "\n\n".join(paragraphs)


def _extract_plain(data: bytes) -> str:
    """Extract text from plain text files (TXT, MD)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _extract_csv(data: bytes) -> str:
    """Extract text from CSV — each row joined as a line."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    # Common exports use commas, semicolons or tabs. Sniffer respects quoted
    # delimiters; ambiguous or single-column input falls back to standard CSV.
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return ""

    header = [cell.strip() for cell in rows[0]]
    quote = lambda value: json.dumps(value.strip(), ensure_ascii=False)  # noqa: E731
    lines = ["Première ligne du CSV (intitulés supposés) : " + " | ".join(map(quote, header))]
    for number, row in enumerate(rows[1:], start=2):
        cells = []
        for index in range(max(len(header), len(row))):
            label = (
                quote(header[index])
                if index < len(header) and header[index]
                else f"Colonne {index + 1} sans intitulé"
            )
            value = quote(row[index]) if index < len(row) else "[colonne absente]"
            cells.append(f"{label}: {value}")
        # Each row is a separate paragraph so it can stay together.
        lines.append(f"Enregistrement CSV {number} : " + " | ".join(cells))
    return "\n\n".join(lines)
