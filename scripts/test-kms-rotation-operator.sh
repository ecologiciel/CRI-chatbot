#!/usr/bin/env bash
# Real PostgreSQL/Docker integration test using only disposable synthetic data.
set -Eeuo pipefail
umask 077
image="${BACKEND_TEST_IMAGE:?Set BACKEND_TEST_IMAGE to a locally available backend image}"
test_root="${KMS_TEST_ROOT:-/tmp}"
fixture=$(mktemp -d "$test_root/codex-kms-operator.XXXXXXXX")
suffix=$(basename "$fixture" | tr -cd 'a-zA-Z0-9' | tr '[:upper:]' '[:lower:]')
project="test_${suffix}"
network="${project}-data"
compose=(docker compose --project-name "$project" --env-file "$fixture/.env.demo" -f "$fixture/docker-compose.hostinger.yml" -f "$fixture/docker-compose.hostinger.local.yml")
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
real_docker=$(command -v docker)

cleanup() {
    local result=$?
    trap - EXIT
    # Refuse to delete anything outside the freshly created fixture namespace.
    if [[ "$project" =~ ^test_codexkmsoperator[a-z0-9]+$ && "$fixture" == "$test_root"/codex-kms-operator.* ]]; then
        docker rm -f "${project}-unmanaged-writer" >/dev/null 2>&1 || true
        "${compose[@]}" --profile whatsapp-durable --profile dossier-import --profile dossier-outbox --profile agent-replies down --volumes --remove-orphans >/dev/null 2>&1 || result=1
        rm -rf -- "$fixture"
    else
        echo 'Invalid test namespace; refusing cleanup.' >&2
        result=1
    fi
    exit "$result"
}
trap cleanup EXIT

test -x "$real_docker"
docker image inspect "$image" >/dev/null
master=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
cat > "$fixture/.env.demo" <<EOF
ENVIRONMENT=development
POSTGRES_DB=kms_fixture
POSTGRES_USER=fixture
POSTGRES_PASSWORD=fixture-password
REDIS_PASSWORD=fixture-redis-password
MINIO_ROOT_PASSWORD=fixture-minio-password
KMS_MASTER_KEY=$master
BACKEND_TEST_IMAGE=$image
TEST_NETWORK=$network
EOF
cat > "$fixture/docker-compose.hostinger.yml" <<'YAML'
x-writer: &writer
  image: ${BACKEND_TEST_IMAGE}
  # PID 1 must handle SIGTERM so this test models graceful application shutdown.
  entrypoint: [python, -c, 'import signal,sys,time; signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); time.sleep(1800)']
  environment:
    KMS_MASTER_KEY: ${KMS_MASTER_KEY}
  networks: [data]
  restart: unless-stopped
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    networks: [data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fixture -d kms_fixture"]
      interval: 1s
      timeout: 3s
      retries: 60
  backend:
    <<: *writer
    healthcheck:
      test: ["CMD", "true"]
      interval: 1s
      timeout: 3s
      retries: 30
  ingestion-worker:
    <<: *writer
  learning-worker:
    <<: *writer
  purge-worker:
    <<: *writer
  whatsapp-inbox-worker:
    <<: *writer
    profiles: ["whatsapp-durable"]
  dossier-import-worker:
    <<: *writer
    profiles: ["dossier-import"]
  dossier-outbox-worker:
    <<: *writer
    profiles: ["dossier-outbox"]
  agent-reply-worker:
    <<: *writer
    profiles: ["agent-replies"]
networks:
  data:
    name: ${TEST_NETWORK}
    internal: true
YAML
printf 'services: {}\n' > "$fixture/docker-compose.hostinger.local.yml"
"${compose[@]}" up -d >/dev/null
pg=$("${compose[@]}" ps -q postgres)
for _ in $(seq 1 60); do
    [[ $(docker inspect -f '{{.State.Health.Status}}' "$pg") == healthy ]] && break
    sleep 1
done
[[ $(docker inspect -f '{{.State.Health.Status}}' "$pg") == healthy ]]

# The fixture contains two independently wrapped, known test data keys.
docker run --rm -i --network "$network" --env-file "$fixture/.env.demo" \
    --env POSTGRES_HOST=postgres --entrypoint python "$image" - <<'PY'
import asyncio, os, secrets, uuid
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core.database import get_engine, get_session_factory, close_engine
from app.models.tenant import Tenant
from app.models.tenant_key import TenantKey
import app.models  # register ORM relationships

async def run():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Tenant.__table__.create)
        await conn.run_sync(TenantKey.__table__.create)
    key = bytes.fromhex(os.environ['KMS_MASTER_KEY'])
    tenant_id = uuid.uuid4()
    async with get_session_factory().begin() as session:
        session.add(Tenant(id=tenant_id, slug='kmstest', name='Test', region='Test'))
        await session.flush()
        for version, plaintext in ((1, b'A' * 32), (2, b'B' * 32)):
            nonce = secrets.token_bytes(12)
            session.add(TenantKey(tenant_id=tenant_id, encrypted_key=nonce + AESGCM(key).encrypt(nonce, plaintext, None), key_version=version, is_active=(version == 2)))
    await close_engine()
