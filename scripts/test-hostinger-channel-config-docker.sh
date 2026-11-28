#!/usr/bin/env bash
# Integration rehearsal with disposable Docker resources and synthetic data.
set -Eeuo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d "${TMPDIR:-/tmp}/codex-config-docker.XXXXXXXX")
suffix=$(basename "$fixture" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')
project="cutover${suffix}"
old="cutover-${suffix}-old:test"
new="cutover-${suffix}-new:test"
old_worker="cutover-${suffix}-worker:test"
old_admin="cutover-${suffix}-admin:test"
old_db="cutover-${suffix}-db:test"
cleanup() {
  rc=$?
  if (( rc != 0 )); then cat "$fixture/success.log" "$fixture/failure.log" 2>/dev/null || true; fi
  if [[ -f "$fixture/deploy/docker-compose.hostinger.yml" ]]; then
    docker compose -p "$project" --env-file "$fixture/deploy/.env.demo" -f "$fixture/deploy/docker-compose.hostinger.yml" down --remove-orphans >/dev/null 2>&1 || true
  fi
  docker image rm "$old" "$old_worker" "$old_admin" "$old_db" "$new" >/dev/null 2>&1 || true
  case "$fixture" in "${TMPDIR:-/tmp}"/codex-config-docker.*) rm -rf -- "$fixture" ;; *) exit 1 ;; esac
}
trap cleanup EXIT
mkdir -p "$fixture/image/app/core" "$fixture/image/app/scripts" "$fixture/deploy/scripts/backup" "$fixture/backups"
cat > "$fixture/image/Dockerfile" <<'EOF'
FROM python:3.12-alpine
ARG marker
LABEL fixture.marker=$marker
ENV FIXTURE_MARKER=$marker
COPY app /app/app
COPY psql /usr/local/bin/psql
WORKDIR /app
CMD ["python", "-m", "http.server", "8000"]
EOF
printf 'import os,sys\nsys.exit(1 if os.getenv("FAIL_HEALTH") == "1" and os.getenv("FIXTURE_MARKER") == "new" else 0)\n' > "$fixture/image/app/scripts/healthcheck.py"
printf 'import os\nclass S:\n    whatsapp_config_require_encryption = os.getenv("WHATSAPP_CONFIG_REQUIRE_ENCRYPTION") == "true"\ndef get_settings(): return S()\n' > "$fixture/image/app/core/config.py"
printf '#!/bin/sh\necho "${DB_COUNT:-0}"\n' > "$fixture/image/psql"
chmod +x "$fixture/image/psql"
docker build -q --build-arg marker=old -t "$old" "$fixture/image" >/dev/null
docker build -q --build-arg marker=new -t "$new" "$fixture/image" >/dev/null
docker build -q --build-arg marker=worker -t "$old_worker" "$fixture/image" >/dev/null
original=$(docker image inspect -f '{{.Id}}' "$old")
docker tag "$original" "$old_admin"
docker tag "$original" "$old_db"
cat > "$fixture/deploy/docker-compose.hostinger.yml" <<EOF
x-fixture: &fixture {init: true}
services:
  postgres:
    <<: *fixture
    image: $old_db
    environment: {POSTGRES_USER: fixture, POSTGRES_DB: fixture, DB_COUNT: "\${DB_COUNT:-0}"}
  backend:
    <<: *fixture
    image: $old
    environment: {FAIL_HEALTH: "\${FAIL_HEALTH:-0}", WHATSAPP_CONFIG_REQUIRE_ENCRYPTION: "\${WHATSAPP_CONFIG_REQUIRE_ENCRYPTION:-false}"}
  ingestion-worker: {<<: *fixture, image: $old}
  learning-worker: {<<: *fixture, image: $old}
  purge-worker: {<<: *fixture, image: $old}
  agent-reply-worker: {<<: *fixture, image: $old, profiles: ["agent-replies"]}
  frontend-admin: {<<: *fixture, image: $old_admin}
