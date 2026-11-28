"""Security and protocol tests for the same-host WhatsApp relay."""
import logging

import httpx
import pytest
import pytest_asyncio

from app.services.whatsapp import local_relay


@pytest_asyncio.fixture
async def relay_client():
    seen = []

    async def upstream(request):
        seen.append(request)
        return httpx.Response(200, content=b"challenge" if request.method == "GET" else b'{"status":"ok"}')

    internal = httpx.AsyncClient(transport=httpx.MockTransport(upstream), trust_env=False)
    local_relay.app.state.relay_secret = "fixture-relay-secret"
    local_relay.app.state.relay_client = internal
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=local_relay.app), base_url="https://relay.test") as client:
        yield client, seen
    await internal.aclose()


@pytest.mark.asyncio
async def test_challenge_preserves_query_and_injects_secret_without_logging(relay_client, caplog):
    client, seen = relay_client
    with caplog.at_level(logging.INFO):
        result = await client.get("/wa/whatsapp/tenant/onssa?hub.mode=subscribe&hub.verify_token=fixture-token&hub.challenge=abc")
    assert result.status_code == 200 and result.text == "challenge"
    assert result.headers["cache-control"] == "no-store"
    assert seen[0].url.path == "/api/v1/webhook/whatsapp/tenant/onssa"
    assert seen[0].url.query == b"hub.mode=subscribe&hub.verify_token=fixture-token&hub.challenge=abc"
    assert seen[0].headers["x-demo-webhook-proxy"] == "fixture-relay-secret"
    assert "fixture-token" not in caplog.text and "fixture-relay-secret" not in caplog.text


@pytest.mark.asyncio
async def test_post_preserves_exact_bytes_and_signature_but_discards_untrusted_headers(relay_client):
    client, seen = relay_client
    signature = "sha256=" + "a" * 64
    body = b'{ "text": "\\u00e9", "x": 1 }'
    result = await client.post("/wa/whatsapp/tenant/onssa", content=body,
                               headers={"X-Hub-Signature-256": signature,
                                        "X-Demo-Webhook-Proxy": "attacker", "Cookie": "sensitive=1"})
    assert result.status_code == 200
    assert seen[0].content == body
    assert seen[0].headers["x-hub-signature-256"] == signature
    assert seen[0].headers["x-demo-webhook-proxy"] == "fixture-relay-secret"
    assert "cookie" not in seen[0].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/wa/whatsapp/tenant/ONSSA", "/wa/whatsapp/tenant/_bad", "/wa/whatsapp/tenant/onssa/extra", "/wa/whatsapp"])
async def test_invalid_paths_never_reach_backend(relay_client, path):
    client, seen = relay_client
    assert (await client.get(path)).status_code == 404
    assert not seen


@pytest.mark.asyncio
@pytest.mark.parametrize("slug", ["a", "1", "institution_1"])
async def test_valid_tenant_slugs_are_forwarded(relay_client, slug):
    client, seen = relay_client
    assert (await client.get(f"/wa/whatsapp/tenant/{slug}")).status_code == 200
    assert seen[0].url.path.endswith(f"/{slug}")


@pytest.mark.asyncio
async def test_unsigned_duplicate_and_oversized_requests_never_reach_backend(relay_client):
    client, seen = relay_client
    path = "/wa/whatsapp/tenant/onssa"
    signature = "sha256=" + "a" * 64
    assert (await client.post(path, content=b"{}")).status_code == 403
    assert (await client.post(path, content=b"{}", headers=[("x-hub-signature-256", signature), ("x-hub-signature-256", signature)])).status_code == 403
    assert (await client.post(path, content=b"x" * (local_relay.MAX_BODY_BYTES + 1), headers={"x-hub-signature-256": signature})).status_code == 413
    assert (await client.get(path + "?x=" + "x" * local_relay.MAX_QUERY_BYTES)).status_code == 400
    assert not seen


@pytest.mark.asyncio
async def test_backend_errors_and_redirects_are_not_reflected(relay_client):
    client, _ = relay_client
    async def failure(_request):
        return httpx.Response(503, content=b"sensitive backend detail")
    previous = local_relay.app.state.relay_client
    local_relay.app.state.relay_client = httpx.AsyncClient(transport=httpx.MockTransport(failure))
    try:
        response = await client.get("/wa/whatsapp/tenant/onssa?hub.verify_token=fixture-token")
        assert response.status_code == 503
        assert "sensitive" not in response.text and "fixture-token" not in response.text
    finally:
        await local_relay.app.state.relay_client.aclose()
        local_relay.app.state.relay_client = previous


@pytest.mark.asyncio
async def test_saturation_fails_closed(relay_client, monkeypatch):
    import asyncio
    client, seen = relay_client
    monkeypatch.setattr(local_relay, "_slots", asyncio.Semaphore(0))
    assert (await client.get("/wa/whatsapp/tenant/onssa")).status_code == 503
    assert not seen


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", ["", "bad\nsecret", "bad secret", "é", "a" * 4097])
async def test_invalid_relay_secret_refuses_startup(monkeypatch, secret):
    monkeypatch.setenv("WEBHOOK_PROXY_SHARED_SECRET", secret)
    with pytest.raises(RuntimeError, match="configuration unavailable"):
        async with local_relay.lifespan(local_relay.app):
            pass
