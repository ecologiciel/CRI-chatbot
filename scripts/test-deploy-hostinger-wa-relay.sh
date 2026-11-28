#!/usr/bin/env bash
# Exercise release and rollback on disposable Docker resources, never production.
set -Eeuo pipefail
umask 077
: "${RELAY_TEST_IMAGE:?Locally built relay image required}"
root=$(mktemp -d /tmp/hostinger-relay-test.XXXXXXXX)
suffix=${root##*.}
suffix=${suffix,,}
project="test_relay${suffix}"
tag="${project}:relay"
compose=(docker compose --project-name "$project" --env-file "$root/.env.demo" -f "$root/docker-compose.hostinger.yml" -f "$root/docker-compose.hostinger.local.yml" --profile local-wa-relay)
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ "$root" =~ ^/tmp/hostinger-relay-test\.[a-zA-Z0-9]{8}$ && "$project" =~ ^test_relay[a-z0-9]{8}$ ]]; then
    "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    docker image rm "$tag" >/dev/null 2>&1 || true
    rm -rf -- "$root"
  else
    echo 'Invalid fixture path; refusing cleanup' >&2
    rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
mkdir -p "$root/scripts/backup" "$root/backup" "$root/python/app/core"
cp "$(dirname "$0")/deploy-hostinger-wa-relay.sh" "$root/scripts/"
printf '#!/usr/bin/env bash\nexit 0\n' > "$root/scripts/backup/check-hostinger-backup.sh"
touch "$root/python/app/__init__.py" "$root/python/app/core/__init__.py"
cat > "$root/python/app/core/config.py" <<'PY'
from types import SimpleNamespace
def get_settings():
    return SimpleNamespace(whatsapp_tenant_webhook_enabled=False, whatsapp_durable_inbox_enabled=False, webhook_proxy_shared_secret='fixture')
PY
chmod 755 "$root" "$root/python" "$root/python/app" "$root/python/app/core"
chmod 644 "$root/python/app/__init__.py" "$root/python/app/core/__init__.py" "$root/python/app/core/config.py"
cat > "$root/docker-compose.hostinger.yml" <<YAML
services:
  backend:
    image: $RELAY_TEST_IMAGE
    entrypoint: ["python", "-m", "http.server", "8000"]
    working_dir: /fixture
    environment:
      PYTHONPATH: /fixture
    volumes: ["$root/python:/fixture:ro"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000', timeout=1)"]
      interval: 2s
      timeout: 2s
      retries: 10
  whatsapp-relay:
    profiles: ["local-wa-relay"]
    image: $tag
    read_only: true
    tmpfs: ["/tmp:noexec,nosuid,nodev,size=32m"]
    mem_limit: 256m
    pids_limit: 32
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    environment:
      WEBHOOK_PROXY_SHARED_SECRET: \${WEBHOOK_PROXY_SHARED_SECRET:-}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=1)"]
      interval: 2s
      timeout: 2s
      retries: 2
      start_period: 20s
YAML
printf 'services: {}\n' > "$root/docker-compose.hostinger.local.yml"
printf 'WEBHOOK_PROXY_SHARED_SECRET=fixture-secret\n' > "$root/.env.demo"
cd "$root"
git init -q
git config user.email fixture@example.invalid
git config user.name fixture
git add scripts docker-compose.hostinger.yml docker-compose.hostinger.local.yml
git commit -qm fixture
head=$(git rev-parse HEAD)
"${compose[@]}" up -d --wait --wait-timeout 90 backend >/dev/null
backend=$("${compose[@]}" ps -q backend)
DEPLOY_DIR="$root" BACKUP_DIR="$root/backup" COMPOSE_PROJECT_NAME="$project" EXPECTED_HEAD="$head" CANDIDATE_RELAY="$RELAY_TEST_IMAGE" bash scripts/deploy-hostinger-wa-relay.sh
[[ $("${compose[@]}" ps -q backend) == "$backend" ]]
[[ $(docker inspect -f '{{.State.Health.Status}}' "$("${compose[@]}" ps -q whatsapp-relay)") == healthy ]]
if DEPLOY_DIR="$root" BACKUP_DIR="$root/backup" COMPOSE_PROJECT_NAME="$project" EXPECTED_HEAD="$head" CANDIDATE_RELAY="$RELAY_TEST_IMAGE" bash scripts/deploy-hostinger-wa-relay.sh; then
  echo 'Existing relay should prevent replacement' >&2
  exit 1
fi
"${compose[@]}" rm -sf whatsapp-relay >/dev/null
docker image rm "$tag" >/dev/null
printf 'WEBHOOK_PROXY_SHARED_SECRET=\n' > "$root/.env.demo"
if DEPLOY_DIR="$root" BACKUP_DIR="$root/backup" COMPOSE_PROJECT_NAME="$project" EXPECTED_HEAD="$head" CANDIDATE_RELAY="$RELAY_TEST_IMAGE" bash scripts/deploy-hostinger-wa-relay.sh; then
  echo 'Invalid relay configuration should fail' >&2
  exit 1
fi
[[ $("${compose[@]}" ps -q backend) == "$backend" ]]
[[ $(docker inspect -f '{{.State.Running}}' "$backend") == true ]]
[[ -z $("${compose[@]}" ps --status running -q whatsapp-relay) ]]
echo 'Isolated relay deployment, duplicate protection, and failed-start rollback: OK'
