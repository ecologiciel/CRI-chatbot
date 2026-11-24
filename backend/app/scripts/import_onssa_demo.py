"""Provision the ONSSA web demo and submit its reviewed corpus for ingestion.

Run inside the backend container with the collected Markdown mounted at
``/corpus``. Credentials are read only from environment variables and are never
written to disk or printed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

import httpx

DEFAULT_DISCLAIMER = (
    "Prototype de démonstration non officiel. Les réponses reposent sur une sélection "
    "de sources publiques ONSSA et ne remplacent pas les informations officielles."
)


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"{name} is required", file=sys.stderr)
        raise SystemExit(1)
    return value


async def _request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    response = await client.request(method, path, **kwargs)
    response.raise_for_status()
    return response


def _collection_date(document_path: Path) -> str:
    """Return the provenance date written by the controlled collector."""
    for line in document_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- Collecté le : "):
            collected_at = line.removeprefix("- Collecté le : ").strip()
            date.fromisoformat(collected_at)
            return collected_at
    raise ValueError(f"Collection date missing from {document_path}")


async def main() -> int:
    base_url = os.environ.get("DEMO_API_URL", "http://backend:8000").rstrip("/")
    corpus_dir = Path(os.environ.get("DEMO_CORPUS_DIR", "/app/onssa-corpus"))
    email = _required("DEMO_ADMIN_EMAIL")
    password = _required("DEMO_ADMIN_PASSWORD")
    manifest_path = corpus_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"Missing manifest: {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
        login = await _request(
            client,
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        tenants = await _request(client, "GET", "/api/v1/tenants/", headers=headers)
        onssa = next((item for item in tenants.json()["items"] if item["slug"] == "onssa"), None)
        if onssa is None:
            tenant_response = await _request(
                client,
                "POST",
                "/api/v1/tenants/",
                headers=headers,
                json={
                    "name": "ONSSA — Démonstration",
                    "slug": "onssa",
                    "region": "National",
                    "accent_color": "hsl(160 84% 25%)",
                    "is_demo": True,
                    "conversation_retention_days": 7,
                    "public_config": {
                        "web_enabled": True,
                        "disclaimer": DEFAULT_DISCLAIMER,
                    },
                },
            )
            onssa = tenant_response.json()
            print("Provisioned ONSSA demo tenant")
        else:
            print("ONSSA demo tenant already exists")

        tenant_headers = {**headers, "X-Tenant-ID": onssa["id"]}
        existing_docs = await _request(
            client,
            "GET",
            "/api/v1/kb/documents",
            headers=tenant_headers,
            params={"page_size": 100},
        )
        existing_titles = {item["title"] for item in existing_docs.json()["items"]}

        for source in manifest["sources"]:
            if source["title"] in existing_titles:
                print(f"Skipped existing document: {source['title']}")
                continue
            document_path = corpus_dir / "corpus" / f"{source['slug']}.md"
            if not document_path.is_file():
                print(f"Missing collected document: {document_path}", file=sys.stderr)
                return 1
            collected_at = _collection_date(document_path)
            version = f"collecte-{collected_at}"
            upload = await _request(
                client,
                "POST",
                "/api/v1/kb/documents",
                headers=tenant_headers,
                data={
                    "title": source["title"],
                    "category": source["category"],
                    "language": source["language"],
                    "source_url": source["url"],
                    "source_authority": manifest["source_authority"],
                    "source_reference": source["title"],
                    "source_version": version,
                    "published_at": collected_at,
                },
                files={"file": (document_path.name, document_path.read_bytes(), "text/markdown")},
            )
            document = upload.json()
            await _request(
                client,
                "POST",
                f"/api/v1/kb/documents/{document['id']}/validate",
                headers=tenant_headers,
                json={
                    "source_authority": manifest["source_authority"],
                    "source_reference": source["title"],
                    "source_version": version,
                    "published_at": collected_at,
                    "source_url": source["url"],
                },
            )
            print(f"Submitted for ingestion: {source['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
