# =============================================================================
# CRI Chatbot Platform — Backend Dockerfile (multi-stage)
# =============================================================================

# Stage 1: Builder — install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runner — minimal runtime image
FROM python:3.12-slim AS runner

# Security: non-root user
RUN groupadd -r cri && useradd -r -g cri -d /app -s /sbin/nologin cri

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ app/
COPY alembic.ini .
COPY alembic/ alembic/

# Set ownership
RUN chown -R cri:cri /app

USER cri

# Uvicorn on port 8000
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8000/api/v1/health'); exit(0 if r.status_code == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