asyncio.run(run())
PY

# Encrypt synthetic data with a disposable test key; no production key is used.
mkdir -m 700 "$fixture/keys"
export GNUPGHOME="$fixture/keys"
gpg --batch --pinentry-mode loopback --passphrase '' --quick-generate-key 'KMS Fixture <kms-fixture@example.com>' rsa2048 encr 1d >/dev/null 2>&1
printf 'synthetic fixture; no real secrets\n' | gpg --batch --yes --trust-model always --recipient kms-fixture@example.com --encrypt --output "$fixture/test.tar.gz.gpg"
(cd "$fixture" && sha256sum test.tar.gz.gpg > test.tar.gz.gpg.sha256)
original_hash=$(printf '%s' "$master" | sha256sum | cut -d' ' -f1)
unset master

# An untracked container with a KMS key on the data network must block
# maintenance before the real fixture writers are touched.
docker run -d --name "${project}-unmanaged-writer" --network "$network" \
    --env KMS_MASTER_KEY=synthetic-only --entrypoint python "$image" \
    -c 'import signal,sys,time; signal.signal(signal.SIGTERM,lambda *_:sys.exit(0)); time.sleep(1800)' >/dev/null
if timeout 90s python3 "$script_dir/kms_rotation_operator.py" rotate --deployment-dir "$fixture" \
    --project "$project" --network "$network" --backup "$fixture/test.tar.gz.gpg" >"$fixture/unmanaged.log" 2>&1; then
    echo 'An unmanaged writer was unexpectedly accepted.' >&2
    exit 1
fi
grep -q 'Another possible KMS writer' "$fixture/unmanaged.log"
[[ ! -e "$fixture/.kms-maintenance" ]]
docker stop --time 10 "${project}-unmanaged-writer" >/dev/null
if timeout 90s python3 "$script_dir/kms_rotation_operator.py" rotate --deployment-dir "$fixture" \
    --project "$project" --network "$network" --backup "$fixture/test.tar.gz.gpg" >"$fixture/unmanaged.log" 2>&1; then
    echo 'A stopped unmanaged KMS container was unexpectedly accepted.' >&2
    exit 1
fi
grep -q 'Another possible KMS writer' "$fixture/unmanaged.log"
[[ ! -e "$fixture/.kms-maintenance" ]]
for service in backend ingestion-worker learning-worker purge-worker; do
    id=$("${compose[@]}" ps -aq "$service")
    [[ $(docker inspect -f '{{.State.Running}}' "$id") == true ]]
done
docker rm -f "${project}-unmanaged-writer" >/dev/null
echo 'Unmanaged KMS writer correctly blocked the rotation.'

# The optional durable worker is an additional KMS writer and must remain
# stopped during an interrupted rotation and be restored after recovery.
"${compose[@]}" --profile whatsapp-durable --profile dossier-import --profile dossier-outbox --profile agent-replies up -d whatsapp-inbox-worker dossier-import-worker dossier-outbox-worker agent-reply-worker >/dev/null

# Proxy only this test's Docker CLI, and kill the operator after a successful
# database/configuration switch but before it can restart the writers.
mkdir "$fixture/proxy"
cat > "$fixture/proxy/docker" <<EOF
#!/bin/sh
"$real_docker" "\$@"
status=\$?
if [ "\$status" -eq 0 ] && [ "\${KMS_FIXTURE_INTERRUPT:-}" = after-apply ]; then
    case " \$* " in *' app.scripts.kms_rotation apply '*) kill -KILL "\$PPID" ;; esac
fi
if [ "\$status" -eq 0 ] && [ "\${KMS_FIXTURE_INTERRUPT:-}" = fail-backend ] && [ -f "$fixture/proxy/fail-once" ]; then
    case " \$* " in
        *' up -d --no-deps --no-build --force-recreate backend '*) rm -f "$fixture/proxy/fail-once"; exit 42 ;;
    esac
fi
exit "\$status"
EOF
chmod 700 "$fixture/proxy/docker"
set +e
PATH="$fixture/proxy:$PATH" KMS_FIXTURE_INTERRUPT=after-apply \
    timeout 180s python3 "$script_dir/kms_rotation_operator.py" rotate --deployment-dir "$fixture" \
    --project "$project" --network "$network" --backup "$fixture/test.tar.gz.gpg"
