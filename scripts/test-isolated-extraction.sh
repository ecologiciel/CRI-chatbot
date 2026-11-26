#!/usr/bin/env bash
# Real extraction smoke test using synthetic files and no external network.
set -Eeuo pipefail
image="${BACKEND_IMAGE:?Set BACKEND_IMAGE to the image to test}"
name="codex-extract-smoke-$$"
cleanup() { docker rm -f "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --name "$name" --network none --cap-drop ALL \
    --security-opt no-new-privileges --read-only \
    --tmpfs /tmp:noexec,nosuid,nodev,size=64m --pids-limit 32 --memory 1g --cpus 1 \
    --entrypoint uvicorn "$image" app.services.rag.extractor_service:app \
    --host 127.0.0.1 --port 8080 --no-access-log >/dev/null
docker exec -i "$name" python - <<'PY'
import io
import socket
import time

import httpx
from docx import Document
from reportlab.pdfgen import canvas

base = "http://127.0.0.1:8080"
for _ in range(60):
    try:
        if httpx.get(base + "/health", timeout=2, trust_env=False).status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise RuntimeError("Extraction service did not start")

def send(extension, data):
    return httpx.post(base + "/extract", headers={"X-File-Extension": extension}, content=data, timeout=55, trust_env=False)

response = send(".txt", b"Plain test")
assert response.status_code == 200 and response.json()["text"] == "Plain test"
document = Document()
document.add_paragraph("Document ONSSA")
docx = io.BytesIO()
document.save(docx)
response = send(".docx", docx.getvalue())
assert response.status_code == 200 and "Document ONSSA" in response.json()["text"]
pdf = io.BytesIO()
writer = canvas.Canvas(pdf)
writer.drawString(70, 700, "Page one")
writer.showPage()
writer.showPage()
writer.drawString(70, 700, "Page three")
writer.save()
response = send(".pdf", pdf.getvalue())
assert response.status_code == 200
result = response.json()
assert [page["number"] for page in result["pages"]] == [1, 3]
assert all(result["text"][p["start"]:p["end"]].strip() for p in result["pages"])
assert send(".docx", b"PK\x03\x04corrupted").status_code == 422
assert send(".txt", b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
assert send(".txt", b"After failure").json()["text"] == "After failure"
try:
    socket.create_connection(("1.1.1.1", 443), timeout=2)
except OSError:
    pass
else:
    raise RuntimeError("The test container unexpectedly has external network access")
print("Isolated extraction, limits, PDF pages and failure recovery: OK")
PY
