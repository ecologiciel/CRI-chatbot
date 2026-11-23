#!/usr/bin/env bash
# Deploy from the VPS Web Console after .env.demo has been securely created.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
COMPOSE=(docker compose --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)

cd "$DEPLOY_DIR"
test -f .env.demo

"${COMPOSE[@]}" up -d --build --remove-orphans

echo "Waiting for the API to become healthy..."
for attempt in $(seq 1 36); do
  if "${COMPOSE[@]}" exec -T backend python -c "import httpx; raise SystemExit(0 if httpx.get('http://localhost:8000/api/v1/health').status_code == 200 else 1)"; then
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 5
done

"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=100 >&2
exit 1
