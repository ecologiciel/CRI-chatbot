"""ChunkingService — split text into overlapping chunks preserving paragraph boundaries.

Usage:
    service = get_chunking_service()
    chunks = service.chunk_text(document_text)
"""

from __future__ import annotations

import re

import structlog
import tiktoken

from app.core.exceptions import ChunkingError
from app.schemas.rag import ChunkResult

logger = structlog.get_logger()

# Module-level tokenizer (thread-safe, loaded once)
_ENCODER = tiktoken.get_encoding("cl100k_base")

# Sentence boundary pattern: split after . ! ? followed by whitespace, or at newlines
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n")

# Default chunking parameters (per CLAUDE.md §6.1)
DEFAULT_CHUNK_SIZE = 512
DEFAULT_OVERLAP = 51
MAX_CHUNK_SIZE = 768
MIN_CHUNK_SIZE = 512  # minimum tokens (below this, merge with next)


class ChunkingService:
    """Stateless text chunking with paragraph-aware boundaries and token-level overlap.

    Algorithm:
        1. Split text on double newlines → paragraphs
        2. If a paragraph exceeds max_chunk_size → split at sentence boundaries
        3. Accumulate paragraphs until chunk_size target reached
        4. Finalize chunk, start next with overlap from previous chunk
        5. Track character offsets in the original text

    Thread-safe, no I/O, no external dependencies beyond tiktoken.
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
        max_chunk_size: int = MAX_CHUNK_SIZE,
    ) -> None:
        if chunk_size <= 0 or max_chunk_size <= 0 or overlap < 0 or chunk_size > max_chunk_size:
            raise ValueError("Invalid chunking limits")
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._max_chunk_size = max_chunk_size
        self._logger = logger.bind(service="chunker")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using cl100k_base encoding."""
        return len(_ENCODER.encode(text))

    def chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
    ) -> list[ChunkResult]:
        """Split text into overlapping chunks preserving paragraph boundaries.

        Args:
            text: Full document text to chunk.
            chunk_size: Override default target chunk size in tokens.

        Returns:
            List of ChunkResult with content, indices, and token counts.

        Raises:
            ChunkingError: If text is empty or chunking fails.
        """
        if not text or not text.strip():
            raise ChunkingError(
                message="Cannot chunk empty text",
                details={"text_length": len(text) if text else 0},
            )

        target = chunk_size or self._chunk_size

        if target <= 0 or target > self._max_chunk_size:
            raise ChunkingError(message="Invalid target chunk size")

        try:
            chunks = self._chunk_exact(text, target)

            self._logger.info(
                "text_chunked",
                text_length=len(text),
                chunk_count=len(chunks),
                target_size=target,
            )

            return chunks

        except ChunkingError:
            raise
        except Exception as exc:
            raise ChunkingError(
                message=f"Chunking failed: {exc}",
                details={"text_length": len(text)},
            ) from exc

    def _chunk_exact(self, text: str, target: int) -> list[ChunkResult]:
        """Return exact source slices, preferring paragraph and sentence boundaries."""
        chunks: list[ChunkResult] = []
        headings: list[tuple[int, tuple[str, ...]]] = []
        path: list[str] = []
        offset = 0
        fence: str | None = None
        for line in text.splitlines(keepends=True):
            marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
            if marker:
                if fence is None:
                    fence = marker.group(1)[0]
                elif marker.group(1)[0] == fence:
                    fence = None
            elif fence is None:
                heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n)?$", line)
                if heading:
                    level = len(heading.group(1))
                    path = path[: level - 1] + [heading.group(2)]
                    headings.append((offset, tuple(path)))
            offset += len(line)
        start = 0
        length = len(text)
        while start < length:
            remaining = text[start:]
            if self.count_tokens(remaining) <= target:
                end = length
            else:
                # Find a bounded prefix on Unicode character boundaries.
                low, high = 1, length - start
                while low < high:
                    mid = (low + high + 1) // 2
                    if self.count_tokens(text[start:start + mid]) <= target:
                        low = mid
                    else:
                        high = mid - 1
                end = start + low
                # BPE token counts are not strictly monotonic; verify the bound.
                while end > start and self.count_tokens(text[start:end]) > target:
                    end -= 1
                if end == start:
                    raise ChunkingError(message="Cannot split text within token limit")
                prefix = text[start:end]
                paragraphs = list(re.finditer(r"\n\s*\n", prefix))
                sentences = list(re.finditer(r"(?<=[.!?؟])\s+", prefix))
                # Avoid selecting a boundary so early it yields tiny chunks.
                for candidates in (paragraphs, sentences):
                    if candidates and candidates[-1].end() >= len(prefix) // 2:
                        end = start + candidates[-1].end()
                        break

            next_heading = next((pos for pos, _ in headings if start < pos < end), None)
            if next_heading is not None:
                end = next_heading
            section = next((p for pos, p in reversed(headings) if pos <= start), ())
            content = text[start:end]
            chunks.append(ChunkResult(content, len(chunks), self.count_tokens(content), start, end, section))
            if end == length:
                break
            next_start = end
            if self._overlap and next_heading is None:
                # Walk backwards by words while respecting the overlap budget.
                for match in reversed(list(re.finditer(r"\S+\s*", content))):
                    candidate = start + match.start()
                    if candidate <= start or self.count_tokens(text[candidate:end]) > self._overlap:
                        break
                    next_start = candidate
            start = next_start
        return chunks

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split text on double newlines, preserving non-empty paragraphs."""
        raw = re.split(r"\n\s*\n", text)
        return [p.strip() for p in raw if p.strip()]

    def _split_sentences(self, text: str) -> list[str]:
        """Split text on sentence boundaries (. ! ? followed by space, or newlines)."""
        parts = _SENTENCE_RE.split(text)
        return [s.strip() for s in parts if s.strip()]

    def _split_oversized(self, paragraphs: list[str]) -> list[str]:
        """Split any paragraph exceeding max_chunk_size at sentence boundaries."""
        segments: list[str] = []
        for para in paragraphs:
            if self.count_tokens(para) <= self._max_chunk_size:
                segments.append(para)
            else:
                # Split at sentence boundaries
                sentences = self._split_sentences(para)
                if not sentences:
                    # No sentence boundaries found — keep as-is
                    segments.append(para)
                    continue

                # Accumulate sentences up to max_chunk_size
                buffer: list[str] = []
                buffer_tokens = 0
                expanded = [part for sentence in sentences for part in self._split_to_limit(sentence)]
                for sentence in expanded:
                    stokens = self.count_tokens(sentence)
                    if buffer and self.count_tokens(" ".join(buffer + [sentence])) > self._max_chunk_size:
                        segments.append(" ".join(buffer))
                        buffer = [sentence]
                        buffer_tokens = stokens
                    else:
                        buffer.append(sentence)
                        buffer_tokens += stokens
                if buffer:
                    segments.append(" ".join(buffer))

        return segments

    def _split_to_limit(self, text: str) -> list[str]:
        """Split a long sentence on character boundaries, preserving Unicode text."""
        parts: list[str] = []
        while text and self.count_tokens(text) > self._max_chunk_size:
            # Repeated halving guarantees progress and avoids breaking UTF-8
            # characters when the tokenizer splits their byte representation.
            end = len(text) // 2
            while end > 1 and self.count_tokens(text[:end]) > self._max_chunk_size:
                end //= 2
            if self.count_tokens(text[:end]) > self._max_chunk_size:
                raise ChunkingError(message="Cannot split text within token limit")
            parts.append(text[:end])
            text = text[end:]
        if text:
            parts.append(text)
        return parts

    def _accumulate_chunks(
        self,
        segments: list[str],
        target: int,
        original_text: str,
    ) -> list[ChunkResult]:
        """Accumulate segments into chunks with overlap.

        Builds chunks by accumulating paragraphs/segments until the target
        token count is reached, then creates overlap by carrying forward
        trailing segments from the previous chunk.
        """
        chunks: list[ChunkResult] = []
        current_segments: list[str] = []
        current_tokens = 0
        overlap_segments: list[str] = []  # segments to prepend for overlap

        for segment in segments:
            seg_tokens = self.count_tokens(segment)

            # If adding this segment would exceed target and we have content,
            # finalize the current chunk
            if current_segments and self.count_tokens("\n\n".join(current_segments + [segment])) > min(target, self._max_chunk_size):
                chunk_content = "\n\n".join(current_segments)
                chunk = self._make_chunk_result(
                    content=chunk_content,
                    chunk_index=len(chunks),
                    original_text=original_text,
                )
                chunks.append(chunk)

                # Build overlap: take trailing segments from current chunk
                overlap_segments = self._get_overlap_segments(current_segments)

                while overlap_segments and self.count_tokens(
                    "\n\n".join(overlap_segments + [segment])
                ) > self._max_chunk_size:
                    overlap_segments.pop(0)

                # Start new chunk with overlap
                current_segments = overlap_segments + [segment]
                current_tokens = sum(self.count_tokens(s) for s in current_segments)
            else:
                current_segments.append(segment)
                current_tokens += seg_tokens

        # Finalize last chunk
        if current_segments:
            chunk_content = "\n\n".join(current_segments)
            chunk = self._make_chunk_result(
                content=chunk_content,
                chunk_index=len(chunks),
                original_text=original_text,
            )
            chunks.append(chunk)

        return chunks

    def _get_overlap_segments(self, segments: list[str]) -> list[str]:
        """Get trailing segments that sum to approximately overlap tokens."""
        overlap_segs: list[str] = []
        overlap_tokens = 0

        for seg in reversed(segments):
            seg_tokens = self.count_tokens(seg)
            if overlap_tokens + seg_tokens > self._overlap:
                break
            overlap_segs.insert(0, seg)
            overlap_tokens += seg_tokens

        return overlap_segs

    def _make_chunk_result(
        self,
        content: str,
        chunk_index: int,
        original_text: str,
    ) -> ChunkResult:
        """Create a ChunkResult with character offsets in the original text."""
        # Find the first unique segment to locate in original text
        # Use the content without overlap to find the true start
        start_char = original_text.find(content[:100])
        if start_char == -1:
            # Overlap content may not appear verbatim — find the core content
            # Use a shorter prefix for matching
            first_line = content.split("\n")[0][:80]
            start_char = original_text.find(first_line)
            if start_char == -1:
                start_char = 0

        end_char = min(start_char + len(content), len(original_text))

        return ChunkResult(
            content=content,
            chunk_index=chunk_index,
            token_count=self.count_tokens(content),
            start_char=start_char,
            end_char=end_char,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_chunking_service: ChunkingService | None = None


def get_chunking_service() -> ChunkingService:
    """Get or create the ChunkingService singleton."""
    global _chunking_service  # noqa: PLW0603
    if _chunking_service is None:
        _chunking_service = ChunkingService()
    return _chunking_service
