"""Validation shared by file upload endpoints."""

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
