"""Unit tests for GeminiService — generate, classify, cost tracking, retry."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import GeminiError
from app.schemas.ai import GeminiRequest, GeminiResponse
from app.services.ai.gemini import GeminiService
from tests.unit.conftest import make_mock_gemini_response

_GENAI_PATCH = "app.services.ai.gemini.genai"
_REDIS_PATCH = "app.services.ai.gemini.get_redis"


def _make_settings():
    s = MagicMock()
    s.gemini_api_key = "test-key"
    s.gemini_model = "gemini-2.5-flash"
    s.gemini_max_output_tokens = 1024
    s.gemini_temperature = 0.3
    return s


def _make_redis():
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    pipe = MagicMock()
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, 1, 1, True])
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


def _make_client(sdk_response=None):
    mock_client = MagicMock()
    mock_aio = AsyncMock()
    mock_aio.generate_content = AsyncMock(
        return_value=sdk_response or make_mock_gemini_response(),
    )
    mock_client.aio.models = mock_aio
    return mock_client


class TestGenerate:
    @pytest.mark.asyncio
    async def test_generate_success(self, tenant_context):
        sdk_resp = make_mock_gemini_response(text="Bonjour", input_tokens=15, output_tokens=8)
        client = _make_client(sdk_response=sdk_resp)
        redis = _make_redis()

        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=redis):
            service = GeminiService(_make_settings())
            service._client = client
            result = await service.generate(GeminiRequest(contents="Bonjour"), tenant_context)

        assert isinstance(result, GeminiResponse)
        assert result.text == "Bonjour"
        assert result.input_tokens == 15
        assert result.output_tokens == 8
        assert result.model == "gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_generate_with_system_instruction(self, tenant_context):
        client = _make_client()
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = GeminiService(_make_settings())
            service._client = client
            await service.generate(
                GeminiRequest(contents="Test", system_instruction="Tu es un assistant."),
                tenant_context,
            )
        assert client.aio.models.generate_content.call_args is not None


class TestGenerateSimple:
    @pytest.mark.asyncio
    async def test_generate_simple_returns_text(self, tenant_context):
        client = _make_client(sdk_response=make_mock_gemini_response(text="  SARL  "))
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = GeminiService(_make_settings())
            service._client = client
            result = await service.generate_simple("SARL?", tenant_context)
        assert result == "  SARL  "


class TestClassifyIntent:
    @pytest.mark.asyncio
    async def test_classify_intent_lowercases(self, tenant_context):
        client = _make_client(sdk_response=make_mock_gemini_response(text="  FAQ  "))
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = GeminiService(_make_settings())
            service._client = client
            result = await service.classify_intent("Bonjour", tenant_context)
        assert result == "faq"


class TestRetryExhaustion:
    @pytest.mark.asyncio
    async def test_retry_exhaustion_raises_gemini_error(self, tenant_context):
        client = _make_client()
        client.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("API down"))
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=_make_redis()):
            service = GeminiService(_make_settings())
            service._client = client
            with pytest.raises(GeminiError, match="Gemini generation failed"):
                await service.generate(GeminiRequest(contents="test"), tenant_context)


class TestGetTenantUsage:
    @pytest.mark.asyncio
    async def test_get_tenant_usage_returns_cost_snapshot(self, tenant_context):
        redis = _make_redis()
        redis.hgetall = AsyncMock(
            return_value={
                "input_tokens": "1000",
                "output_tokens": "500",
                "embedding_tokens": "200",
                "request_count": "50",
            }
        )
        with patch(_GENAI_PATCH), patch(_REDIS_PATCH, return_value=redis):
            service = GeminiService(_make_settings())
            result = await service.get_tenant_usage(tenant_context, month="2026-03")
        assert result.input_tokens == 1000
        assert result.output_tokens == 500
        assert result.tenant_slug == "rabat"
