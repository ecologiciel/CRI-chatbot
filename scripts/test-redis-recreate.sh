#!/usr/bin/env bash
# Exercise AOF continuity and policy persistence in a disposable Compose project.
set -Eeuo pipefail
fixture=$(mktemp -d /tmp/codex-redis-recreate.XXXXXXXX)
suffix=$(basename "$fixture" | tr -cd 'a-zA-Z0-9' | tr '[:upper:]' '[:lower:]')
project="test_${suffix}"
cleanup() {
    result=$?
    trap - EXIT
    if [[ "$project" =~ ^test_codexredisrecreate[a-z0-9]+$ ]]; then
        docker compose -p "$project" -f "$fixture/new.yml" down --volumes --remove-orphans >/dev/null 2>&1 || result=1
        rm -rf -- "$fixture"
    else
        echo 'Unsafe fixture project; refusing cleanup' >&2
        result=1
    fi
    exit "$result"
}
trap cleanup EXIT
cat > "$fixture/new.yml" <<'YAML'
services:
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --maxmemory 20mb --maxmemory-policy noeviction
    volumes: [data:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 1s
      timeout: 2s
      retries: 20
volumes:
  data:
YAML
sed 's/maxmemory-policy noeviction/maxmemory-policy allkeys-lru/' "$fixture/new.yml" > "$fixture/old.yml"
old=(docker compose -p "$project" -f "$fixture/old.yml")
new=(docker compose -p "$project" -f "$fixture/new.yml")
"${old[@]}" up -d --wait redis >/dev/null
"${old[@]}" exec -T redis redis-cli SET fixture:accepted-job accepted >/dev/null
"${old[@]}" exec -T redis redis-cli ZADD fixture:queue 1 job-one >/dev/null
"${old[@]}" exec -T redis redis-cli CONFIG SET maxmemory-policy noeviction >/dev/null
"${new[@]}" up -d --no-deps --force-recreate --wait redis >/dev/null
check() {
    [[ $("${new[@]}" exec -T redis redis-cli GET fixture:accepted-job | tr -d '\r') == accepted ]]
    [[ $("${new[@]}" exec -T redis redis-cli ZCARD fixture:queue | tr -d '\r') == 1 ]]
    [[ $("${new[@]}" exec -T redis redis-cli --raw CONFIG GET maxmemory-policy | tr -d '\r' | tail -1) == noeviction ]]
}
check
"${new[@]}" restart redis >/dev/null
for attempt in $(seq 1 30); do
    if "${new[@]}" exec -T redis redis-cli ping >/dev/null 2>&1; then break; fi
    (( attempt < 30 )) || exit 1
    sleep 1
done
check
echo 'REDIS_AOF_RECREATE_AND_RESTART_OK'
