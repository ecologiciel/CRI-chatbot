"""Validation shared by file upload endpoints."""

import io
import stat
import zipfile
import zlib
from pathlib import PurePosixPath

from app.core.exceptions import ValidationError


def validate_upload_filename(filename: str | None) -> str:
    """Accept a plain filename, never a path or control characters."""
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    ):
        raise ValidationError("Nom de fichier invalide : indiquez un nom sans chemin.")
    return filename


_DOCX_MAX_MEMBERS = 2048
_DOCX_MAX_ENTRY_BYTES = 10 * 1024 * 1024
_DOCX_MAX_EXPANDED_BYTES = 50 * 1024 * 1024
_NESTED_ARCHIVE_MAGIC = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"Rar!\x1a\x07",
    b"7z\xbc\xaf\x27\x1c",
    b"\x1f\x8b",
)


def validate_docx_archive(data: bytes) -> None:
    """Bound DOCX ZIP expansion and reject encrypted or nested active archives.

    This is a structural guard, not a substitute for malware scanning.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > _DOCX_MAX_MEMBERS:
                raise ValidationError("DOCX refusé : trop de fichiers internes.")
            names = set()
            total = 0
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                if (
                    not name
                    or "\\" in name
                    or path.is_absolute()
                    or ".." in path.parts
                    or len(path.parts) > 32
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)
                    or name in names
                    or (entry.create_system == 3 and stat.S_ISLNK(entry.external_attr >> 16))
                ):
                    raise ValidationError("DOCX refusé : structure interne invalide.")
                names.add(name)
                if entry.flag_bits & 1:
                    raise ValidationError("DOCX refusé : contenu chiffré non analysable.")
                if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValidationError("DOCX refusé : compression non prise en charge.")
                if entry.file_size > _DOCX_MAX_ENTRY_BYTES:
                    raise ValidationError("DOCX refusé : fichier interne trop volumineux.")
                total += entry.file_size
                if total > _DOCX_MAX_EXPANDED_BYTES:
                    raise ValidationError("DOCX refusé : contenu décompressé trop volumineux.")
                lowered = name.lower()
                if lowered.startswith("word/embeddings/") or lowered.endswith("vbaproject.bin"):
                    raise ValidationError(
                        "DOCX refusé : contenu actif ou incorporé non pris en charge."
                    )
                if not entry.is_dir():
                    with archive.open(entry) as member:
                        if member.read(8).startswith(_NESTED_ARCHIVE_MAGIC):
                            raise ValidationError(
                                "DOCX refusé : archive interne non prise en charge."
                            )
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ValidationError("DOCX refusé : composants obligatoires absents.")
    except ValidationError:
        raise
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        zlib.error,
        RuntimeError,
        NotImplementedError,
        OSError,
        EOFError,
        ValueError,
    ) as exc:
        raise ValidationError("DOCX refusé : archive invalide ou non lisible.") from exc
