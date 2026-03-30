"""Unit tests for EmbeddingService — embed_single, embed_batch, batch splitting."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import EmbeddingError
from app.services.ai.embeddings import EmbeddingService

_GENAI_PATCH = "app.services.ai.embeddings.genai"
_REDIS_PATCH = "app.services.ai.embeddings.get_redis"

DIMENSION = 768


def _make_settings(batch_size=100):
    s = MagicMock()
    s.gemini_api_key = "test-key"
    s.embedding_model = "text-embedding-004"
    s.embedding_dimension = DIMENSION
    s.embedding_batch_size = batch_size
    return s


def _make_redis():
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, 1, True])
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


def _make_embed_result(count):
    embedding = MagicMock()
    embedding.values = [0.1] * DIMENSION
    result = MagicMock()
    result.embeddings = [embedding] * count
    result.usage_metadata = None
    return result


def _make_client(embed_result=None, side_effect=None):
    mock_client = MagicMock()
    mock_aio = AsyncMock()
    if side_effect:
        mock_aio.embed_content = AsyncMock(side_effect=side_effect)
    else:
        mock_aio.embed_content = AsyncMock(
            return_value=embed_result or _make_embed_result(1),
        )
    mock_client.aio.models = mock_aio
    return mock_client


class TestEmbedSingle:
    @pytest.mark.asyncio
    async def test_embed_single_returns_vector(self, tenant_context):
        client = _make_client()
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = EmbeddingService(_make_settings())
            service._client = client
            result = await service.embed_single("Bonjour", tenant_context)
        assert isinstance(result, list)
        assert len(result) == DIMENSION

    @pytest.mark.asyncio
    async def test_embed_single_uses_query_task_type(self, tenant_context):
        client = _make_client()
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = EmbeddingService(_make_settings())
            service._client = client
            await service.embed_single("query text", tenant_context)
        config = client.aio.models.embed_content.call_args.kwargs.get("config")
        assert config.task_type == "RETRIEVAL_QUERY"


class TestEmbedBatch:
    @pytest.mark.asyncio
    async def test_embed_batch_returns_correct_count(self, tenant_context):
        client = _make_client(embed_result=_make_embed_result(3))
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = EmbeddingService(_make_settings())
            service._client = client
            result = await service.embed_batch(["t1", "t2", "t3"], tenant_context)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_embed_batch_auto_splits(self, tenant_context):
        client = _make_client(
            side_effect=[
                _make_embed_result(2),
                _make_embed_result(2),
                _make_embed_result(1),
            ]
        )
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = EmbeddingService(_make_settings(batch_size=2))
            service._client = client
            result = await service.embed_batch(["a", "b", "c", "d", "e"], tenant_context)
        assert len(result) == 5
        assert client.aio.models.embed_content.call_count == 3


class TestEmbedError:
    @pytest.mark.asyncio
    async def test_api_failure_raises_embedding_error(self, tenant_context):
        client = _make_client(side_effect=RuntimeError("API error"))
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = EmbeddingService(_make_settings())
            service._client = client
            with pytest.raises(EmbeddingError, match="Embedding generation failed"):
                await service.embed_single("test", tenant_context)
