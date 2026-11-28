"""Exercise escalation WebSockets against disposable PostgreSQL and Redis.

Run only in the explicitly named isolated fixture environment.
"""

import asyncio
import json
import os
import socket
import uuid

import httpx
import uvicorn
from fastapi import FastAPI, Request
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from app.api.ws.escalation_ws import escalation_ws_endpoint
from app.core.config import get_settings
from app.core.database import close_engine, get_engine, get_session_factory
from app.core.redis import close_redis, init_redis
from app.core.trusted_proxy import TrustedProxyIPMiddleware
from app.models.admin import Admin
from app.models.enums import AdminRole, TenantStatus
from app.models.tenant import Tenant
from app.services.auth.jwt import JWTManager
from app.services.auth.service import AuthService
from app.services.auth.session_manager import SessionManager


async def main():
    settings = get_settings()
    if (settings.postgres_host, settings.postgres_db, settings.redis_host) != (
        "codex-ws-pg",
        "ragtest_ws",
        "codex-ws-redis",
    ):
        raise RuntimeError("Refusing to run outside the isolated fixture")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: Tenant.metadata.create_all(
                sync, tables=[Tenant.__table__, Admin.__table__]
            )
        )
    tenant_id, other_id, admin_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with get_session_factory()() as session:
        session.add_all(
            [
                Tenant(
                    id=tenant_id,
                    name="Fixture A",
                    slug="fixture_a",
                    region="Test",
                    status=TenantStatus.active,
                ),
                Tenant(
                    id=other_id,
                    name="Fixture B",
                    slug="fixture_b",
                    region="Test",
                    status=TenantStatus.active,
                ),
            ]
        )
        await session.flush()
        session.add(
            Admin(
                id=admin_id,
                email="test@example.invalid",
                full_name="Fixture",
                password_hash=AuthService.hash_password("fixture-password"),
                role=AdminRole.supervisor,
                tenant_id=tenant_id,
                is_active=True,
            )
        )
        await session.commit()
    redis = await init_redis()
    token, jti = JWTManager.create_access_token(admin_id, "supervisor", tenant_id)
    sessions = SessionManager(redis)
    app = FastAPI()
    app.add_api_websocket_route("/ws/escalations/{tenant_id}", escalation_ws_endpoint)

    @app.get("/api/fixture-peer")
    async def fixture_peer(request: Request):
        return {"ip": request.client.host}

    proxy = os.environ.get("WS_FIXTURE_PROXY") == "1"
    proof_mode = os.environ.get("WS_FIXTURE_PROXY_PROOF") == "1"
    if proof_mode and not proxy:
        raise RuntimeError("Proxy proof fixture requires the proxy")
    if proof_mode:
        app.add_middleware(TrustedProxyIPMiddleware, secret="a" * 64)

        @app.post("/api/fixture-login")
        async def fixture_login(request: Request):
            tokens = await AuthService().login("test@example.invalid", "fixture-password", request.client.host)
            return {"access_token": tokens.access_token}
    if proxy:
        port = 8000
    else:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0" if proxy else "127.0.0.1",
            port=port,
            log_level="error",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError("Fixture API did not start")
        if proxy:
            async with httpx.AsyncClient(trust_env=False) as client:
                last_failure = "no response"
                for _ in range(100):
                    try:
                        response = await client.get("http://codex-ws-traefik:8080/api/fixture-peer", headers={"X-Forwarded-For": "203.0.113.99", "X-Internal-Client-IP-Proof": "attacker"} if proof_mode else {})
                        response.raise_for_status()
                        ip_address = response.json()["ip"]
                        break
                    except (httpx.HTTPError, KeyError) as exc:
                        last_failure = str(exc)
                        await asyncio.sleep(0.1)
                else:
                    raise RuntimeError(f"Fixture proxy did not route API: {last_failure}")
            url = "ws://codex-ws-traefik:8080/ws/escalations"
        else:
            ip_address = "127.0.0.1"
            url = f"ws://127.0.0.1:{port}/ws/escalations"
        if proof_mode:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
                peer.connect(("codex-ws-traefik", 8080))
                assert ip_address == peer.getsockname()[0] and ip_address != "203.0.113.99"
            async with httpx.AsyncClient(trust_env=False) as client:
                login = await client.post("http://codex-ws-traefik:8080/api/fixture-login", headers={"X-Forwarded-For": "203.0.113.99", "X-Internal-Client-IP-Proof": "attacker"})
                login.raise_for_status()
                token = login.json()["access_token"]
        else:
            await sessions.register_session(str(admin_id), jti, ip_address)
        headers = {"X-Forwarded-For": "203.0.113.99", "X-Internal-Client-IP-Proof": "attacker"} if proof_mode else None
        async with connect(f"{url}/{tenant_id}", additional_headers=headers) as one, connect(f"{url}/{tenant_id}", additional_headers=headers) as two:
            for ws in (one, two):
                await ws.send(json.dumps({"type": "auth", "token": token}))
                assert json.loads(await asyncio.wait_for(ws.recv(), 3))["event"] == "authenticated"
            async with connect(f"{url}/{other_id}") as foreign:
                await foreign.send(json.dumps({"type": "auth", "token": token}))
                try:
                    await asyncio.wait_for(foreign.recv(), 3)
                    raise AssertionError("Foreign tenant accepted")
                except ConnectionClosed as exc:
                    assert exc.code == 4003
            await redis.publish("fixture_a:escalations:new", json.dumps({"id": "synthetic"}))
            for ws in (one, two):
                assert json.loads(await asyncio.wait_for(ws.recv(), 3))["data"]["id"] == "synthetic"
                try:
                    await asyncio.wait_for(ws.recv(), 0.25)
                    raise AssertionError("Duplicate event")
                except TimeoutError:
                    pass
            await sessions.invalidate_session(str(admin_id))
            await redis.publish("fixture_a:escalations:new", json.dumps({"id": "must-not-arrive"}))
            for ws in (one, two):
                try:
                    await asyncio.wait_for(ws.recv(), 3)
                    raise AssertionError("Revoked session received a message")
                except ConnectionClosed as exc:
                    assert exc.code == 4001
        if proxy:
            async with httpx.AsyncClient(trust_env=False) as client:
                responses = [
                    (
                        await client.get(f"http://codex-ws-traefik:8080/ws/escalations/{tenant_id}")
                    ).status_code
                    for _ in range(50)
                ]
                assert 429 in responses, "Proxy did not limit repeated connection attempts"
        print(
            "REAL_WS_PROXY_PROOF_LOGIN_OK" if proof_mode else "REAL_WS_POSTGRES_REDIS_PROXY_OK" if proxy else "REAL_WS_POSTGRES_REDIS_ISOLATION_OK",
            flush=True,
        )
    finally:
        server.should_exit = True
        await task
        await close_redis()
        await close_engine()


if __name__ == "__main__":
    asyncio.run(main())
