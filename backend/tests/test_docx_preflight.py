"""Document archive limits must be enforced before extraction."""

import io
import warnings
import zipfile

import pytest
from docx import Document

from app.core.exceptions import ValidationError
from app.core.uploads import validate_docx_archive
from app.services.rag.extractors import extract_text


def make_archive(extra):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", "document")
        for name, data in extra:
            archive.writestr(name, data)
    return output.getvalue()


def test_normal_docx_passes_and_can_be_extracted():
    document = Document()
    document.add_paragraph("Contrôle phytosanitaire")
    output = io.BytesIO()
    document.save(output)
    validate_docx_archive(output.getvalue())
    assert "Contrôle phytosanitaire" in extract_text(output.getvalue(), "guide.docx")


@pytest.mark.parametrize(
    "entries",
    [
        [("word/media/large.bin", b"x" * (11 * 1024 * 1024))],
        [("word/media/archive.bin", b"PK\x03\x04archive")],
        [("word/embeddings/object.bin", b"object")],
        [("word/vbaProject.bin", b"macro")],
        [("../outside", b"data")],
        [(f"item{i}", b"") for i in range(2047)],
    ],
)
def test_unsafe_archives_refused_before_extraction(entries):
    data = make_archive(entries)
    with pytest.raises(ValidationError):
        validate_docx_archive(data)
    with pytest.raises(ValidationError):
        extract_text(data, "guide.docx")


def test_invalid_and_duplicate_archive_rejected():
    with pytest.raises(ValidationError):
        validate_docx_archive(b"PK\x03\x04invalid")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        duplicate = make_archive([("word/document.xml", b"duplicate")])
    with pytest.raises(ValidationError):
        validate_docx_archive(duplicate)
