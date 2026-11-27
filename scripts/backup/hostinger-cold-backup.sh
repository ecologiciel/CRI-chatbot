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
RECIPIENT="${BACKUP_RECIPIENT_FILE:-}"
STOP_TIMEOUT="${BACKUP_STOP_TIMEOUT_SECONDS:-780}"
[[ "$STOP_TIMEOUT" =~ ^[1-9][0-9]*$ && ${#STOP_TIMEOUT} -le 5 ]] || { echo "Invalid backup stop timeout." >&2; exit 2; }
MODE="${1:-backup}"
[[ "$MODE" == backup || "$MODE" == --recover ]] || { echo "Usage: $0 [--recover]" >&2; exit 2; }
COMPOSE=(docker compose --project-name "$PROJECT" --env-file "$DEPLOY_DIR/.env.demo" -f "$DEPLOY_DIR/docker-compose.hostinger.yml" -f "$DEPLOY_DIR/docker-compose.hostinger.local.yml" --profile whatsapp-durable --profile dossier-import --profile dossier-outbox)

command -v docker >/dev/null
command -v flock >/dev/null
test -f "$DEPLOY_DIR/.env.demo"
# A shared lock prevents the KMS database/configuration switch from racing a
# backup. Rotation holds the same lock exclusively for the whole operation.
if [[ -L "$DEPLOY_DIR/.kms-rotation.lock" ]]; then
    echo "Unsafe KMS maintenance lock." >&2
    exit 1
fi
exec 8> "$DEPLOY_DIR/.kms-rotation.lock"
chmod 600 "$DEPLOY_DIR/.kms-rotation.lock"
if ! flock -s -n 8; then
    echo "KMS maintenance is in progress; backup postponed." >&2
    exit 1
fi
if [[ -e "$DEPLOY_DIR/.kms-maintenance/journal" ]]; then
    echo "Unfinished KMS maintenance: recover it before running a backup or restarting services." >&2
    exit 1
fi
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
exec 9> "$BACKUP_DIR/.cold-backup.lock"
if ! flock -n 9; then
    echo "Another cold backup is already running." >&2
    exit 1
fi
journal="$BACKUP_DIR/.cold-backup-services"
if [[ "$MODE" == --recover ]]; then
    [[ -f "$journal" && ! -L "$journal" ]] || { echo "No safe backup recovery journal exists." >&2; exit 1; }
    mapfile -t recovery_services < "$journal"
    mapfile -t known_services < <("${COMPOSE[@]}" config --services)
    (( ${#recovery_services[@]} > 0 && ${#recovery_services[@]} <= ${#known_services[@]} )) || { echo "Invalid recovery journal." >&2; exit 1; }
    for service in "${recovery_services[@]}"; do
        [[ "$service" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] && printf '%s\n' "${known_services[@]}" | grep -Fxq -- "$service" || { echo "Invalid service in recovery journal." >&2; exit 1; }
    done
    "${COMPOSE[@]}" start "${recovery_services[@]}"
    for service in "${recovery_services[@]}"; do
        container=$("${COMPOSE[@]}" ps -q "$service")
        [[ -n "$container" ]] || { echo "Missing recovered service: $service" >&2; exit 1; }
        for attempt in $(seq 1 150); do
            state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")
            [[ "$state" == healthy || "$state" == running ]] && break
            sleep 2
        done
        [[ "$state" == healthy || "$state" == running ]] || { echo "Recovered service is not ready: $service ($state)" >&2; exit 1; }
    done
    rm -f -- "$journal"
    echo "Previously running services restarted and ready."
    exit 0
fi
[[ ! -e "$journal" && ! -L "$journal" ]] || { echo "Unfinished backup: inspect and run $0 --recover before another backup." >&2; exit 1; }
command -v gpg >/dev/null
command -v sha256sum >/dev/null
docker image inspect redis:7-alpine >/dev/null
[[ -n "$RECIPIENT" && -r "$RECIPIENT" ]] || { echo "Set BACKUP_RECIPIENT_FILE to a readable public OpenPGP key." >&2; exit 1; }
workdir=$(mktemp -d "$BACKUP_DIR/.cold-backup.XXXXXXXX")
chmod 700 "$workdir"
mkdir -m 700 "$workdir/metadata"
# Keep GnuPG's Unix socket path short even when the backup path is long.
keydir=$(mktemp -d /tmp/codex-backup-gpg.XXXXXXXX)
chmod 700 "$keydir"
archive=""
stopped=0
running=()

services_ready() {
    local service container state attempt
    for service in "${running[@]}"; do
        container=$("${COMPOSE[@]}" ps -q "$service") || return 1
        [[ -n "$container" ]] || return 1
        for attempt in $(seq 1 150); do
            state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container") || return 1
            [[ "$state" == healthy || "$state" == running ]] && break
            sleep 2
        done
        if [[ "$state" != healthy && "$state" != running ]]; then
            echo "Service did not become ready after backup: $service ($state)" >&2
            return 1
        fi
    done
}

cleanup() {
    local result=$?
    trap - EXIT
    if (( stopped )); then
        echo "Restarting services that were running before the backup..." >&2
        if ! "${COMPOSE[@]}" start "${running[@]}"; then
            echo "ERROR: automatic restart failed; inspect the Hostinger stack immediately." >&2
            result=1
        elif ! services_ready; then
            echo "ERROR: one or more services did not become ready after the backup." >&2
            result=1
        else
            rm -f -- "$journal"
        fi
    fi
    if [[ -n "$archive" && -f "$archive.partial" ]]; then rm -f -- "$archive.partial"; fi
    case "$workdir" in "$BACKUP_DIR"/.cold-backup.*) rm -rf -- "$workdir" ;; esac
    case "$keydir" in /tmp/codex-backup-gpg.*) rm -rf -- "$keydir" ;; esac
    exit "$result"
}
trap cleanup EXIT
trap 'exit 1' INT TERM

# Compose refers to this bind-mounted configuration outside the data volumes.
# Preserve it in the encrypted archive; signatures can be downloaded again.
antivirus_config="$DEPLOY_DIR/docker/clamav/clamd.conf"
if grep -Eq '^[[:space:]]*antivirus:[[:space:]]*$' "$DEPLOY_DIR/docker-compose.hostinger.yml"; then
    [[ -f "$antivirus_config" && ! -L "$antivirus_config" && -r "$antivirus_config" ]] || {
        echo "Antivirus configuration is missing or unreadable; refusing an incomplete backup." >&2
        exit 1
    }
    mkdir -m 700 -p "$workdir/metadata/runtime/docker/clamav"
    cp -- "$antivirus_config" "$workdir/metadata/runtime/docker/clamav/clamd.conf"
fi

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
    printf 'postgres_image_id=%s\n' "$(docker inspect -f '{{.Image}}' "$("${COMPOSE[@]}" ps -q postgres)")"
    printf 'minio_image=%s\n' "$(docker inspect -f '{{.Config.Image}}' "$("${COMPOSE[@]}" ps -q minio)")"
    printf 'minio_image_id=%s\n' "$(docker inspect -f '{{.Image}}' "$("${COMPOSE[@]}" ps -q minio)")"
    printf 'qdrant_image=%s\n' "$(docker inspect -f '{{.Config.Image}}' "$("${COMPOSE[@]}" ps -q qdrant)")"
    printf 'qdrant_image_id=%s\n' "$(docker inspect -f '{{.Image}}' "$("${COMPOSE[@]}" ps -q qdrant)")"
    printf 'backend_image_id=%s\n' "$(docker inspect -f '{{.Image}}' "$("${COMPOSE[@]}" ps -q backend)")"
    printf '%s\n' 'redis_excluded=queues and sessions must not be replayed automatically'
} > "$workdir/metadata/manifest.txt"

archive="$BACKUP_DIR/hostinger-data-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz.gpg"
[[ ! -e "$archive" && ! -e "$archive.partial" ]] || { echo "Backup already exists" >&2; exit 1; }
echo "Stopping the stack for a consistent encrypted data backup..." >&2
printf '%s\n' "${running[@]}" > "$workdir/running-services"
mv -- "$workdir/running-services" "$journal"
stopped=1
"${COMPOSE[@]}" stop --timeout "$STOP_TIMEOUT" "${running[@]}"

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
(cd "$BACKUP_DIR" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")
if [[ -n "${BACKUP_RESULT_FILE:-}" ]]; then
    printf '%s\n' "$archive" > "$BACKUP_RESULT_FILE"
fi
echo "Encrypted data archive created: $archive"
echo "A separate copy and a tested restore are still required."
