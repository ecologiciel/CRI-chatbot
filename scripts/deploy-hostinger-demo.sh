#!/usr/bin/env bash
# Deploy the Hostinger single-VPS demonstration stack from immutable GHCR tags.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
COMPOSE_FILE="docker-compose.hostinger.yml"
ENV_FILE=".env.demo"
IMAGE_TAG="${1:?Usage: deploy-hostinger-demo.sh <image-tag>}"

cd "${DEPLOY_DIR}"
test -f "${ENV_FILE}"
test -f "${COMPOSE_FILE}"

PREVIOUS_TAG="$(grep '^IMAGE_TAG=' "${ENV_FILE}" | cut -d= -f2 || true)"
rollback() {
  if [[ -n "${PREVIOUS_TAG}" ]]; then
    sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${PREVIOUS_TAG}/" "${ENV_FILE}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull backend frontend-demo frontend-admin
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d backend frontend-demo frontend-admin
  fi
}
trap rollback ERR

sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=${IMAGE_TAG}/" "${ENV_FILE}"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d postgres redis qdrant minio traefik
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" --profile maintenance run --rm db-migrate
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d

for attempt in $(seq 1 24); do
  if curl --fail --silent http://localhost/api/v1/health >/dev/null; then
    trap - ERR
    docker image prune -f
    exit 0
  fi
  sleep 5
done
echo "Health check failed" >&2
exit 1
