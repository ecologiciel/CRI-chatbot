"""Recover client IP only from a proxy authenticated with a private header.

The proxy must strip untrusted incoming forwarded headers and overwrite the
authentication header. Direct clients keep their socket address. This does
not authenticate users or prove an address is a real person.
"""
from __future__ import annotations

import hmac
import ipaddress

from starlette.types import ASGIApp, Receive, Scope, Send

_SECRET_HEADER = b"x-internal-client-ip-proof"
_FORWARDED_FOR = b"x-forwarded-for"


class TrustedProxyIPMiddleware:
    def __init__(self, app: ASGIApp, *, secret: str) -> None:
        self.app = app
        self.secret = secret.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        proofs = [value for name, value in headers if name.lower() == _SECRET_HEADER]
        forwarded = [value for name, value in headers if name.lower() == _FORWARDED_FOR]
        # Remove the proof before any application logger or route sees it,
        # regardless of whether it was valid.
        sanitized = [(name, value) for name, value in headers if name.lower() != _SECRET_HEADER]
        child = dict(scope, headers=sanitized)
        if self.secret and len(proofs) == 1 and hmac.compare_digest(proofs[0], self.secret) and len(forwarded) == 1:
            try:
                # Traefik appends its immediate client as the rightmost entry.
                # Its entrypoint must reject untrusted forwarded input.
                last = forwarded[0].decode("ascii").split(",")[-1].strip()
                address = str(ipaddress.ip_address(last))
            except (UnicodeDecodeError, ValueError):
                pass
            else:
                child["client"] = (address, 0)
        await self.app(child, receive, send)
