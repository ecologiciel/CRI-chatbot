#!/usr/bin/env bash
# Provision the ONSSA tenant and submit the collected corpus to the KB pipeline.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
COMPOSE_FILE="docker-compose.hostinger.yml"
ENV_FILE=".env.demo"

: "${DEMO_ADMIN_EMAIL:?DEMO_ADMIN_EMAIL is required}"
: "${DEMO_ADMIN_PASSWORD:?DEMO_ADMIN_PASSWORD is required}"

cd "${DEPLOY_DIR}"
python3 scripts/collect_onssa_demo.py --output-dir var/onssa-corpus
cp docs/demos/onssa/manifest.json var/onssa-corpus/manifest.json
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" run --rm \
  -e "DEMO_ADMIN_EMAIL=${DEMO_ADMIN_EMAIL}" \
  -e "DEMO_ADMIN_PASSWORD=${DEMO_ADMIN_PASSWORD}" \
  -v "${PWD}/var/onssa-corpus:/corpus:ro" \
  backend python -m app.scripts.import_onssa_demo
