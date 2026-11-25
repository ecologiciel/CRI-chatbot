#!/usr/bin/env bash
set -Eeuo pipefail
export PATH="/snap/bin:$PATH"
umask 077
# Restore an actual encrypted Hostinger backup into a temporary local test stack.
# Read the GPG passphrase from stdin; never include it in arguments or logs.
# Uses /dev/shm and Docker tmpfs volumes; tmpfs can be swapped by the host.
# No network ports are published, Redis is new, and no AI request is made.
# Requires a locally built current backend image and the four existing data images.
# This is a sample verification, not a production restore or exhaustive audit.
root="${BACKUP_DIR:?Set BACKUP_DIR to the local encrypted backup directory}"
expected_daemon="${BACKUP_EXPECTED_DAEMON:?Set BACKUP_EXPECTED_DAEMON to the verified local Docker daemon name}"
backend_image="${BACKUP_TEST_BACKEND_IMAGE:?Set BACKUP_TEST_BACKEND_IMAGE to the locally built backend image}"
archive="$root/donnees-hostinger.tar.gz.gpg"
[ -z "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ]
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}')" = unix:///var/run/docker.sock ]
[ "$(docker info --format '{{.Name}}')" = "$expected_daemon" ]
for image in "$backend_image" postgres:16-alpine redis:7-alpine qdrant/qdrant:v1.12.1 dappros/minio:RELEASE.2025-09-07T16-13-09Z; do docker image inspect "$image" >/dev/null; done
read -r expected_hash expected_name < "$root/donnees-hostinger.sha256"
[[ "$expected_hash" =~ ^[a-f0-9]{64}$ && "$expected_name" = donnees-hostinger.tar.gz.gpg ]]
actual_hash=$(sha256sum "$archive"); actual_hash=${actual_hash%% *}
[ "$actual_hash" = "$expected_hash" ]
work=$(mktemp -d /dev/shm/codex-real-restore.XXXXXXXX)
nonce=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
prefix="codexrealrestore${nonce}"
net="${prefix}net"; pgvol="${prefix}pg"; minvol="${prefix}min"; qvol="${prefix}qdr"
keeper="${prefix}keeper"; pg="${prefix}postgres"; minio="${prefix}minio"; qdrant="${prefix}qdrant"; redis="${prefix}redis"; api="${prefix}api"
created_containers=()
created_volumes=()
created_network=""
cleanup() {
 result=$?
 trap - EXIT
 if ((${#created_containers[@]})); then docker rm -fv "${created_containers[@]}" >/dev/null 2>&1 || result=1; fi
 for v in "${created_volumes[@]}"; do
  if [ "$(docker volume inspect -f '{{index .Labels "codex.restore-test"}}' "$v" 2>/dev/null || true)" = "$nonce" ]; then
   docker volume rm "$v" >/dev/null 2>&1 || result=1
  else
   echo RESTORE_VOLUME_LABEL_MISMATCH >&2; result=1
  fi
 done
 if [ -n "$created_network" ]; then docker network rm "$created_network" >/dev/null 2>&1 || result=1; fi
 GNUPGHOME="$work/key" gpgconf --kill gpg-agent >/dev/null 2>&1 || true
 case "$work" in /dev/shm/codex-real-restore.*) rm -rf -- "$work";; *) echo INVALID_TEMP_PATH >&2; result=1;; esac
 unset pass
 exit "$result"
}
trap cleanup EXIT
start_container() {
 local container_id
 container_id=$(docker create "$@")
 created_containers+=("$container_id")
 docker start "$container_id" >/dev/null
}
for n in "$keeper" "$pg" "$minio" "$qdrant" "$redis" "$api"; do if docker inspect "$n" >/dev/null 2>&1; then echo CONTAINER_NAME_COLLISION; exit 1; fi; done
for n in "$pgvol" "$minvol" "$qvol"; do if docker volume inspect "$n" >/dev/null 2>&1; then echo VOLUME_NAME_COLLISION; exit 1; fi; done
if docker network inspect "$net" >/dev/null 2>&1; then echo NETWORK_NAME_COLLISION; exit 1; fi
mkdir -m 700 "$work/key" "$work/data"
cp "$root/cle-recuperation/pubring.kbx" "$root/cle-recuperation/trustdb.gpg" "$work/key/"
cp -R "$root/cle-recuperation/private-keys-v1.d" "$work/key/"
chmod -R go-rwx "$work/key"
IFS= read -r pass
decrypt() { printf '%s\n' "$pass" | gpg --homedir "$work/key" --batch --quiet --pinentry-mode loopback --passphrase-fd 0 --decrypt "$archive" 2>/dev/null; }
decrypt | python3 -c 'import sys,tarfile,pathlib
with tarfile.open(fileobj=sys.stdin.buffer,mode="r|gz") as archive:
 for m in archive:
  p=pathlib.PurePosixPath(m.name)
  if p.is_absolute() or ".." in p.parts or m.isdev() or m.issym() or m.islnk(): raise SystemExit("UNSAFE_ARCHIVE_MEMBER")
print("ARCHIVE_PATHS_SAFE")'
decrypt | tar -xzf - -C "$work/data"
for d in postgres minio qdrant; do [ -d "$work/data/$d" ]; done
[ -f "$work/data/env.demo" ]
while IFS= read -r line || [ -n "$line" ]; do
 case "$line" in *=*) key=${line%%=*}; value=${line#*=};; *) continue;; esac
 case "$key" in
  POSTGRES_USER|POSTGRES_PASSWORD|POSTGRES_DB|REDIS_PASSWORD|MINIO_ROOT_USER|MINIO_ROOT_PASSWORD|GEMINI_API_KEY|WHATSAPP_APP_SECRET|WHATSAPP_VERIFY_TOKEN|JWT_SECRET_KEY|KMS_MASTER_KEY|BACKOFFICE_URL)
   case "$value" in \"*|\'*) echo UNSUPPORTED_QUOTED_ENV_VALUE; exit 1;; esac
   export "$key=$value";;
 esac
