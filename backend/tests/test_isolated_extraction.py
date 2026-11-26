"""Exercise the extraction boundary and fail-closed client behavior."""

from unittest.mock import patch

import httpx
import pytest

from app.core.exceptions import IngestionError
from app.services.rag.extractor_service import MAX_INPUT, app
from app.services.rag.remote_extraction import extract_remotely


@pytest.mark.asyncio
async def test_private_endpoint_rejects_oversize_and_unsupported_before_child():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        with patch("app.services.rag.extractor_service._run_child") as child:
            large = await c.post(
                "/extract", headers={"X-File-Extension": ".txt"}, content=b"x" * (MAX_INPUT + 1)
            )
            unsupported = await c.post(
                "/extract", headers={"X-File-Extension": ".exe"}, content=b"x"
            )
        assert large.status_code == 413
        assert unsupported.status_code == 415
        child.assert_not_called()


@pytest.mark.asyncio
async def test_worker_client_validates_text_and_page_offsets():
    def response(request):
        assert request.headers["X-File-Extension"] == ".pdf"
        return httpx.Response(
            200, json={"text": "alpha beta", "pages": [{"number": 2, "start": 0, "end": 5}]}
        )

    actual_client = httpx.AsyncClient
    with patch(
        "app.services.rag.remote_extraction.httpx.AsyncClient",
        side_effect=lambda **kw: actual_client(transport=httpx.MockTransport(response), **kw),
    ):
        result = await extract_remotely(b"pdf bytes", "example.pdf", "http://extractor:8080")
    assert result.text == "alpha beta"
    assert (result.pages[0].number, result.pages[0].start, result.pages[0].end) == (2, 0, 5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"text": "alpha", "pages": [{"number": 1, "start": 0, "end": 99}]},
        {"text": "", "pages": []},
        {"text": "alpha"},
    ],
)
async def test_worker_rejects_invalid_service_response(payload):
    actual_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with patch(
        "app.services.rag.remote_extraction.httpx.AsyncClient",
        side_effect=lambda **kw: actual_client(transport=transport, **kw),
    ):
        with pytest.raises(IngestionError):
            await extract_remotely(b"data", "example.txt", "http://extractor:8080")


@pytest.mark.asyncio
async def test_worker_does_not_fall_back_if_extractor_unavailable():
    def fail(request):
        raise httpx.ConnectError("unavailable", request=request)

    actual_client = httpx.AsyncClient
    with patch(
        "app.services.rag.remote_extraction.httpx.AsyncClient",
        side_effect=lambda **kw: actual_client(transport=httpx.MockTransport(fail), **kw),
    ):
        with pytest.raises(IngestionError):
            await extract_remotely(b"data", "example.txt", "http://extractor:8080")
