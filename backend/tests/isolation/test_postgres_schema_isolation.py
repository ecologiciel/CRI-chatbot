"""PostgreSQL schema isolation tests.

Verifies that TenantContext.db_session() scopes each tenant to its own
schema via SET search_path, and that slug validation prevents SQL injection.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.tenant import TenantContext

from .conftest import make_tenant


def _make_mock_session_factory():
    """Create a properly structured mock for get_session_factory().

    get_session_factory() returns an async_sessionmaker.
    Calling the sessionmaker returns an async context manager yielding a session.
    """
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    # factory() returns an async context manager
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    # get_session_factory() returns the factory; factory() returns the cm
    mock_factory = MagicMock()
    mock_factory.return_value = mock_cm

    return mock_factory, mock_session


class TestPostgresSchemaIsolation:
    """Each tenant's DB session must use its own schema."""

    @pytest.mark.asyncio
    async def test_db_session_search_path_alpha(self, tenant_alpha):
        """tenant_alpha session sets search_path to tenant_alpha, public."""
        mock_factory, mock_session = _make_mock_session_factory()

        with patch("app.core.tenant.get_session_factory", return_value=mock_factory):
            async with tenant_alpha.db_session():
                pass

        # First execute call is the SET search_path
        first_call = mock_session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "tenant_alpha" in sql_text
        assert "SET search_path TO tenant_alpha, public" in sql_text

    @pytest.mark.asyncio
    async def test_db_session_search_path_beta(self, tenant_beta):
        """tenant_beta session sets search_path to tenant_beta, public."""
        mock_factory, mock_session = _make_mock_session_factory()

        with patch("app.core.tenant.get_session_factory", return_value=mock_factory):
            async with tenant_beta.db_session():
                pass

        first_call = mock_session.execute.call_args_list[0]
        sql_text = str(first_call[0][0])
        assert "tenant_beta" in sql_text
        assert "tenant_alpha" not in sql_text

    @pytest.mark.asyncio
    async def test_two_tenants_never_share_search_path(self, tenant_alpha, tenant_beta):
        """Sequential sessions for two tenants produce distinct search paths."""
        captured_sql = []

        async def capture_session(tenant):
            mock_factory, mock_session = _make_mock_session_factory()

            with patch("app.core.tenant.get_session_factory", return_value=mock_factory):
                async with tenant.db_session():
                    pass

            first_call = mock_session.execute.call_args_list[0]
            captured_sql.append(str(first_call[0][0]))

        await capture_session(tenant_alpha)
        await capture_session(tenant_beta)

        assert len(captured_sql) == 2
        assert captured_sql[0] != captured_sql[1]
        assert "tenant_alpha" in captured_sql[0]
        assert "tenant_beta" in captured_sql[1]

    def test_sql_injection_slug_rejected(self):
        """Slug with SQL injection characters is rejected at construction."""
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            TenantContext(
                id=TenantContext.__dataclass_fields__["id"].default
                if hasattr(TenantContext.__dataclass_fields__["id"], "default")
                else __import__("uuid").uuid4(),
                slug="alpha; DROP TABLE admins;--",
                name="Evil",
                status="active",
                whatsapp_config=None,
            )

    @pytest.mark.parametrize(
        "bad_slug",
        [
            "Alpha",  # uppercase
            "alpha beta",  # space
            "alpha-beta",  # hyphen
            "alpha.beta",  # dot
            "_alpha",  # leading underscore
            "alpha'OR'1'='1",  # SQL injection
            "",  # empty
            "123; DROP",  # SQL with semicolon
        ],
    )
    def test_invalid_slug_patterns_rejected(self, bad_slug):
        """Various invalid slug patterns are rejected by __post_init__."""
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            make_tenant(bad_slug)
