#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — Script de deploiement production
# Usage : ./scripts/deploy.sh <image-tag>
# Execute sur le VPS Nindohost via SSH depuis GitHub Actions
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEPLOY_DIR="/opt/cri-platform"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE="${DEPLOY_DIR}/.env"
IMAGE_TAG="${1:-}"
HEALTH_URL="http://localhost:8000/api/v1/health"
MAX_HEALTH_RETRIES=30
HEALTH_INTERVAL=5

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() {
    echo "[deploy $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

usage() {
    cat <<EOF
Usage: $(basename "$0") <image-tag>

Deploy the CRI Chatbot Platform to production.

Arguments:
  image-tag   Docker image tag to deploy (git SHA or 'latest')

Environment:
  Requires a .env file at ${ENV_FILE} with all production variables.
  See .env.example for reference.

Examples:
  $(basename "$0") abc123def456    # Deploy specific commit
  $(basename "$0") latest          # Deploy latest build
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
if [[ "${IMAGE_TAG}" == "--help" || "${IMAGE_TAG}" == "-h" ]]; then
    usage
fi

if [[ -z "${IMAGE_TAG}" ]]; then
    log "ERROR: image tag required"
    usage
fi

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
cd "${DEPLOY_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
    log "ERROR: .env file not found at ${ENV_FILE}"
    exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
    log "ERROR: ${COMPOSE_FILE} not found in ${DEPLOY_DIR}"
    exit 1
fi

# ---------------------------------------------------------------------------
# Save current tag for rollback
# ---------------------------------------------------------------------------
PREV_TAG=$(grep "^IMAGE_TAG=" "${ENV_FILE}" | cut -d= -f2 || echo "latest")
log "Current image tag: ${PREV_TAG}"
log "Deploying image tag: ${IMAGE_TAG}"

# ---------------------------------------------------------------------------
# Rollback function
# ---------------------------------------------------------------------------
rollback() {
    log "ROLLING BACK to previous tag: ${PREV_TAG}"
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${PREV_TAG}/" "${ENV_FILE}"
    docker compose -f "${COMPOSE_FILE}" up -d --no-deps backend frontend
    log "Rollback complete. Deployment FAILED."
    exit 1
}

# ---------------------------------------------------------------------------
# Phase 1: Update image tag in .env
# ---------------------------------------------------------------------------
log "Phase 1: Updating IMAGE_TAG in .env..."
if grep -q "^IMAGE_TAG=" "${ENV_FILE}"; then
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${IMAGE_TAG}/" "${ENV_FILE}"
else
    echo "IMAGE_TAG=${IMAGE_TAG}" >> "${ENV_FILE}"
fi

# ---------------------------------------------------------------------------
# Phase 2: Pull new images
# ---------------------------------------------------------------------------
log "Phase 2: Pulling new images..."
docker compose -f "${COMPOSE_FILE}" pull backend frontend

# ---------------------------------------------------------------------------
# Phase 3: Run database migrations
# ---------------------------------------------------------------------------
log "Phase 3: Running Alembic migrations..."
if ! docker compose -f "${COMPOSE_FILE}" run --rm backend alembic upgrade head; then
    log "ERROR: Migration failed!"
    rollback
fi

# ---------------------------------------------------------------------------
# Phase 4: Rolling restart
# ---------------------------------------------------------------------------
log "Phase 4: Restarting backend and frontend..."
trap rollback ERR
docker compose -f "${COMPOSE_FILE}" up -d --no-deps backend frontend

# ---------------------------------------------------------------------------
# Phase 5: Health check verification
# ---------------------------------------------------------------------------
log "Phase 5: Verifying health (max ${MAX_HEALTH_RETRIES} attempts, ${HEALTH_INTERVAL}s interval)..."

for i in $(seq 1 "${MAX_HEALTH_RETRIES}"); do
    STATUS=$(curl -sf "${HEALTH_URL}" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unreachable")

    if [[ "${STATUS}" == "healthy" || "${STATUS}" == "degraded" ]]; then
        log "Health check PASSED: ${STATUS}"
        trap - ERR
        log "============================================"
        log "Deployment SUCCESS — tag: ${IMAGE_TAG}"
        log "============================================"
        docker compose -f "${COMPOSE_FILE}" ps
        exit 0
    fi

    log "Health check attempt ${i}/${MAX_HEALTH_RETRIES}: ${STATUS}"
    sleep "${HEALTH_INTERVAL}"
done

# If we get here, health check exhausted all retries
log "ERROR: Health check failed after ${MAX_HEALTH_RETRIES} attempts"
rollback
