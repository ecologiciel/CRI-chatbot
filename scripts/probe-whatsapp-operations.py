"""Short-lived production RBAC probe; never prints credentials or tokens.

Run inside the backend container with an isolated random WA_PROBE_RUN_ID.
Only exact synthetic UUIDs/emails derived from that ID can be removed.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import sys
import uuid

import httpx
from sqlalchemy import delete, select

from app.core.database import close_engine, get_session_factory
from app.core.config import get_settings
from app.models.admin import Admin
from app.models.enums import AdminRole, TenantStatus
from app.models.tenant import Tenant
from app.services.auth.service import AuthService

run_id = os.environ.get("WA_PROBE_RUN_ID", "")
if not re.fullmatch(r"[0-9a-f]{32}", run_id):
    raise RuntimeError("Invalid probe identifier")
if os.environ.get("WA_PROBE_AUTHORIZED") != "1" or not get_settings().is_production:
    raise RuntimeError("Explicit production probe guard is required")
tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "wa-probe-tenant:" + run_id)
admin_id = uuid.uuid5(uuid.NAMESPACE_URL, "wa-probe-admin:" + run_id)
viewer_id = uuid.uuid5(uuid.NAMESPACE_URL, "wa-probe-viewer:" + run_id)
slug = "codexprobe" + run_id[:20]
admin_email = "probe-admin-" + run_id + "@example.com"
viewer_email = "probe-viewer-" + run_id + "@example.com"


async def cleanup() -> None:
    async with get_session_factory()() as session:
        await session.execute(
            delete(Admin).where(Admin.id == admin_id, Admin.email == admin_email)
        )
        await session.execute(
            delete(Admin).where(Admin.id == viewer_id, Admin.email == viewer_email)
        )
        await session.execute(
            delete(Tenant).where(Tenant.id == tenant_id, Tenant.slug == slug)
        )
        await session.commit()


async def run() -> None:
    password = secrets.token_urlsafe(32)
    tokens: list[dict] = []
    try:
        async with get_session_factory()() as session:
            onssa_id = (
                await session.execute(select(Tenant.id).where(Tenant.slug == "onssa"))
            ).scalar_one()
            existing = (
                await session.execute(select(Tenant.id).where(Tenant.id == tenant_id))
            ).scalar_one_or_none()
            if existing is not None:
                raise RuntimeError("Probe identifier already exists")
            session.add(
                Tenant(
                    id=tenant_id,
                    slug=slug,
                    name="Temporary probe",
                    region="Test",
                    status=TenantStatus.active,
                    is_demo=True,
                    conversation_retention_days=1,
                )
            )
            await session.flush()
            hashed = AuthService.hash_password(password)
            for identifier, email, role in (
                (admin_id, admin_email, AdminRole.admin_tenant),
                (viewer_id, viewer_email, AdminRole.viewer),
            ):
                session.add(
                    Admin(
                        id=identifier,
                        email=email,
                        full_name="Temporary probe",
                        role=role,
                        tenant_id=onssa_id,
                        password_hash=hashed,
                        is_active=True,
                    )
                )
            await session.commit()

        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8000", timeout=20
        ) as client:
            for email in (admin_email, viewer_email):
                response = await client.post(
                    "/api/v1/auth/login", json={"email": email, "password": password}
                )
                if response.status_code != 200:
                    raise RuntimeError("Synthetic login failed")
                tokens.append(response.json())
            auth = {
                "Authorization": "Bearer " + tokens[0]["access_token"],
                "X-Tenant-ID": str(onssa_id),
            }
            availability = await client.get(
                "/api/v1/whatsapp/operations/availability", headers=auth
            )
            assert (
                availability.status_code == 200
                and availability.json()["intake_enabled"] is False
            )
            events = await client.get(
                "/api/v1/whatsapp/operations/events?kind=status", headers=auth
            )
            assert events.status_code == 200 and isinstance(
                events.json()["events"], list
            )
            foreign = await client.get(
                "/api/v1/whatsapp/operations/events",
                headers={**auth, "X-Tenant-ID": str(tenant_id)},
            )
            assert foreign.status_code == 403
            viewer = await client.get(
                "/api/v1/whatsapp/operations/events",
                headers={
                    "Authorization": "Bearer " + tokens[1]["access_token"],
                    "X-Tenant-ID": str(onssa_id),
                },
            )
            assert viewer.status_code == 403
            for token in tokens:
                await client.post(
                    "/api/v1/auth/logout",
                    headers={"Authorization": "Bearer " + token["access_token"]},
                    json={"refresh_token": token["refresh_token"]},
                )
        print("LIVE_WA_OPERATIONS_RBAC_OK", flush=True)
    finally:
        await cleanup()
        await close_engine()


async def main() -> None:
    if sys.argv[1:] == ["--cleanup"]:
        await cleanup()
        await close_engine()
    elif not sys.argv[1:]:
        await run()
    else:
        raise RuntimeError("Invalid probe mode")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(
            "LIVE_WA_OPERATIONS_PROBE_FAILED",
            type(exc).__name__,
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from None
