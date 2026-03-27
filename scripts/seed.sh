#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — Script de seed initial
# Usage : ./scripts/seed.sh
# Cree le super_admin + tenant CRI-RSK (rabat) lors du premier deploiement
# =============================================================================

set -euo pipefail

DEPLOY_DIR="/opt/cri-platform"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

log() {
    echo "[seed $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ -z "${SEED_ADMIN_EMAIL:-}" ]]; then
    echo "ERROR: SEED_ADMIN_EMAIL is required"
    echo "Usage: SEED_ADMIN_EMAIL=admin@cri.ma SEED_ADMIN_PASSWORD='...' ./scripts/seed.sh"
    exit 1
fi

if [[ -z "${SEED_ADMIN_PASSWORD:-}" ]]; then
    echo "ERROR: SEED_ADMIN_PASSWORD is required (min 12 chars, 1 maj, 1 chiffre, 1 special)"
    exit 1
fi

cd "${DEPLOY_DIR}"

# ---------------------------------------------------------------------------
# Step 1: Run Alembic migrations
# ---------------------------------------------------------------------------
log "Running Alembic migrations..."
docker compose -f "${COMPOSE_FILE}" run --rm backend alembic upgrade head
log "Migrations complete."

# ---------------------------------------------------------------------------
# Step 2: Run seed script
# ---------------------------------------------------------------------------
log "Running seed script..."
docker compose -f "${COMPOSE_FILE}" run --rm \
    -e SEED_ADMIN_EMAIL="${SEED_ADMIN_EMAIL}" \
    -e SEED_ADMIN_PASSWORD="${SEED_ADMIN_PASSWORD}" \
    backend python -m app.scripts.seed

log "============================================"
log "Seed COMPLETE"
log "  Super-admin: ${SEED_ADMIN_EMAIL}"
log "  Tenant: rabat (CRI Rabat-Sale-Kenitra)"
log "============================================"
