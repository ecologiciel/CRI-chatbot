"""Fixed, non-sensitive messages safe to expose to knowledge-base operators."""

from app.core.exceptions import ChunkingError, DuplicateResourceError, EmbeddingError

GENERIC = "Le traitement a échoué. Consultez les journaux du service."
EMBEDDING = "La génération des représentations a échoué. Vérifiez le service d’IA et réessayez."
CHUNKING = "Le découpage du document a échoué. Vérifiez son contenu et réessayez."
DUPLICATE = "Un document au contenu identique est déjà indexé."
TIMEOUT = "Le traitement a dépassé le délai prévu. Réessayez."
QUEUE = "Impossible de placer le document en file de traitement. Réessayez."
MALWARE = "Document rejeté par le contrôle antivirus."
SAFE_MESSAGES = frozenset({GENERIC, EMBEDDING, CHUNKING, DUPLICATE, TIMEOUT, QUEUE, MALWARE})


def safe_ingestion_error(exc: Exception) -> str:
    if isinstance(exc, EmbeddingError):
        return EMBEDDING
    if isinstance(exc, ChunkingError):
        return CHUNKING
    if isinstance(exc, DuplicateResourceError):
        return DUPLICATE
    if isinstance(exc, TimeoutError):
        return TIMEOUT
    return GENERIC


def public_ingestion_error(message: str | None) -> str | None:
    if message is None:
        return None
    return message if message in SAFE_MESSAGES else GENERIC
