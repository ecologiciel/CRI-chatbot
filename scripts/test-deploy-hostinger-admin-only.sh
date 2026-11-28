#!/usr/bin/env bash
# Real Docker rehearsal using only freshly created fixture resources.
set -Eeuo pipefail
umask 077
root=$(mktemp -d /tmp/hostinger-admin-test.XXXXXXXX)
suffix=${root##*.}; suffix=${suffix,,}
project="test_admin${suffix}"
old="${project}:old"; new="${project}:new"; bad="${project}:bad"; tag="${project}:current"
c=(docker compose --project-name "$project" --env-file "$root/.env.demo" -f "$root/docker-compose.hostinger.yml" -f "$root/docker-compose.hostinger.local.yml" --profile agent-replies --profile whatsapp-durable --profile local-wa-relay)
cleanup() {
  local rc=$?
  trap - EXIT
  if [[ "$root" =~ ^/tmp/hostinger-admin-test\.[a-zA-Z0-9]{8}$ && "$project" =~ ^test_admin[a-z0-9]{8}$ ]]; then
    "${c[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    for file in "$root"/backup/admin-release.*/admin.rollback-tag; do
      if [[ -f "$file" ]]; then
        read -r rollback_tag < "$file"
        [[ "$rollback_tag" =~ ^chatbot-demo-admin:rollback-[a-zA-Z0-9]{8}$ ]] || { echo 'Invalid fixture rollback tag' >&2; rc=1; continue; }
        docker image rm "$rollback_tag" >/dev/null 2>&1 || true
      fi
    done
    docker image rm "$old" "$new" "$bad" "$tag" >/dev/null 2>&1 || true
    rm -rf -- "$root"
  else
    echo 'Invalid fixture path; refusing cleanup' >&2; rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
mkdir -p "$root/scripts/backup" "$root/backup"
printf 'FROM redis:7-alpine\nRUN touch /fixture-healthy\nLABEL fixture=old\n' > "$root/Dockerfile"
docker build -q -t "$old" "$root" >/dev/null
printf 'FROM redis:7-alpine\nRUN touch /fixture-healthy\nLABEL fixture=new\n' > "$root/Dockerfile"
docker build -q -t "$new" "$root" >/dev/null
printf 'FROM redis:7-alpine\nLABEL fixture=bad\n' > "$root/Dockerfile"
docker build -q -t "$bad" "$root" >/dev/null
docker tag "$old" "$tag"
cat > "$root/docker-compose.hostinger.yml" <<YAML
services:
  frontend-admin:
    image: $tag
    entrypoint: ["sleep", "600"]
    healthcheck: { test: ["CMD", "test", "-f", "/fixture-healthy"], interval: 2s, timeout: 2s, retries: 2 }
  backend: { image: redis:7-alpine, entrypoint: ["sleep", "600"] }
  agent-reply-worker: { image: redis:7-alpine, entrypoint: ["sleep", "600"], profiles: ["agent-replies"] }
  whatsapp-inbox-worker: { image: redis:7-alpine, entrypoint: ["sleep", "600"], profiles: ["whatsapp-durable"] }
  whatsapp-relay: { image: redis:7-alpine, entrypoint: ["sleep", "600"], profiles: ["local-wa-relay"] }
YAML
printf 'services: {}\n' > "$root/docker-compose.hostinger.local.yml"
printf 'FIXTURE=true\n' > "$root/.env.demo"
printf '#!/usr/bin/env bash\nexit 0\n' > "$root/scripts/backup/check-hostinger-backup.sh"
cp "$(dirname "$0")/deploy-hostinger-admin-only.sh" "$root/scripts/"
cd "$root"
git init -q
git config user.email fixture@example.invalid
git config user.name fixture
git add scripts docker-compose.hostinger.yml docker-compose.hostinger.local.yml
git commit -qm fixture
head=$(git rev-parse HEAD)
"${c[@]}" up -d --wait --wait-timeout 90 frontend-admin backend agent-reply-worker whatsapp-inbox-worker whatsapp-relay >/dev/null
for service in backend agent-reply-worker whatsapp-inbox-worker whatsapp-relay; do "${c[@]}" ps -q "$service"; done > "$root/ids.before"
DEPLOY_DIR="$root" BACKUP_DIR="$root/backup" COMPOSE_PROJECT_NAME="$project" EXPECTED_HEAD="$head" CANDIDATE_ADMIN="$new" bash scripts/deploy-hostinger-admin-only.sh
[[ $(docker inspect -f '{{.Image}}' "$("${c[@]}" ps -q frontend-admin)") == "$(docker image inspect -f '{{.Id}}' "$new")" ]]
for service in backend agent-reply-worker whatsapp-inbox-worker whatsapp-relay; do "${c[@]}" ps -q "$service"; done > "$root/ids.after"
cmp "$root/ids.before" "$root/ids.after"
if DEPLOY_DIR="$root" BACKUP_DIR="$root/backup" COMPOSE_PROJECT_NAME="$project" EXPECTED_HEAD="$head" CANDIDATE_ADMIN="$bad" bash scripts/deploy-hostinger-admin-only.sh; then
  echo 'Unhealthy candidate should fail' >&2; exit 1
fi
[[ $(docker inspect -f '{{.Image}}' "$("${c[@]}" ps -q frontend-admin)") == "$(docker image inspect -f '{{.Id}}' "$new")" ]]
[[ $(docker inspect -f '{{.State.Health.Status}}' "$("${c[@]}" ps -q frontend-admin)") == healthy ]]
for service in backend agent-reply-worker whatsapp-inbox-worker whatsapp-relay; do "${c[@]}" ps -q "$service"; done > "$root/ids.rollback"
cmp "$root/ids.before" "$root/ids.rollback"
echo 'Isolated admin release, worker preservation and unhealthy-image rollback: OK'
