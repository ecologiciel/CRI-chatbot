#!/usr/bin/env bash
# PostgreSQL rehearsal. Only schema is copied; all test data and roles are fake.
set -Eeuo pipefail
umask 077
: "${TEST_BACKEND_IMAGE:?Backend image required}" "${TEST_SCHEMA_SOURCE:?Source PostgreSQL container required}"
[[ "$TEST_SCHEMA_SOURCE" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || exit 1
source_dir=$(cd "$(dirname "$0")/.." && pwd)
fixture=$(mktemp -d /tmp/codex-db-isolation.XXXXXXXX)
suffix=${fixture##*.}; suffix=${suffix,,}
net="testdbiso${suffix}"; pg="testdbiso${suffix}-pg"; runner="testdbiso${suffix}-runner"
cleanup(){
  local rc=$?
  trap - EXIT
  if [[ "$fixture" =~ ^/tmp/codex-db-isolation\.[a-zA-Z0-9]{8}$ && "$net" =~ ^testdbiso[a-z0-9]{8}$ && "$pg" == "$net-pg" && "$runner" == "$net-runner" ]]; then
    docker rm -fv "$runner" "$pg" >/dev/null 2>&1 || true
    docker network rm "$net" >/dev/null 2>&1 || true
    rm -rf -- "$fixture"
  else
    echo 'Invalid fixture resource; refusing cleanup' >&2; rc=1
  fi
  exit "$rc"
}
trap cleanup EXIT
version=$(docker exec "$TEST_SCHEMA_SOURCE" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atqc "SELECT version_num FROM public.alembic_version"')
[[ "$version" == 0019d_reply ]] || { echo 'Unexpected source schema revision' >&2; exit 1; }
docker network create "$net" >/dev/null
docker run -d --name "$pg" --network "$net" -e POSTGRES_USER=fixture -e POSTGRES_PASSWORD=fixture-pass -e POSTGRES_DB=ragtest_empty postgres:16-alpine >/dev/null
ready=0
for attempt in $(seq 1 60); do
  if docker exec "$pg" psql -U fixture -d ragtest_empty -Atqc 'SELECT 1' >/dev/null 2>&1; then
    sleep 2
    if docker exec "$pg" psql -U fixture -d ragtest_empty -Atqc 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi
  fi
  sleep 1
done
[[ "$ready" == 1 ]] || { echo 'Fixture PostgreSQL unavailable' >&2; exit 1; }
for db in ragtest_current ragtest_rls; do
  docker exec "$pg" createdb -U fixture "$db"
  docker exec "$TEST_SCHEMA_SOURCE" sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --schema-only --no-owner --no-acl' | docker exec -i "$pg" psql -U fixture -d "$db" -v ON_ERROR_STOP=1 -q
done
docker run -d --name "$runner" --network "$net" --dns 1.1.1.1 --dns 8.8.8.8 -u 0 -v "$source_dir:/source:ro" -w /source/backend --entrypoint sleep "$TEST_BACKEND_IMAGE" 600 >/dev/null
docker exec "$runner" python -m pip install -q pytest pytest-asyncio
docker exec -e TEST_RUNTIME_ROLE_DB_URL="postgresql+asyncpg://fixture:fixture-pass@$pg:5432/ragtest_empty" "$runner" python -m pytest -q tests/test_runtime_db_role_postgres.py
docker exec -e TEST_RUNTIME_ROLE_MIGRATED_DB_URL="postgresql://fixture:fixture-pass@$pg:5432/ragtest_current" "$runner" python -m pytest -q tests/test_runtime_migrated_role_postgres.py
docker exec -e TEST_WA_FENCE_DB_URL="postgresql+asyncpg://fixture:fixture-pass@$pg:5432/ragtest_rls" "$runner" python -m pytest -q tests/test_shared_row_isolation_real_postgres.py tests/test_tenant_login_isolation_real_postgres.py
echo 'ISOLATED_POSTGRES16_ROLE_AND_TENANT_TESTS_OK'