EOF
printf 'services: {}\n' > "$fixture/deploy/docker-compose.hostinger.local.yml"
cat > "$fixture/deploy/.initial.yml" <<EOF
services:
  ingestion-worker: {image: $old_worker}
  learning-worker: {image: $old_worker}
  purge-worker: {image: $old_worker}
EOF
printf '#!/bin/sh\nexit 0\n' > "$fixture/deploy/scripts/backup/check-hostinger-backup.sh"
cd "$fixture/deploy"
git init -q
git config user.email fixture@example.invalid
git config user.name Fixture
git add docker-compose.hostinger.yml docker-compose.hostinger.local.yml scripts/backup/check-hostinger-backup.sh
git commit -qm fixture
export DEPLOY_DIR="$fixture/deploy" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project"
export CANDIDATE_BACKEND="$new" CANDIDATE_ADMIN="$new" EXPECTED_HEAD="$(git rev-parse HEAD)"
compose=(docker compose -p "$project" --env-file .env.demo -f docker-compose.hostinger.yml -f docker-compose.hostinger.local.yml)
printf 'DB_COUNT=0\nFAIL_HEALTH=0\nWHATSAPP_CONFIG_REQUIRE_ENCRYPTION=true\n' > .env.demo
"${compose[@]}" up -d --wait --wait-timeout 60 >/dev/null
"${compose[@]}" --profile agent-replies up -d --no-deps agent-reply-worker >/dev/null
if bash "$root/deploy-hostinger-channel-config.sh" > "$fixture/active.log" 2>&1; then echo 'Expected active-worker refusal' >&2; exit 1; fi
grep -q 'Durable worker is active' "$fixture/active.log"
"${compose[@]}" --profile agent-replies stop agent-reply-worker >/dev/null
echo CONFIG_RELEASE_ACTIVE_WORKER_REFUSED_OK
bash "$root/deploy-hostinger-channel-config.sh" > "$fixture/success.log" 2>&1
grep -q '^WHATSAPP_CONFIG_REQUIRE_ENCRYPTION=true$' .env.demo
[[ "$(docker inspect -f '{{.Image}}' "$(${compose[@]} ps -q backend)")" == "$(docker image inspect -f '{{.Id}}' "$new")" ]]
echo CONFIG_RELEASE_REAL_DOCKER_SUCCESS_OK
# A failing readiness check must restore the exact prior image and environment.
"${compose[@]}" down --remove-orphans >/dev/null
printf 'DB_COUNT=0\nFAIL_HEALTH=1\nWHATSAPP_CONFIG_REQUIRE_ENCRYPTION=true\n' > .env.demo
docker tag "$original" "$old"
docker tag "$original" "$old_admin"
"${compose[@]}" up -d --wait --wait-timeout 60 >/dev/null
before=$(docker inspect -f '{{.Image}}' "$(${compose[@]} ps -q backend)")
worker_before=$(docker inspect -f '{{.Image}}' "$(${compose[@]} ps -q ingestion-worker)")
[[ "$worker_before" == "$before" ]]
if bash "$root/deploy-hostinger-channel-config.sh" > "$fixture/failure.log" 2>&1; then echo 'Expected readiness failure' >&2; exit 1; fi
grep -q '^WHATSAPP_CONFIG_REQUIRE_ENCRYPTION=true$' .env.demo
grep -q 'Previous API and administration restored' "$fixture/failure.log"
[[ "$(docker inspect -f '{{.Image}}' "$(${compose[@]} ps -q backend)")" == "$before" ]]
for service in ingestion-worker learning-worker purge-worker; do
  [[ "$(docker inspect -f '{{.Image}}' "$(${compose[@]} ps -q "$service")")" == "$worker_before" ]]
done
echo CONFIG_RELEASE_REAL_DOCKER_ROLLBACK_OK
