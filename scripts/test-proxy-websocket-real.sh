#!/usr/bin/env bash
# Real Traefik/PostgreSQL/Redis test with synthetic accounts and data only.
set -Eeuo pipefail
umask 077
: "${TEST_BACKEND_IMAGE:?Backend image required}"
source_dir=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d /tmp/codex-ws-proof.XXXXXXXX)
suffix=${fixture##*.}; suffix=${suffix,,}
project="test_wsproof${suffix}"
c=(docker compose --project-name "$project" -f "$fixture/compose.yml")
cleanup(){
  local rc=$?
  trap - EXIT
  if [[ "$fixture" =~ ^/tmp/codex-ws-proof\.[a-zA-Z0-9]{8}$ && "$project" =~ ^test_wsproof[a-z0-9]{8}$ ]]; then
    if (( rc != 0 )); then "${c[@]}" logs --tail 20 postgres redis traefik runner >&2 || true; fi
    "${c[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf -- "$fixture"
  else
    echo 'Invalid fixture path; refusing cleanup' >&2; rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
chmod 755 "$fixture"
cat > "$fixture/compose.yml" <<YAML
services:
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_USER: fixture, POSTGRES_PASSWORD: fixture-pass, POSTGRES_DB: ragtest_ws }
    networks: { default: { aliases: [codex-ws-pg] } }
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U fixture -d ragtest_ws"], interval: 2s, timeout: 3s, retries: 30 }
  redis:
    image: redis:7-alpine
    command: redis-server --requirepass fixture-pass
    networks: { default: { aliases: [codex-ws-redis] } }
    healthcheck: { test: ["CMD", "redis-cli", "-a", "fixture-pass", "ping"], interval: 2s, timeout: 3s, retries: 30 }
  traefik:
    image: traefik:v3.7.20
    command:
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --providers.docker.constraints=Label(\`fixture.wsproof\`,\`$project\`)
      - --providers.docker.network=${project}_default
      - --entrypoints.web.address=:8080
    volumes: ["/var/run/docker.sock:/var/run/docker.sock:ro"]
    networks: { default: { aliases: [codex-ws-traefik] } }
  runner:
    image: $TEST_BACKEND_IMAGE
    working_dir: /source/backend
    volumes: ["$source_dir:/source:ro"]
    entrypoint: ["python", "-u", "tests/integration/escalation_ws_real_services.py"]
    healthcheck: { disable: true }
    environment:
      ENVIRONMENT: development
      POSTGRES_HOST: codex-ws-pg
      POSTGRES_USER: fixture
      POSTGRES_PASSWORD: fixture-pass
      POSTGRES_DB: ragtest_ws
      REDIS_HOST: codex-ws-redis
      REDIS_PASSWORD: fixture-pass
      MINIO_ROOT_PASSWORD: fixture-pass
      JWT_SECRET_KEY: fixture-jwt-secret
      WS_FIXTURE_PROXY: '1'
      WS_FIXTURE_PROXY_PROOF: '1'
      PYTHONPATH: /source/backend
    labels:
      - fixture.wsproof=$project
      - traefik.enable=true
      - traefik.http.routers.fixture-api.rule=PathPrefix(\`/api\`)
      - traefik.http.routers.fixture-api.entrypoints=web
      - traefik.http.routers.fixture-api.middlewares=fixture-proof
      - traefik.http.routers.fixture-ws.rule=PathPrefix(\`/ws\`)
      - traefik.http.routers.fixture-ws.entrypoints=web
      - traefik.http.routers.fixture-ws.middlewares=fixture-proof,fixture-rate
      - traefik.http.middlewares.fixture-rate.ratelimit.average=5
      - traefik.http.middlewares.fixture-rate.ratelimit.burst=30
      - traefik.http.middlewares.fixture-proof.headers.customrequestheaders.X-Internal-Client-IP-Proof=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      - traefik.http.services.fixture.loadbalancer.server.port=8000
YAML
"${c[@]}" up -d --wait --wait-timeout 90 postgres redis traefik >/dev/null
"${c[@]}" run --rm --no-deps runner
echo 'Authenticated HTTP login and WebSocket via Traefik fixture: OK'