done < "$work/data/env.demo"
for key in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB REDIS_PASSWORD MINIO_ROOT_USER MINIO_ROOT_PASSWORD GEMINI_API_KEY WHATSAPP_APP_SECRET WHATSAPP_VERIFY_TOKEN JWT_SECRET_KEY KMS_MASTER_KEY BACKOFFICE_URL; do if [ -z "${!key:-}" ]; then echo "MISSING_REQUIRED_VARIABLE $key"; exit 1; fi; done
for v in "$pgvol" "$minvol" "$qvol"; do
 docker volume create --label "codex.restore-test=$nonce" --driver local --opt type=tmpfs --opt device=tmpfs --opt o=size=600m,mode=0755 "$v" >/dev/null
 created_volumes+=("$v")
done
created_network=$(docker network create --internal "$net")
[ "$(docker network inspect -f '{{.Internal}}' "$created_network")" = true ]
start_container --name "$keeper" --network none --mount "type=volume,src=$pgvol,dst=/keep/pg" --mount "type=volume,src=$minvol,dst=/keep/min" --mount "type=volume,src=$qvol,dst=/keep/qdr" --entrypoint sleep redis:7-alpine 3600 >/dev/null
for pair in "postgres:$pgvol" "minio:$minvol" "qdrant:$qvol"; do
 dir=${pair%%:*}; volume=${pair#*:}
 tar --numeric-owner -C "$work/data/$dir" -cpf - . | docker run --rm -i --network none --user 0 --mount "type=volume,src=$volume,dst=/to" --entrypoint sh redis:7-alpine -c 'cd /to && tar xpf -'
done
echo RAM_VOLUMES_RESTORED
start_container --name "$pg" --network "$net" --network-alias postgres -e POSTGRES_USER -e POSTGRES_PASSWORD -e POSTGRES_DB --mount "type=volume,src=$pgvol,dst=/var/lib/postgresql/data" postgres:16-alpine >/dev/null
start_container --name "$minio" --network "$net" --network-alias minio -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD --mount "type=volume,src=$minvol,dst=/data" dappros/minio:RELEASE.2025-09-07T16-13-09Z server /data >/dev/null
start_container --name "$qdrant" --network "$net" --network-alias qdrant --mount "type=volume,src=$qvol,dst=/qdrant/storage" qdrant/qdrant:v1.12.1 >/dev/null
start_container --name "$redis" --network "$net" --network-alias redis -e REDIS_PASSWORD --entrypoint sh redis:7-alpine -c 'exec redis-server --requirepass "$REDIS_PASSWORD"' >/dev/null
ready=0
for i in $(seq 1 60); do if docker exec "$pg" sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then ready=1; break; fi; sleep 2; done
[ "$ready" = 1 ]
start_container --name "$api" --network "$net" --network-alias api -e ENVIRONMENT=production -e POSTGRES_HOST=postgres -e POSTGRES_USER -e POSTGRES_PASSWORD -e POSTGRES_DB -e REDIS_HOST=redis -e REDIS_PASSWORD -e QDRANT_HOST=qdrant -e MINIO_ENDPOINT=minio:9000 -e MINIO_ROOT_USER -e MINIO_ROOT_PASSWORD -e GEMINI_API_KEY -e WHATSAPP_APP_SECRET -e WHATSAPP_VERIFY_TOKEN -e JWT_SECRET_KEY -e KMS_MASTER_KEY -e BACKOFFICE_URL "$backend_image" >/dev/null
ready=0
for i in $(seq 1 60); do
 if docker exec "$api" python -m app.scripts.healthcheck >/dev/null 2>&1; then ready=1; break; fi
 if [ "$(docker inspect -f '{{.State.Running}}' "$api")" != true ]; then echo RESTORED_API_NOT_RUNNING; exit 1; fi
 sleep 2
done
[ "$ready" = 1 ]
echo RESTORED_API_AND_FOUR_DEPENDENCIES_HEALTHY
docker exec -i "$api" python - <<'PY'
import asyncio
import aiohttp, asyncpg, httpx
from app.core.config import get_settings
from miniopy_async import Minio

async def main():
    settings=get_settings()
    conn=await asyncpg.connect(host=settings.postgres_host,port=settings.postgres_port,user=settings.postgres_user,password=settings.postgres_password,database=settings.postgres_db)
    try:
        n=await conn.fetchval("SELECT count(*) FROM tenant_onssa.kb_documents WHERE status='indexed'")
        row=await conn.fetchrow("SELECT d.id,d.file_path,c.qdrant_point_id FROM tenant_onssa.kb_documents d JOIN tenant_onssa.kb_chunks c ON c.document_id=d.id AND c.index_version=d.active_index_version WHERE d.status='indexed' AND d.file_path IS NOT NULL AND c.qdrant_point_id IS NOT NULL LIMIT 1")
        assert n>0 and row is not None
        print('RESTORED_INDEXED_DOCUMENTS',n)
    finally:
        await conn.close()
    storage=Minio(settings.minio_endpoint, access_key=settings.minio_root_user, secret_key=settings.minio_root_password, secure=False)
    async with aiohttp.ClientSession() as session:
        response=await storage.get_object('cri-onssa',row['file_path'],session)
        try:
            content=await response.read()
            assert len(content)>0
        finally:
            response.release()
    print('RESTORED_MINIO_DOCUMENT_OK')
    async with httpx.AsyncClient(timeout=15) as client:
        response=await client.get(f'http://qdrant:6333/collections/kb_onssa/points/{row["qdrant_point_id"]}')
        response.raise_for_status()
        point=response.json()['result']
        assert point is not None and point['payload']['document_id']==str(row['id'])
    print('RESTORED_QDRANT_POINT_MATCHES_DOCUMENT')
asyncio.run(main())
PY
echo ACTUAL_LOCAL_ARCHIVE_RESTORE_OK