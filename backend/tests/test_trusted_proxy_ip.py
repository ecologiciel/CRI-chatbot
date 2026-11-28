"""IP attribution never trusts unauthenticated forwarding headers."""
import pytest

from app.core.config import Settings
from app.core.trusted_proxy import TrustedProxyIPMiddleware

SECRET = "a" * 64
HEADER = b"x-internal-client-ip-proof"


async def observe(scope, *, secret=SECRET):
    seen = {}

    async def downstream(child, receive, send):
        seen.update(child)

    await TrustedProxyIPMiddleware(downstream, secret=secret)(scope, None, None)
    return seen


def scope(kind="http", headers=()):
    return {"type": kind, "client": ("172.20.0.2", 1234), "headers": list(headers)}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["http", "websocket"])
async def test_authenticated_proxy_supplies_rightmost_address_and_removes_proof(kind):
    result = await observe(scope(kind, [(HEADER, SECRET.encode()), (b"x-forwarded-for", b"192.0.2.10, 198.51.100.40")]))
    assert result["client"] == ("198.51.100.40", 0)
    assert all(name != HEADER for name, _ in result["headers"])


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [[], [(HEADER, b"wrong")], [(HEADER, SECRET.encode()), (HEADER, SECRET.encode())]])
async def test_untrusted_or_duplicate_proof_cannot_spoof_client(proof):
    result = await observe(scope(headers=[*proof, (b"x-forwarded-for", b"198.51.100.40")]))
    assert result["client"] == ("172.20.0.2", 1234)
    assert all(name != HEADER for name, _ in result["headers"])


@pytest.mark.asyncio
@pytest.mark.parametrize("forwarded", [[], [(b"x-forwarded-for", b"bad")], [(b"x-forwarded-for", b"\xff")], [(b"x-forwarded-for", b"1.2.3.4"), (b"x-forwarded-for", b"5.6.7.8")]])
async def test_invalid_or_duplicate_forwarded_headers_do_not_change_client(forwarded):
    result = await observe(scope(headers=[(HEADER, SECRET.encode()), *forwarded]))
    assert result["client"] == ("172.20.0.2", 1234)


@pytest.mark.asyncio
async def test_disabled_feature_does_not_trust_header():
    result = await observe(scope(headers=[(HEADER, SECRET.encode()), (b"x-forwarded-for", b"198.51.100.40")]), secret="")
    assert result["client"] == ("172.20.0.2", 1234)


@pytest.mark.parametrize("value", ["too-short", "Z" * 64, "a" * 63 + "\n"])
def test_proxy_proof_rejects_weak_or_invalid_configuration(value):
    with pytest.raises(ValueError):
        Settings.validate_trusted_proxy_ip_secret(value)


def test_proxy_proof_allows_disabled_or_fixed_length_hex():
    assert Settings.validate_trusted_proxy_ip_secret("") == ""
    assert Settings.validate_trusted_proxy_ip_secret(SECRET) == SECRET
