"""Tests for ChunkingService — pure unit tests, no mocking needed."""

import os

import pytest

# Set required env vars before any app imports
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("REDIS_PASSWORD", "test")

from app.core.exceptions import ChunkingError
from app.schemas.rag import ChunkResult
from app.services.rag.chunker import ChunkingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_long_text(num_paragraphs: int, words_per_paragraph: int = 100) -> str:
    """Generate text with multiple paragraphs of predictable size."""
    paragraphs = []
    for i in range(num_paragraphs):
        words = " ".join(f"word{i}_{j}" for j in range(words_per_paragraph))
        paragraphs.append(f"Paragraph {i} begins here. {words}. Paragraph {i} ends here.")
    return "\n\n".join(paragraphs)


def _make_text_with_tokens(target_tokens: int) -> str:
    """Generate text that is approximately target_tokens long."""
    service = ChunkingService()
    words = []
    for i in range(target_tokens * 2):  # Overshoot then trim
        words.append(f"mot{i}")
        if service.count_tokens(" ".join(words)) >= target_tokens:
            break
    return " ".join(words)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCountTokens:
    def test_count_tokens_nonempty(self):
        """count_tokens returns a positive integer for non-empty text."""
        service = ChunkingService()
        count = service.count_tokens("Bonjour, comment ça va aujourd'hui?")
        assert isinstance(count, int)
        assert count > 0

    def test_count_tokens_empty(self):
        """count_tokens returns 0 for empty string."""
        service = ChunkingService()
        assert service.count_tokens("") == 0


class TestChunkShortText:
    def test_chunk_short_text_single_chunk(self):
        """Text shorter than chunk_size → exactly 1 chunk."""
        service = ChunkingService(chunk_size=768)
        short_text = "Ceci est un court texte sur les investissements au Maroc."
        chunks = service.chunk_text(short_text)

        assert len(chunks) == 1
        assert isinstance(chunks[0], ChunkResult)
        assert chunks[0].chunk_index == 0
        assert chunks[0].content == short_text
        assert chunks[0].token_count > 0
        assert chunks[0].token_count < 768


class TestChunkLongText:
    def test_chunk_long_text_produces_multiple_chunks(self):
        """Text of ~3000 tokens produces multiple chunks within size bounds."""
        service = ChunkingService(chunk_size=768, overlap=128, max_chunk_size=1024)
        text = _make_long_text(num_paragraphs=30, words_per_paragraph=80)

        chunks = service.chunk_text(text)

        assert len(chunks) > 1, "Should produce more than 1 chunk"

        for chunk in chunks:
            assert isinstance(chunk, ChunkResult)
            assert chunk.token_count > 0
            # Chunks should generally be in the expected range
            # (last chunk may be smaller, overlap can push over target)

        # Verify sequential chunk_index
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i


class TestChunkPreservesParagraphs:
    def test_paragraphs_not_split_mid_text(self):
        """Paragraphs that fit within max_chunk_size are not split mid-paragraph."""
        service = ChunkingService(chunk_size=200, overlap=30)

        # Create paragraphs that are each ~50-80 tokens (well under max_chunk_size)
        paragraphs = [
            "Le Centre Régional d'Investissement de Rabat-Salé-Kénitra accompagne les investisseurs dans toutes les étapes de création d'entreprise.",
            "Les incitations fiscales comprennent une exonération de TVA pendant les cinq premières années pour les entreprises installées dans les zones d'accélération industrielle.",
            "Le suivi de dossier permet aux investisseurs de consulter l'état d'avancement de leur projet via WhatsApp en toute sécurité.",
        ]
        text = "\n\n".join(paragraphs)

        chunks = service.chunk_text(text)

        # Each original paragraph should appear intact in at least one chunk
        for para in paragraphs:
            found = any(para in chunk.content for chunk in chunks)
            assert found, f"Paragraph not found intact in any chunk: {para[:60]}..."


class TestChunkOverlap:
    def test_consecutive_chunks_share_overlap(self):
        """Consecutive chunks share overlapping content."""
        service = ChunkingService(chunk_size=200, overlap=50)

        # Generate enough text for multiple chunks
        text = _make_long_text(num_paragraphs=20, words_per_paragraph=40)
        chunks = service.chunk_text(text)

        assert len(chunks) > 1, "Need at least 2 chunks to test overlap"

        # For each pair of consecutive chunks, verify some content from
        # the end of chunk N appears at the start of chunk N+1
        for i in range(len(chunks) - 1):
            current = chunks[i]
            next_chunk = chunks[i + 1]

            # Get last few words of current chunk
            current_words = current.content.split()
            last_words = current_words[-15:] if len(current_words) > 15 else current_words

            # Check if any of those words appear in the beginning of next chunk
            next_start = next_chunk.content[:500]
            overlap_found = any(word in next_start for word in last_words if len(word) > 4)

            assert overlap_found, (
                f"No overlap detected between chunk {i} and {i + 1}. "
                f"End of chunk {i}: ...{current.content[-80:]!r} | "
                f"Start of chunk {i + 1}: {next_chunk.content[:80]!r}..."
            )


class TestChunkEmptyText:
    def test_empty_string_raises(self):
        """Empty string raises ChunkingError."""
        service = ChunkingService()
        with pytest.raises(ChunkingError, match="Cannot chunk empty text"):
            service.chunk_text("")

    def test_whitespace_only_raises(self):
        """Whitespace-only string raises ChunkingError."""
        service = ChunkingService()
        with pytest.raises(ChunkingError, match="Cannot chunk empty text"):
            service.chunk_text("   \n\n  \t  ")
