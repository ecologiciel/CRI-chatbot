"""Read approved, supported WhatsApp templates from the tenant's Meta account."""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.core.tenant import TenantContext

_META_GRAPH = "https://graph.facebook.com/v27.0"
_VARIABLE = re.compile(r"{{\s*(\d+)\s*}}")


def _supported_template(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Return templates the current sender can render: static headers and numeric body variables."""
    if raw.get("status") != "APPROVED":
        return None
    if not all(isinstance(raw.get(key), str) and raw[key] for key in ("id", "name", "language")):
        return None
    components = raw.get("components")
    if not isinstance(components, list):
        return None
    body = header = footer = None
    buttons: list[str] = []
    for item in components:
        if not isinstance(item, dict):
            return None
        kind = item.get("type")
        if kind == "BODY" and isinstance(item.get("text"), str) and body is None:
            body = item["text"]
        elif (
            kind == "HEADER" and item.get("format") == "TEXT" and isinstance(item.get("text"), str)
        ):
            header = item["text"]
            if "{{" in header:
                return None
        elif kind == "FOOTER" and isinstance(item.get("text"), str):
            footer = item["text"]
            if "{{" in footer:
                return None
        elif kind == "BUTTONS" and isinstance(item.get("buttons"), list):
            for button in item["buttons"]:
                if not isinstance(button, dict) or not isinstance(button.get("text"), str):
                    return None
                if button.get("type") not in {"QUICK_REPLY", "URL", "PHONE_NUMBER"}:
                    return None
                if "{{" in str(button.get("url", "")):
                    return None
                buttons.append(button["text"])
        else:
            return None
    if body is None:
        return None
    variables = sorted({int(value) for value in _VARIABLE.findall(body)})
    if _VARIABLE.sub("", body).count("{{") or variables != list(range(1, len(variables) + 1)):
        return None
    template: dict[str, Any] = {
        "id": raw["id"],
        "name": raw["name"],
        "language": raw["language"],
        "body": body,
        "buttons": buttons,
        "variables": [str(value) for value in variables],
    }
    if header is not None:
        template["header"] = header
    if footer is not None:
        template["footer"] = footer
    return template


async def approved_templates(tenant: TenantContext, after: str | None = None) -> dict[str, Any]:
    """Fetch one page from a fixed Meta host; never return credentials or follow provider URLs."""
    config = tenant.whatsapp_config or {}
    account_id, token = config.get("business_account_id"), config.get("access_token")
    if not account_id or not token:
        return {"configured": False, "items": [], "next_cursor": None}
    if (
        not isinstance(account_id, str)
        or not re.fullmatch(r"[0-9]{1,32}", account_id)
        or not isinstance(token, str)
    ):
        raise ValueError("Invalid WhatsApp account configuration")
    params = {"fields": "id,name,language,status,components", "limit": "100"}
    if after:
        params["after"] = after
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        response = await client.get(
            f"{_META_GRAPH}/{account_id}/message_templates",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Invalid Meta response")
    items = [_supported_template(item) for item in payload["data"] if isinstance(item, dict)]
    paging = payload.get("paging") or {}
    cursors = paging.get("cursors") or {} if isinstance(paging, dict) else {}
    next_cursor = cursors.get("after") if isinstance(cursors, dict) and paging.get("next") else None
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 512):
        raise ValueError("Invalid Meta pagination cursor")
    return {
        "configured": True,
        "items": [item for item in items if item],
        "next_cursor": next_cursor,
    }
