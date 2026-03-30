"""Tests for GeminiService — all mocked, no real API calls."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import GeminiError
from app.core.tenant import TenantContext
from app.schemas.ai import GeminiRequest, GeminiResponse

# --- Fixtures ---

TEST_TENANT = TenantContext(
    id=uuid.uuid4(),
    slug="rabat",
    name="CRI Rabat",
    status="active",
    whatsapp_config=None,
)


def _make_settings(**overrides):
    """Create a mock Settings object with AI defaults."""
    settings = MagicMock()
    settings.gemini_api_key = "test-api-key"
    settings.gemini_model = "gemini-2.5-flash"
    settings.gemini_max_output_tokens = 2048
    settings.gemini_temperature = 0.3
    settings.gemini_timeout = 30.0
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_mock_response(
    text="Hello world", input_tokens=10, output_tokens=5, finish_reason_name="STOP"
):
    """Create a mock Gemini API response."""
    usage = MagicMock()
    usage.prompt_token_count = input_tokens
    usage.candidates_token_count = output_tokens

    finish_reason = MagicMock()
    finish_reason.name = finish_reason_name

    candidate = MagicMock()
    candidate.finish_reason = finish_reason

    response = MagicMock()
    response.text = text
    response.usage_metadata = usage
    response.candidates = [candidate]
    return response


@pytest.fixture
def mock_redis():
    """Mock Redis client with pipeline support."""
    pipe = AsyncMock()
    pipe.hincrby = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, 1, 1, True])

    redis = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipe)
    redis.hgetall = AsyncMock(return_value={})
    return redis, pipe


@pytest.fixture
def gemini_service(mock_redis):
    """Create a GeminiService with mocked client and Redis."""
    redis_mock, _ = mock_redis

    with (
        patch("app.services.ai.gemini.genai") as mock_genai,
        patch("app.services.ai.gemini.get_redis", return_value=redis_mock),
    ):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client

        from app.services.ai.gemini import GeminiService

        service = GeminiService(_make_settings())
        # Replace the client with our mock
        service._client = mock_client
        yield service, mock_client


# --- Tests ---


@pytest.mark.asyncio
async def test_generate_success(gemini_service, mock_redis):
    """generate() returns a valid GeminiResponse with correct fields."""
    service, mock_client = gemini_service

    mock_response = _make_mock_response(text="Bienvenue au CRI", input_tokens=15, output_tokens=8)
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    request = GeminiRequest(contents="Bonjour, comment investir?")
    response = await service.generate(request, TEST_TENANT)

    assert isinstance(response, GeminiResponse)
    assert response.text == "Bienvenue au CRI"
    assert response.input_tokens == 15
    assert response.output_tokens == 8
    assert response.total_tokens == 23
    assert response.model == "gemini-2.5-flash"
    assert response.latency_ms >= 0
    assert response.finish_reason == "STOP"


@pytest.mark.asyncio
async def test_generate_with_overrides(gemini_service, mock_redis):
    """Custom temperature and max_output_tokens are passed to the SDK config."""
    service, mock_client = gemini_service

    mock_client.aio.models.generate_content = AsyncMock(return_value=_make_mock_response())

    request = GeminiRequest(
        contents="Test prompt",
        temperature=0.9,
        max_output_tokens=512,
        system_instruction="Be creative",
    )
    await service.generate(request, TEST_TENANT)

    # Verify the config passed to the SDK
    call_kwargs = mock_client.aio.models.generate_content.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config")
    assert config.temperature == 0.9
    assert config.max_output_tokens == 512
    assert config.system_instruction == "Be creative"


@pytest.mark.asyncio
async def test_generate_retries_on_rate_limit(gemini_service, mock_redis):
    """ResourceExhausted 2x then success → retry works."""
    service, mock_client = gemini_service

    from google.api_core.exceptions import ResourceExhausted

    error = ResourceExhausted("Rate limited")

    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[error, error, _make_mock_response(text="OK after retry")]
    )

    # Disable retry wait for test speed
    from tenacity import wait_none

    service._generate_with_retry.retry.wait = wait_none()

    request = GeminiRequest(contents="Test retry")
    response = await service.generate(request, TEST_TENANT)
    assert response.text == "OK after retry"
    assert mock_client.aio.models.generate_content.call_count == 3


@pytest.mark.asyncio
async def test_generate_raises_gemini_error_after_exhaustion(gemini_service, mock_redis):
    """3x failure → GeminiError raised."""
    service, mock_client = gemini_service

    mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("API down"))

    request = GeminiRequest(contents="Test failure")
    with pytest.raises(GeminiError, match="Gemini generation failed"):
        await service.generate(request, TEST_TENANT)


@pytest.mark.asyncio
async def test_cost_tracking_redis(gemini_service, mock_redis):
    """After generate(), Redis pipeline hincrby is called with correct token values."""
    service, mock_client = gemini_service
    _, pipe = mock_redis

    mock_client.aio.models.generate_content = AsyncMock(
        return_value=_make_mock_response(input_tokens=20, output_tokens=10)
    )

    request = GeminiRequest(contents="Cost test")
    await service.generate(request, TEST_TENANT)

    # Verify Redis pipeline was used with correct token values
    assert pipe.hincrby.call_count >= 3
    # Extract all hincrby calls and verify token fields
    calls = [str(c) for c in pipe.hincrby.call_args_list]
    assert any("input_tokens" in c and "20" in c for c in calls)
    assert any("output_tokens" in c and "10" in c for c in calls)
    assert any("request_count" in c for c in calls)
    pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_classify_intent(gemini_service, mock_redis):
    """classify_intent returns a lowercase intent label."""
    service, mock_client = gemini_service

    mock_client.aio.models.generate_content = AsyncMock(
        return_value=_make_mock_response(text="  FAQ  ")
    )

    result = await service.classify_intent("Quels sont les avantages fiscaux?", TEST_TENANT)
    assert result == "faq"


@pytest.mark.asyncio
async def test_no_pii_in_logs(gemini_service, mock_redis, capfd):
    """Log output must NOT contain prompt content or response text."""
    service, mock_client = gemini_service

    sensitive_prompt = "Mon CIN est AB123456 et mon numéro 0612345678"
    mock_client.aio.models.generate_content = AsyncMock(
        return_value=_make_mock_response(text="Réponse avec données sensibles")
    )

    with patch("app.services.ai.gemini.logger") as mock_logger:
        request = GeminiRequest(contents=sensitive_prompt)
        await service.generate(request, TEST_TENANT)

        # Check all log calls — none should contain the prompt or response text
        for call in mock_logger.method_calls:
            call_str = str(call)
            assert "AB123456" not in call_str
            assert "0612345678" not in call_str
            assert "données sensibles" not in call_str
