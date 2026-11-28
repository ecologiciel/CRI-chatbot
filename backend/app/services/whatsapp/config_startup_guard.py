"""Check channel envelopes before a strict-mode instance serves traffic."""

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.tenant import TenantResolver
from app.models.tenant import Tenant


async def verify_channel_configs_on_startup() -> None:
    """Refuse unreadable or legacy configs; do not log credential contents.

    Writers must still be stopped during a strict-mode cutover: this startup
    check is not a lock against other running versions of the application.
    """
    if not get_settings().whatsapp_config_require_encryption:
        return
    last_id = None
    async with get_session_factory()() as session:
        while True:
            statement = select(Tenant).order_by(Tenant.id).limit(100)
            if last_id is not None:
                statement = statement.where(Tenant.id > last_id)
            tenants = (await session.execute(statement)).scalars().all()
            if not tenants:
                return
            for tenant in tenants:
                try:
                    await TenantResolver._build_context(tenant, session=session)
                except Exception:
                    raise RuntimeError("Channel configuration validation failed") from None
            last_id = tenants[-1].id
