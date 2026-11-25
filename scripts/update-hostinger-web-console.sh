#!/usr/bin/env bash
# Update an existing Hostinger deployment without recreating its data services.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
BACKUP_DIR="${BACKUP_DIR:-/root/chatbot-backups}"
COMPOSE=(docker compose --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)

cd "$DEPLOY_DIR"
test -f .env.demo
umask 077
mkdir -p "$BACKUP_DIR"

# Fail before stopping anything if the dump or archive catalog is unreadable.
backup_file="$BACKUP_DIR/pre-update-$(date +%Y%m%d-%H%M%S)-$$.dump"
"${COMPOSE[@]}" exec -T postgres sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$backup_file"
"${COMPOSE[@]}" exec -T postgres pg_restore --list < "$backup_file" > /dev/null
echo "PostgreSQL backup catalog verified: $backup_file"

# Builds happen while the existing services remain available.
"${COMPOSE[@]}" build backend frontend-demo frontend-admin

# The old ingestion worker must not publish old-format chunks during migration.
"${COMPOSE[@]}" stop ingestion-worker learning-worker purge-worker
echo "Applying database migrations..."
"${COMPOSE[@]}" run --rm --no-deps backend alembic upgrade head

# Do not restart PostgreSQL, Redis, Qdrant, MinIO, or Traefik.
"${COMPOSE[@]}" up -d --no-deps --force-recreate backend frontend-demo frontend-admin
echo "Waiting for the API to become healthy..."
for attempt in $(seq 1 36); do
  if "${COMPOSE[@]}" exec -T backend python -m app.scripts.healthcheck; then
    "${COMPOSE[@]}" up -d --no-deps --force-recreate ingestion-worker learning-worker purge-worker
    "${COMPOSE[@]}" ps
    exit 0
  fi
  sleep 5
done

"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=100 backend >&2
exit 1
