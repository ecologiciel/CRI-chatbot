# =============================================================================
# CRI Chatbot Platform — Backend Dockerfile (multi-stage)
# =============================================================================

# Stage 1: Builder — install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --require-hashes --prefix=/install -r requirements.txt

# Stage 2: Runner — minimal runtime image
FROM python:3.12-slim AS runner

# Security: non-root user
RUN groupadd -r cri && useradd -r -g cri -d /app -s /sbin/nologin cri

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code and the reviewed ONSSA demonstration corpus.  The
# corpus is intentionally embedded so Hostinger Docker Manager can initialize
# a new project without SSH, bind mounts, or a second artifact store.
COPY backend/app/ app/
COPY backend/alembic.ini .
COPY backend/alembic/ alembic/
COPY docs/demos/onssa/ /app/onssa-corpus/

# Set ownership
RUN chown -R cri:cri /app

USER cri

# Uvicorn on port 8000
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/api/v1/health'); exit(0 if r.status_code == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
