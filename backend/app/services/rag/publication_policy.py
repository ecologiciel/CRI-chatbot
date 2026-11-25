"""Checks shared by API approval and worker publication."""

from datetime import date

from app.core.exceptions import ValidationError
from app.models.enums import KBDocumentStatus
from app.models.kb import KBDocument


def ensure_publishable(document: KBDocument) -> None:
    missing = [
        name
        for name, value in {
            "source_authority": document.source_authority,
            "source_reference": document.source_reference,
            "source_version": document.source_version,
            "published_at": document.published_at,
        }.items()
        if not value
    ]
    if missing:
        raise ValidationError(
            "Les métadonnées de preuve sont incomplètes.", details={"missing": missing}
        )
    if document.expires_at and document.expires_at < date.today():
        raise ValidationError("Ce document est expiré et ne peut pas être publié.")


def ensure_validated(document: KBDocument) -> None:
    if not document.validated_at or not document.validated_by:
        raise ValidationError("Le document doit être validé avant sa publication.")
    if document.status in {
        KBDocumentStatus.pending_validation,
        KBDocumentStatus.rejected,
        KBDocumentStatus.expired,
    }:
        raise ValidationError("Le document ne peut pas être publié dans son état actuel.")
    ensure_publishable(document)
