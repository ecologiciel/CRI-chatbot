"""AI service package — Gemini generation and embedding services."""

from app.services.ai.embeddings import EmbeddingService, get_embedding_service
from app.services.ai.gemini import GeminiService, get_gemini_service

__all__ = [
    "EmbeddingService",
    "GeminiService",
    "get_embedding_service",
    "get_gemini_service",
]
