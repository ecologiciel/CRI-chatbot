"""Minimal same-host relay for institution-specific WhatsApp webhooks.

TLS terminates at Traefik. Only Meta's signature and the exact request body
are forwarded; the backend still authenticates the signature per institution.
Never log request URLs: verification tokens are query parameters.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

MAX_BODY_BYTES = 1_048_576
MAX_QUERY_BYTES = 4096
MAX_REPLY_BYTES = 16_384
MAX_CONCURRENT = 32
UPSTREAM = "http://backend:8000"
_SIGNATURE = re.compile(r"sha256=[0-9a-f]{64}\Z")

# HTTPX's INFO request logger includes query strings, which may contain the
# Meta verification token. Do not enable verbose HTTP transport logging here.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    secret = os.environ.get("WEBHOOK_PROXY_SHARED_SECRET", "")
    try:
        encoded = secret.encode("ascii")
    except UnicodeEncodeError:
        raise RuntimeError("Webhook relay configuration unavailable") from None
    if not encoded or len(encoded) > 4096 or any(byte < 33 or byte > 126 for byte in encoded):
        raise RuntimeError("Webhook relay configuration unavailable")
    app.state.relay_secret = secret
    app.state.relay_client = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=3.0),
        limits=httpx.Limits(max_connections=MAX_CONCURRENT, max_keepalive_connections=MAX_CONCURRENT),
        follow_redirects=False,
        trust_env=False,
    )
    try:
        yield
    finally:
        await app.state.relay_client.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
_slots = asyncio.Semaphore(MAX_CONCURRENT)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/wa/whatsapp/tenant/{slug}", methods=["GET", "POST"])
async def relay(slug: str, request: Request) -> Response:
    if not re.fullmatch(r"[a-z][a-z0-9]{1,49}", slug):
        raise HTTPException(status_code=404, detail="Not found")
    query = request.scope.get("query_string", b"")
    if len(query) > MAX_QUERY_BYTES or any(byte < 32 or byte > 126 for byte in query):
        raise HTTPException(status_code=400, detail="Invalid request")
    signatures = request.headers.getlist("x-hub-signature-256")
    if request.method == "POST" and (len(signatures) != 1 or not _SIGNATURE.fullmatch(signatures[0])):
        raise HTTPException(status_code=403, detail="Webhook rejected")
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=0.1)
    except TimeoutError:
        raise HTTPException(status_code=503, detail="Webhook unavailable") from None
    try:
        body = bytearray()
        if request.method == "POST":
            lengths = request.headers.getlist("content-length")
            if len(lengths) > 1:
                raise HTTPException(status_code=400, detail="Invalid request")
            length = lengths[0] if lengths else None
            if length is not None and (len(length) > 10 or not length.isascii()
                                       or not length.isdecimal() or int(length) > MAX_BODY_BYTES):
                raise HTTPException(status_code=413, detail="Request too large")
            try:
                async with asyncio.timeout(10):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > MAX_BODY_BYTES:
                            raise HTTPException(status_code=413, detail="Request too large")
                        body.extend(chunk)
            except TimeoutError:
                raise HTTPException(status_code=408, detail="Request timed out") from None
        url = httpx.URL(f"{UPSTREAM}/api/v1/webhook/whatsapp/tenant/{slug}").copy_with(query=query)
        headers = {"X-Demo-Webhook-Proxy": request.app.state.relay_secret}
        if request.method == "POST":
            headers["X-Hub-Signature-256"] = signatures[0]
            headers["Content-Type"] = "application/json"
        client = request.app.state.relay_client
        try:
            async with client.stream(request.method, url, headers=headers, content=bytes(body)) as upstream:
                if not 200 <= upstream.status_code < 300:
                    raise HTTPException(status_code=upstream.status_code if 400 <= upstream.status_code < 500 else 503,
                                        detail="Webhook rejected" if 400 <= upstream.status_code < 500 else "Webhook unavailable")
                response_body = bytearray()
                async for chunk in upstream.aiter_bytes():
                    if len(response_body) + len(chunk) > MAX_REPLY_BYTES:
                        raise HTTPException(status_code=503, detail="Webhook unavailable")
                    response_body.extend(chunk)
                media_type = "text/plain" if request.method == "GET" else "application/json"
                return Response(bytes(response_body), status_code=upstream.status_code, media_type=media_type,
                                headers={"Cache-Control": "no-store"})
        except httpx.HTTPError:
            raise HTTPException(status_code=503, detail="Webhook unavailable") from None
    finally:
        _slots.release()
