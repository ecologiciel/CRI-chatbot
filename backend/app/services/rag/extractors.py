"""Text extraction from uploaded KB documents.

Supports PDF, DOCX, TXT, MD, CSV. Each extractor reads raw bytes
and returns the full text content. Raises IngestionError on failure.

Usage:
    text = extract_text(file_bytes, "guide_investisseur.pdf")
"""

from __future__ import annotations

import csv
import io
from pathlib import PurePosixPath

from app.core.exceptions import IngestionError

SUPPORTED_EXTENSIONS: set[str] = {".pdf", ".docx", ".txt", ".md", ".csv"}


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
    """Extract text from DOCX using python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(data))
    paragraphs: list[str] = []
    for para in doc.paragraphs:
        if para.text.strip():
            paragraphs.append(para.text)

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

    reader = csv.reader(io.StringIO(text))
    lines: list[str] = []
    for row in reader:
        line = " | ".join(cell.strip() for cell in row if cell.strip())
        if line:
            lines.append(line)

    return "\n".join(lines)
