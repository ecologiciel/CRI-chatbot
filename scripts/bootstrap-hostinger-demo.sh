#!/usr/bin/env bash
# Bootstrap a clean Hostinger demo stack.  Run once after the first deployment.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
COMPOSE_FILE="docker-compose.hostinger.yml"
ENV_FILE=".env.demo"

: "${SEED_ADMIN_EMAIL:?SEED_ADMIN_EMAIL is required}"
: "${SEED_ADMIN_PASSWORD:?SEED_ADMIN_PASSWORD is required}"

cd "${DEPLOY_DIR}"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile maintenance run --rm db-migrate
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" run --rm \
  -e "SEED_ADMIN_EMAIL=${SEED_ADMIN_EMAIL}" \
  -e "SEED_ADMIN_PASSWORD=${SEED_ADMIN_PASSWORD}" \
  db-migrate python -m app.scripts.bootstrap_demo
