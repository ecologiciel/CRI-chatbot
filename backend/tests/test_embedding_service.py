"""Tests for EmbeddingService — all mocked, no real API calls."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import EmbeddingError
from app.core.tenant import TenantContext
from app.schemas.ai import EmbeddingRequest, EmbeddingResponse


# --- Fixtures ---

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)

DIMENSION = 768


def _make_settings(**overrides):
    """Create a mock Settings object with embedding defaults."""
    settings = MagicMock()
    settings.gemini_api_key = "test-api-key"
    settings.embedding_model = "text-embedding-004"
    settings.embedding_dimension = DIMENSION
    settings.embedding_batch_size = overrides.get("embedding_batch_size", 100)
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_mock_embed_response(count: int, dimension: int = DIMENSION):
    """Create a mock embedding API response with `count` vectors."""
    embeddings = []
    for i in range(count):
        emb = MagicMock()
        emb.values = [0.1 * (i + 1)] * dimension
        embeddings.append(emb)

    result = MagicMock()
    result.embeddings = embeddings
    result.usage_metadata = None  # Triggers word-count approximation
    return result


@pytest.fixture
def mock_redis():
    """Mock Redis client with pipeline support."""
    pipe = AsyncMock()
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, 1, True])

    redis = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipe)
    return redis, pipe


@pytest.fixture
def embedding_service(mock_redis):
    """Create an EmbeddingService with mocked client and Redis."""
    redis_mock, _ = mock_redis

    with (
        patch("app.services.ai.embeddings.genai") as mock_genai,
        patch("app.services.ai.embeddings.get_redis", return_value=redis_mock),
    ):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        from app.services.ai.embeddings import EmbeddingService

        service = EmbeddingService(_make_settings())
        service._client = mock_client
        yield service, mock_client


@pytest.fixture
def small_batch_service(mock_redis):
    """EmbeddingService with batch_size=2 for testing auto-split."""
    redis_mock, _ = mock_redis

    with (
        patch("app.services.ai.embeddings.genai") as mock_genai,
        patch("app.services.ai.embeddings.get_redis", return_value=redis_mock),
    ):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        from app.services.ai.embeddings import EmbeddingService

        service = EmbeddingService(_make_settings(embedding_batch_size=2))
        service._client = mock_client
        yield service, mock_client


# --- Tests ---


@pytest.mark.asyncio
async def test_embed_texts_success(embedding_service, mock_redis):
    """embed() returns correct number of embeddings with right dimension."""
    service, mock_client = embedding_service

    mock_client.aio.models.embed_content = AsyncMock(
        return_value=_make_mock_embed_response(3)
    )

    request = EmbeddingRequest(texts=["text 1", "text 2", "text 3"])
    response = await service.embed(request, TEST_TENANT)

    assert isinstance(response, EmbeddingResponse)
    assert len(response.embeddings) == 3
    assert len(response.embeddings[0]) == DIMENSION
    assert response.model == "text-embedding-004"
    assert response.dimension == DIMENSION
    assert response.latency_ms > 0


@pytest.mark.asyncio
async def test_embed_single(embedding_service, mock_redis):
    """embed_single() returns a single vector directly."""
    service, mock_client = embedding_service

    mock_client.aio.models.embed_content = AsyncMock(
        return_value=_make_mock_embed_response(1)
    )

    vector = await service.embed_single("search query", TEST_TENANT)

    assert isinstance(vector, list)
    assert len(vector) == DIMENSION
    assert all(isinstance(v, float) for v in vector)


@pytest.mark.asyncio
async def test_embed_batch_auto_splits(small_batch_service, mock_redis):
    """With batch_size=2, 5 texts should produce 3 API calls (2+2+1)."""
    service, mock_client = small_batch_service

    # Each call returns the appropriate number of embeddings
    mock_client.aio.models.embed_content = AsyncMock(
        side_effect=[
            _make_mock_embed_response(2),  # batch 1: texts 0-1
            _make_mock_embed_response(2),  # batch 2: texts 2-3
            _make_mock_embed_response(1),  # batch 3: text 4
        ]
    )

    request = EmbeddingRequest(
        texts=["t1", "t2", "t3", "t4", "t5"],
        task_type="RETRIEVAL_DOCUMENT",
    )
    response = await service.embed(request, TEST_TENANT)

    assert len(response.embeddings) == 5
    assert mock_client.aio.models.embed_content.call_count == 3


@pytest.mark.asyncio
async def test_embed_raises_embedding_error(embedding_service, mock_redis):
    """SDK failure → EmbeddingError raised."""
    service, mock_client = embedding_service

    mock_client.aio.models.embed_content = AsyncMock(
        side_effect=Exception("API down")
    )

    request = EmbeddingRequest(texts=["test"])
    with pytest.raises(EmbeddingError, match="Embedding generation failed"):
        await service.embed(request, TEST_TENANT)


@pytest.mark.asyncio
async def test_cost_tracking_embedding_tokens(embedding_service, mock_redis):
    """After embed(), Redis pipeline increments embedding_tokens field."""
    service, mock_client = embedding_service
    _, pipe = mock_redis

    mock_client.aio.models.embed_content = AsyncMock(
        return_value=_make_mock_embed_response(2)
    )

    request = EmbeddingRequest(texts=["hello world", "test text"])
    await service.embed(request, TEST_TENANT)

    # Verify embedding_tokens was incremented
    hincrby_calls = [str(c) for c in pipe.hincrby.call_args_list]
    assert any("embedding_tokens" in c for c in hincrby_calls)
    pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_embed_empty_raises_validation():
    """Empty text list → Pydantic validation error."""
    with pytest.raises(Exception):  # ValidationError from Pydantic
        EmbeddingRequest(texts=[])
