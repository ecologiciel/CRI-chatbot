#!/usr/bin/env bash
# Create an encrypted, consistent data backup of the Hostinger demo stack.
# The application is briefly unavailable while its data volumes are captured.
# Usage: BACKUP_RECIPIENT_FILE=/absolute/path/to/public-key.asc ./hostinger-cold-backup.sh
# The private decryption key must be stored independently of the VPS.
set -Eeuo pipefail
umask 077

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
BACKUP_DIR="${BACKUP_DIR:-/root/chatbot-backups}"
PROJECT="${COMPOSE_PROJECT_NAME:-chatbot-demo}"
RECIPIENT="${BACKUP_RECIPIENT_FILE:?Set BACKUP_RECIPIENT_FILE to a public OpenPGP key}"
COMPOSE=(docker compose --project-name "$PROJECT" --env-file "$DEPLOY_DIR/.env.demo" -f "$DEPLOY_DIR/docker-compose.hostinger.yml" -f "$DEPLOY_DIR/docker-compose.hostinger.local.yml")

command -v docker >/dev/null
command -v gpg >/dev/null
command -v sha256sum >/dev/null
test -r "$RECIPIENT"
test -f "$DEPLOY_DIR/.env.demo"
docker image inspect redis:7-alpine >/dev/null
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
workdir=$(mktemp -d "$BACKUP_DIR/.cold-backup.XXXXXXXX")
chmod 700 "$workdir"
mkdir -m 700 "$workdir/metadata"
# Keep GnuPG's Unix socket path short even when the backup path is long.
keydir=$(mktemp -d /tmp/codex-backup-gpg.XXXXXXXX)
chmod 700 "$keydir"
archive=""
stopped=0
running=()

cleanup() {
    local result=$?
    trap - EXIT
    if (( stopped )); then
        echo "Restarting services that were running before the backup..." >&2
        if ! "${COMPOSE[@]}" start "${running[@]}"; then
            echo "ERROR: automatic restart failed; inspect the Hostinger stack immediately." >&2
            result=1
        fi
    fi
    if [[ -n "$archive" && -f "$archive.partial" ]]; then rm -f -- "$archive.partial"; fi
    case "$workdir" in "$BACKUP_DIR"/.cold-backup.*) rm -rf -- "$workdir" ;; esac
    case "$keydir" in /tmp/codex-backup-gpg.*) rm -rf -- "$keydir" ;; esac
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' INT TERM

export GNUPGHOME="$keydir"
if ! gpg --batch --import "$RECIPIENT" >/dev/null 2>&1; then
    echo "Could not import the public backup key." >&2
    exit 1
fi
if gpg --batch --with-colons --list-secret-keys | grep -q '^sec:'; then
    echo "Provide a public key only; private keys must never be copied to the VPS." >&2
    exit 1
fi
mapfile -t fingerprints < <(gpg --batch --with-colons --list-keys | awk -F: '$1 == "pub" {want=1; next} want && $1 == "fpr" {print $10; want=0}')
if [[ ${#fingerprints[@]} -ne 1 || ! "${fingerprints[0]}" =~ ^[0-9A-F]{40,64}$ ]]; then
    echo "The recipient file must contain exactly one public key." >&2
    exit 1
fi

volume_for() {
    local service="$1" destination="$2" container volume
    container=$("${COMPOSE[@]}" ps -q "$service")
    [[ -n "$container" ]] || { echo "Missing container: $service" >&2; return 1; }
    volume=$(docker inspect -f "{{range .Mounts}}{{if eq .Destination \"$destination\"}}{{if eq .Type \"volume\"}}{{.Name}}{{end}}{{end}}{{end}}" "$container")
    [[ "$volume" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]] || { echo "Invalid volume for $service" >&2; return 1; }
    printf '%s' "$volume"
}

postgres_volume=$(volume_for postgres /var/lib/postgresql/data)
minio_volume=$(volume_for minio /data)
qdrant_volume=$(volume_for qdrant /qdrant/storage)
mapfile -t running < <("${COMPOSE[@]}" ps --status running --services)
for essential in postgres minio qdrant backend; do
    if ! printf '%s\n' "${running[@]}" | grep -Fxq "$essential"; then
        echo "Required service is not running: $essential" >&2
        exit 1
    fi
done
{
    printf 'created_utc=%s\n' "$(date -u +%FT%TZ)"
    printf 'git_commit=%s\n' "$(git -C "$DEPLOY_DIR" rev-parse HEAD)"
    printf 'postgres_image=%s\n' "$(docker inspect -f '{{.Config.Image}}' "$("${COMPOSE[@]}" ps -q postgres)")"
    printf 'minio_image=%s\n' "$(docker inspect -f '{{.Config.Image}}' "$("${COMPOSE[@]}" ps -q minio)")"
    printf 'qdrant_image=%s\n' "$(docker inspect -f '{{.Config.Image}}' "$("${COMPOSE[@]}" ps -q qdrant)")"
    printf '%s\n' 'redis_excluded=queues and sessions must not be replayed automatically'
} > "$workdir/metadata/manifest.txt"

archive="$BACKUP_DIR/hostinger-data-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz.gpg"
[[ ! -e "$archive" && ! -e "$archive.partial" ]] || { echo "Backup already exists" >&2; exit 1; }
echo "Stopping the stack for a consistent encrypted data backup..." >&2
stopped=1
"${COMPOSE[@]}" stop "${running[@]}"

# Data and the sensitive environment are streamed directly to GPG. No plaintext
# archive is written on the VPS. Redis is excluded to avoid replaying old jobs.
docker run --rm --network none --read-only --entrypoint tar \
    --mount "type=volume,src=$postgres_volume,dst=/backup/postgres,readonly" \
    --mount "type=volume,src=$minio_volume,dst=/backup/minio,readonly" \
    --mount "type=volume,src=$qdrant_volume,dst=/backup/qdrant,readonly" \
    --mount "type=bind,src=$DEPLOY_DIR/.env.demo,dst=/backup/env.demo,readonly" \
    --mount "type=bind,src=$DEPLOY_DIR/docker-compose.hostinger.yml,dst=/backup/docker-compose.hostinger.yml,readonly" \
    --mount "type=bind,src=$DEPLOY_DIR/docker-compose.hostinger.local.yml,dst=/backup/docker-compose.hostinger.local.yml,readonly" \
    --mount "type=bind,src=$workdir/metadata,dst=/backup/metadata,readonly" \
    redis:7-alpine -czf - -C /backup . \
    | gpg --batch --yes --trust-model always --recipient "${fingerprints[0]}" --encrypt --output "$archive.partial"

test -s "$archive.partial"
mv -- "$archive.partial" "$archive"
sha256sum "$archive" > "$archive.sha256"
echo "Encrypted data archive created: $archive"
echo "A separate copy and a tested restore are still required."
