"""Client for the network-isolated document extraction service."""

import json
from pathlib import PurePosixPath

import httpx

from app.core.exceptions import IngestionError
from app.services.rag.extractors import SUPPORTED_EXTENSIONS, ExtractedDocument, PageSpan


async def extract_remotely(data: bytes, filename: str, service_url: str) -> ExtractedDocument:
    extension = PurePosixPath(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise IngestionError("Unsupported document type")
    try:
        async with (
            # The ingestion worker can run five jobs concurrently while the
            # isolated service processes one document at a time (45 s limit).
            # Allow the queue to drain without timing out valid long documents.
            httpx.AsyncClient(timeout=httpx.Timeout(300, connect=5), trust_env=False) as client,
            client.stream(
                "POST",
                f"{service_url.rstrip('/')}/extract",
                headers={"X-File-Extension": extension},
                content=data,
            ) as response,
        ):
            response.raise_for_status()
            encoded = bytearray()
            async for part in response.aiter_bytes():
                encoded.extend(part)
                if len(encoded) > 24 * 1024 * 1024:
                    raise ValueError("Extraction result too large")
            result = json.loads(encoded)
        text = result["text"]
        if not isinstance(text, str) or not text.strip() or len(text) > 12_000_000:
            raise ValueError("Invalid extracted text")
        pages = []
        for page in result["pages"]:
            number, start, end = page["number"], page["start"], page["end"]
            if not all(type(value) is int for value in (number, start, end)):
                raise ValueError("Invalid page span")
            if number <= 0 or not 0 <= start < end <= len(text):
                raise ValueError("Invalid page bounds")
            pages.append(PageSpan(number=number, start=start, end=end))
        return ExtractedDocument(text=text, pages=tuple(pages))
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise IngestionError("Isolated document extraction failed") from exc
