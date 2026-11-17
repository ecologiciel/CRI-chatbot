"""Regression tests for external-data privacy and user-verifiable citations."""

import pytest

from app.api.v1.kb import _validate_file_signature
from app.schemas.rag import ConversationTurn, RetrievedChunk
from app.services.rag.generation import GenerationService
from app.services.rag.prompts import PromptTemplates
from app.services.whatsapp.handler import MessageHandler


def test_file_signature_rejects_mismatched_pdf() -> None:
    with pytest.raises(Exception, match="PDF"):
        _validate_file_signature(".pdf", b"not a pdf")


def test_file_signature_accepts_pdf_header() -> None:
    _validate_file_signature(".pdf", b"%PDF-1.7\n")


def test_source_command_is_exact_and_accent_insensitive() -> None:
    assert MessageHandler._is_source_command("Source")
    assert MessageHandler._is_source_command(" SOURCE ")
    assert not MessageHandler._is_source_command("Quelle est votre source ?")


def test_citations_are_deduplicated_and_limited() -> None:
    chunks = [
        RetrievedChunk(
            chunk_id=str(index),
            document_id=f"document-{index // 2}",
            content="content",
            score=0.9,
            metadata={
                "title": f"Document {index // 2}",
                "source_authority": "CRI",
                "source_reference": f"REF-{index // 2}",
                "source_version": "1.0",
                "published_at": "2026-01-01",
            },
        )
        for index in range(8)
    ]
    sources = GenerationService._build_sources(chunks)
    assert [source["document_id"] for source in sources] == [
        "document-0",
        "document-1",
        "document-2",
    ]


def test_history_masking_removes_phone_before_external_prompt() -> None:
    service = object.__new__(GenerationService)
    history = [ConversationTurn(role="user", content="Appelez-moi au 0612345678")]
    masked = service._anonymize_history(history)
    assert "0612345678" not in masked[0].content
    assert "[PHONE_1]" in masked[0].content


def test_source_message_contains_at_most_three_citations() -> None:
    sources = [
        {"title": f"Doc {index}", "version": "1", "published_at": "2026-01-01"}
        for index in range(5)
    ]
    message = PromptTemplates.format_sources_message(sources)
    assert "1. Doc 0" in message
    assert "3. Doc 2" in message
    assert "4. Doc 3" not in message