status=$?
set -e
[[ "$status" -ne 0 && -f "$fixture/.kms-maintenance/journal/READY" ]]
interrupted_hash=$(sed -n 's/^KMS_MASTER_KEY=//p' "$fixture/.env.demo" | tr -d '\n' | sha256sum | cut -d' ' -f1)
[[ "$interrupted_hash" != "$original_hash" ]]
for service in backend ingestion-worker learning-worker purge-worker whatsapp-inbox-worker dossier-import-worker dossier-outbox-worker agent-reply-worker; do
    id=$("${compose[@]}" ps -aq "$service")
    [[ $(docker inspect -f '{{.State.Running}}/{{.HostConfig.RestartPolicy.Name}}' "$id") == false/no ]]
done
echo 'Interrupted rotation kept all fixture writers stopped with restart disabled.'

# Recovery also recreates a writer container lost after the crash.
missing=$("${compose[@]}" ps -aq learning-worker)
docker rm "$missing" >/dev/null

timeout 180s python3 "$script_dir/kms_rotation_operator.py" recover --deployment-dir "$fixture" --project "$project" --network "$network"
[[ ! -e "$fixture/.kms-maintenance" ]]
recovered_hash=$(sed -n 's/^KMS_MASTER_KEY=//p' "$fixture/.env.demo" | tr -d '\n' | sha256sum | cut -d' ' -f1)
[[ "$recovered_hash" == "$original_hash" ]]
echo 'Rollback restored the original fixture master key.'

# A failure immediately after backend recreation must stop the new writer,
# roll the database/environment back, and restart every fixture writer.
touch "$fixture/proxy/fail-once"
set +e
PATH="$fixture/proxy:$PATH" KMS_FIXTURE_INTERRUPT=fail-backend \
    timeout 180s python3 "$script_dir/kms_rotation_operator.py" rotate --deployment-dir "$fixture" \
    --project "$project" --network "$network" --backup "$fixture/test.tar.gz.gpg" >"$fixture/recovery.log" 2>&1
status=$?
set -e
[[ "$status" -ne 0 && ! -e "$fixture/proxy/fail-once" && ! -e "$fixture/.kms-maintenance" ]]
grep -q 'Maintenance recovered; writers restarted' "$fixture/recovery.log"
recovered_hash=$(sed -n 's/^KMS_MASTER_KEY=//p' "$fixture/.env.demo" | tr -d '\n' | sha256sum | cut -d' ' -f1)
[[ "$recovered_hash" == "$original_hash" ]]
for service in backend ingestion-worker learning-worker purge-worker whatsapp-inbox-worker dossier-import-worker dossier-outbox-worker agent-reply-worker; do
    id=$("${compose[@]}" ps -aq "$service")
    [[ $(docker inspect -f '{{.State.Running}}/{{.HostConfig.RestartPolicy.Name}}' "$id") == true/unless-stopped ]]
done
echo 'Failure after backend restart rolled back and recovered the fixture.'

timeout 180s python3 "$script_dir/kms_rotation_operator.py" rotate --deployment-dir "$fixture" --project "$project" --network "$network" --backup "$fixture/test.tar.gz.gpg"
[[ ! -e "$fixture/.kms-maintenance" ]]
rotated_hash=$(sed -n 's/^KMS_MASTER_KEY=//p' "$fixture/.env.demo" | tr -d '\n' | sha256sum | cut -d' ' -f1)
[[ "$rotated_hash" != "$original_hash" ]]

docker run --rm -i --network "$network" --env-file "$fixture/.env.demo" \
    --env POSTGRES_HOST=postgres --entrypoint python "$image" - <<'PY'
import asyncio, os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from app.core.database import get_session_factory, close_engine
from app.models.tenant_key import TenantKey
import app.models

async def run():
    async with get_session_factory()() as session:
        keys = list((await session.execute(select(TenantKey).order_by(TenantKey.key_version))).scalars())
    cipher = AESGCM(bytes.fromhex(os.environ['KMS_MASTER_KEY']))
    assert [cipher.decrypt(bytes(k.encrypted_key)[:12], bytes(k.encrypted_key)[12:], None) for k in keys] == [b'A' * 32, b'B' * 32]
    await close_engine()
asyncio.run(run())
PY
for service in backend ingestion-worker learning-worker purge-worker whatsapp-inbox-worker dossier-import-worker dossier-outbox-worker agent-reply-worker; do
    id=$("${compose[@]}" ps -aq "$service")
    [[ $(docker inspect -f '{{.State.Running}}/{{.HostConfig.RestartPolicy.Name}}' "$id") == true/unless-stopped ]]
done
echo 'Real PostgreSQL fixture rotation, interruption recovery and data keys: OK'
