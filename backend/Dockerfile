# =============================================================================
# CRI Chatbot Platform — Backend Dockerfile (multi-stage)
# =============================================================================

# Apply available Alpine security updates to both build and runtime.
FROM python:3.12-alpine AS base
RUN apk upgrade --no-cache

# Stage 1: Builder — install dependencies
FROM base AS builder

WORKDIR /build
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes --prefix=/install -r requirements.txt

# Stage 2: Runner — minimal runtime image
FROM base AS runner

# Security: non-root user
RUN addgroup -S cri && adduser -S -G cri -h /app cri

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# The data network is intentionally internal on the VPS.  Seed tiktoken's
# tokenizer vocabulary while the image is built, so workers never need to
# contact Azure Blob Storage at runtime just to tokenize a document.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

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
    CMD ["python", "-m", "app.scripts.healthcheck"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
