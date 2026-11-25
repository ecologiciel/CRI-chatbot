#!/usr/bin/env bash
# Restore a fully synthetic encrypted backup into disposable real data services.
set -Eeuo pipefail
umask 077
root="${BACKUP_TEST_ROOT:-/tmp}"
fixture=$(mktemp -d "$root/hostinger-real-test.XXXXXXXX")
keydir=$(mktemp -d /tmp/codex-real-restore-gpg.XXXXXXXX)
suffix=$(basename "$fixture" | tr -cd 'a-zA-Z0-9' | tr '[:upper:]' '[:lower:]')
project="test_${suffix}"
restore="${project}restore"
compose=(docker compose --project-name "$project" --env-file "$fixture/.env.demo" -f "$fixture/docker-compose.hostinger.yml" -f "$fixture/docker-compose.hostinger.local.yml")
clone=(docker compose --project-name "$restore" --env-file "$fixture/.env.demo" -f "$fixture/docker-compose.hostinger.yml" -f "$fixture/docker-compose.hostinger.local.yml")

cleanup() {
    local result=$?
    trap - EXIT
    if [[ "$project" =~ ^test_hostingerrealtest[a-z0-9]+$ && "$restore" == "${project}restore" ]]; then
        "${clone[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || result=1
        "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || result=1
    else
        echo 'Invalid fixture project; refusing cleanup' >&2
        result=1
    fi
    case "$fixture" in "$root"/hostinger-real-test.*) rm -rf -- "$fixture" ;; esac
    case "$keydir" in /tmp/codex-real-restore-gpg.*) rm -rf -- "$keydir" ;; esac
    exit "$result"
}
trap cleanup EXIT

cat > "$fixture/docker-compose.hostinger.yml" <<'YAML'
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: fixturedb
      POSTGRES_USER: fixture
      POSTGRES_PASSWORD: fixture-password
    volumes: [pg:/var/lib/postgresql/data]
  minio:
    image: dappros/minio:RELEASE.2025-09-07T16-13-09Z
    command: server /data
    environment:
      MINIO_ROOT_USER: fixture-user
      MINIO_ROOT_PASSWORD: fixture-password
    volumes: [objects:/data]
  qdrant:
    image: qdrant/qdrant:v1.12.1
    volumes: [vectors:/qdrant/storage]
  backend:
    image: chatbot-demo-backend:ed3192b5b1d5ff4e94522eb9de9a5ce1972c04af
    entrypoint: [sleep, '600']
volumes:
  pg:
  objects:
  vectors:
YAML
printf 'services: {}\n' > "$fixture/docker-compose.hostinger.local.yml"
printf 'SECRET=fixture-only\n' > "$fixture/.env.demo"
git -C "$fixture" init -q
git -C "$fixture" -c user.name=Fixture -c user.email=fixture@example.com -c commit.gpgsign=false commit --allow-empty -qm fixture
mkdir -m 700 "$fixture/backups" "$fixture/extracted"
chmod 700 "$keydir"
export GNUPGHOME="$keydir"
gpg --batch --pinentry-mode loopback --passphrase '' --quick-generate-key 'Real Restore Fixture <restore@example.com>' rsa2048 encr 1d >/dev/null 2>&1
gpg --batch --armor --export 'restore@example.com' > "$fixture/recipient.asc"
"${compose[@]}" up -d >/dev/null
pg=$("${compose[@]}" ps -q postgres)
app=$("${compose[@]}" ps -q backend)
for attempt in $(seq 1 60); do docker exec "$pg" pg_isready -U fixture -d fixturedb >/dev/null 2>&1 && break; sleep 1; done
docker exec "$pg" psql -v ON_ERROR_STOP=1 -U fixture -d fixturedb -c "CREATE TABLE recovery_fixture (value text NOT NULL); INSERT INTO recovery_fixture VALUES ('postgres-restored');" >/dev/null
docker exec -i "$app" python - <<'PY'
import asyncio, io, time
import aiohttp, httpx
from miniopy_async import Minio

async def main():
    for attempt in range(60):
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                if (await client.get('http://qdrant:6333/')).status_code == 200 and (await client.get('http://minio:9000/minio/health/live')).status_code == 200:
                    break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    else:
        raise RuntimeError('Fixture data services did not start')
    minio = Minio('minio:9000', access_key='fixture-user', secret_key='fixture-password', secure=False)
    await minio.make_bucket('restore-fixture')
    content = b'minio-restored'
    await minio.put_object('restore-fixture', 'example.txt', io.BytesIO(content), len(content))
    async with httpx.AsyncClient(timeout=15) as client:
        (await client.put('http://qdrant:6333/collections/restore_fixture', json={'vectors': {'size': 2, 'distance': 'Cosine'}})).raise_for_status()
        (await client.put('http://qdrant:6333/collections/restore_fixture/points?wait=true', json={'points': [{'id': 1, 'vector': [1.0, 0.0], 'payload': {'value': 'qdrant-restored'}}]})).raise_for_status()
asyncio.run(main())
PY

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"
archive=$(find "$fixture/backups" -maxdepth 1 -name '*.tar.gz.gpg' -type f -print)
[[ -n "$archive" && $(printf '%s\n' "$archive" | wc -l) -eq 1 ]]
gpg --batch --pinentry-mode loopback --passphrase '' --decrypt "$archive" | tar -xzf - -C "$fixture/extracted"

# Create new, stopped containers and volumes. Restore only into their uniquely
# named test volumes, never into the source fixture or production volumes.
"${clone[@]}" create >/dev/null
for pair in "postgres:pg" "minio:objects" "qdrant:vectors"; do
    source_dir=${pair%%:*}
    volume="${restore}_${pair#*:}"
    [[ "$volume" == "${restore}_"* ]]
    docker volume inspect "$volume" >/dev/null
    docker run --rm --network none --user 0 --entrypoint sh \
        --mount "type=bind,src=$fixture/extracted/$source_dir,dst=/from,readonly" \
        --mount "type=volume,src=$volume,dst=/to" redis:7-alpine \
        -c 'cd /from && tar -cf - . | tar -C /to -xf -'
done
"${clone[@]}" start >/dev/null
restore_pg=$("${clone[@]}" ps -q postgres)
restore_app=$("${clone[@]}" ps -q backend)
for attempt in $(seq 1 60); do docker exec "$restore_pg" pg_isready -U fixture -d fixturedb >/dev/null 2>&1 && break; sleep 1; done
[[ $(docker exec "$restore_pg" psql -At -v ON_ERROR_STOP=1 -U fixture -d fixturedb -c 'SELECT value FROM recovery_fixture') == postgres-restored ]]
docker exec -i "$restore_app" python - <<'PY'
import asyncio
import aiohttp, httpx
from miniopy_async import Minio

async def main():
    for attempt in range(60):
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                if (await client.get('http://qdrant:6333/')).status_code == 200 and (await client.get('http://minio:9000/minio/health/live')).status_code == 200:
                    break
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    else:
        raise RuntimeError('Restored services did not start')
    minio = Minio('minio:9000', access_key='fixture-user', secret_key='fixture-password', secure=False)
    async with aiohttp.ClientSession() as session:
        response = await minio.get_object('restore-fixture', 'example.txt', session)
        try:
            assert await response.read() == b'minio-restored'
        finally:
            response.release()
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get('http://qdrant:6333/collections/restore_fixture/points/1')
        response.raise_for_status()
        assert response.json()['result']['payload']['value'] == 'qdrant-restored'
asyncio.run(main())
PY
echo 'Restored isolated PostgreSQL row, MinIO object and Qdrant point: OK'
