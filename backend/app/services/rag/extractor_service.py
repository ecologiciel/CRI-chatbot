"""Private extraction endpoint with per-request child processes.

This service has no storage credentials or external network in the Hostinger
deployment. The container boundary reduces exposure; it is not a VM sandbox.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import sys
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request

from app.services.rag.extractors import SUPPORTED_EXTENSIONS, extract_document

MAX_INPUT = 10 * 1024 * 1024
MAX_OUTPUT = 24 * 1024 * 1024
TIMEOUT_SECONDS = 45
_slot = asyncio.Semaphore(1)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _read_bounded(reader: asyncio.StreamReader, maximum: int) -> bytes:
    chunks = []
    total = 0
    while data := await reader.read(65536):
        total += len(data)
        if total > maximum:
            raise ValueError("Extraction output is too large")
        chunks.append(data)
    return b"".join(chunks)


async def _run_child(data: bytes, extension: str) -> dict:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.services.rag.extractor_service",
        extension,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": "/app"},
    )
    assert process.stdin is not None and process.stdout is not None

    async def send() -> None:
        try:
            process.stdin.write(data)
            await process.stdin.drain()
        finally:
            process.stdin.close()

    sending = asyncio.create_task(send())
    receiving = asyncio.create_task(_read_bounded(process.stdout, MAX_OUTPUT))
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            _, output = await asyncio.gather(sending, receiving)
            await process.wait()
        if process.returncode != 0:
            raise ValueError("Extraction process failed")
        value = json.loads(output)
        if not isinstance(value, dict):
            raise ValueError("Invalid extraction output")
        return value
    finally:
        # Kill descendants too: a parser child must not persist between tenants.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        for task in (sending, receiving):
            if not task.done():
                task.cancel()
        await asyncio.gather(sending, receiving, return_exceptions=True)
        await process.wait()


@app.post("/extract")
async def extract(request: Request) -> dict:
    extension = request.headers.get("x-file-extension", "")
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported document type")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_INPUT:
            raise HTTPException(status_code=413, detail="Document too large")
    if not data:
        raise HTTPException(status_code=422, detail="Empty document")
    try:
        async with _slot:
            return await _run_child(bytes(data), extension)
    except (TimeoutError, OSError, ValueError, BrokenPipeError):
        raise HTTPException(status_code=422, detail="Document extraction failed") from None


def _child_main(extension: str) -> None:
    if sys.platform != "linux" or extension not in SUPPORTED_EXTENSIONS:
        raise SystemExit(1)
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if not data or len(data) > MAX_INPUT:
        raise SystemExit(1)
    result = extract_document(data, "document" + extension)
    if len(result.text) > 12_000_000:
        raise SystemExit(1)
    output = json.dumps(asdict(result), ensure_ascii=False).encode("utf-8")
    if len(output) > MAX_OUTPUT:
        raise SystemExit(1)
    sys.stdout.buffer.write(output)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(1)
    _child_main(sys.argv[1])
