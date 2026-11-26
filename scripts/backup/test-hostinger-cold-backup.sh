#!/usr/bin/env bash
# Integration test using an isolated disposable Compose project and test keys.
set -Eeuo pipefail
export BACKUP_STOP_TIMEOUT_SECONDS=2
umask 077
root="${BACKUP_TEST_ROOT:-/tmp}"
fixture=$(mktemp -d "$root/hostinger-backup-test.XXXXXXXX")
suffix=$(basename "$fixture" | tr -cd 'a-zA-Z0-9' | tr '[:upper:]' '[:lower:]')
project="test_${suffix}"
compose=(docker compose --project-name "$project" --env-file "$fixture/.env.demo" -f "$fixture/docker-compose.hostinger.yml" -f "$fixture/docker-compose.hostinger.local.yml")
lock_pid=""

cleanup() {
    local result=$?
    trap - EXIT
    if [[ -n "$lock_pid" ]]; then kill "$lock_pid" 2>/dev/null || true; fi
    # Only the freshly generated test project and its disposable volumes.
    if [[ "$project" =~ ^test_hostingerbackuptest[a-z0-9]+$ ]]; then
        "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || result=1
    else
        echo "Invalid fixture project; refusing cleanup" >&2
        result=1
    fi
    case "$fixture" in "$root"/hostinger-backup-test.*) rm -rf -- "$fixture" ;; esac
    exit "$result"
}
trap cleanup EXIT

cat > "$fixture/docker-compose.hostinger.yml" <<'YAML'
services:
  postgres:
    image: redis:7-alpine
    entrypoint: [sh, -c]
    command: ['echo postgres-fixture > /var/lib/postgresql/data/marker; exec sleep 600']
    volumes: [pg:/var/lib/postgresql/data]
  minio:
    image: redis:7-alpine
    entrypoint: [sh, -c]
    command: ['echo minio-fixture > /data/marker; exec sleep 600']
    volumes: [objects:/data]
  qdrant:
    image: redis:7-alpine
    entrypoint: [sh, -c]
    command: ['echo qdrant-fixture > /qdrant/storage/marker; exec sleep 600']
    volumes: [vectors:/qdrant/storage]
  backend:
    image: redis:7-alpine
    entrypoint: [sleep, '600']
volumes:
  pg:
  objects:
  vectors:
YAML
printf 'services: {}\n' > "$fixture/docker-compose.hostinger.local.yml"
printf 'SECRET=fixture-only\n' > "$fixture/.env.demo"
mkdir -p "$fixture/docker/clamav"
printf 'TCPSocket 3310\n' > "$fixture/docker/clamav/clamd.conf"
git -C "$fixture" init -q
git -C "$fixture" -c user.name=Fixture -c user.email=fixture@example.com -c commit.gpgsign=false commit --allow-empty -qm fixture
mkdir -m 700 "$fixture/keys" "$fixture/backups" "$fixture/extracted"
export GNUPGHOME="$fixture/keys"
gpg --batch --pinentry-mode loopback --passphrase '' --quick-generate-key 'Backup Fixture <fixture@example.com>' rsa2048 encr 1d >/dev/null 2>&1
gpg --batch --armor --export 'fixture@example.com' > "$fixture/recipient.asc"
"${compose[@]}" up -d >/dev/null
for service in postgres minio qdrant; do
    container=$("${compose[@]}" ps -q "$service")
    for attempt in $(seq 1 30); do
        case "$service" in postgres) marker=/var/lib/postgresql/data/marker ;; minio) marker=/data/marker ;; qdrant) marker=/qdrant/storage/marker ;; esac
        docker exec "$container" test -s "$marker" && break
        sleep 1
    done
    docker exec "$container" test -s "$marker"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$fixture/scripts/backup"
cp "$script_dir/hostinger-cold-backup.sh" "$fixture/scripts/backup/hostinger-cold-backup.sh"
DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"
archive=$(find "$fixture/backups" -maxdepth 1 -name '*.tar.gz.gpg' -type f -print)
[[ -n "$archive" && $(printf '%s\n' "$archive" | wc -l) -eq 1 ]]
(cd "$fixture/backups" && sha256sum -c "$(basename "$archive").sha256")
gpg --batch --pinentry-mode loopback --passphrase '' --decrypt "$archive" | tar -xzf - -C "$fixture/extracted"
grep -Fxq postgres-fixture "$fixture/extracted/postgres/marker"
grep -Fxq minio-fixture "$fixture/extracted/minio/marker"
grep -Fxq qdrant-fixture "$fixture/extracted/qdrant/marker"
grep -Fxq SECRET=fixture-only "$fixture/extracted/env.demo"
test -f "$fixture/extracted/metadata/manifest.txt"
[[ $("${compose[@]}" ps --status running --services | wc -l) -eq 4 ]]

# A production-like antivirus bind mount must be captured inside encryption.
# Disabling its Docker service for this synthetic test keeps the fixture small.
sed -i '/^services:/a\  antivirus:\n    image: redis:7-alpine\n    entrypoint: [sleep, "600"]' "$fixture/docker-compose.hostinger.yml"
"${compose[@]}" up -d antivirus >/dev/null
DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"
archive_with_av=$(find "$fixture/backups" -maxdepth 1 -name '*.tar.gz.gpg' -type f ! -samefile "$archive" -print)
[[ -n "$archive_with_av" && $(printf '%s\n' "$archive_with_av" | wc -l) -eq 1 ]]
gpg --batch --pinentry-mode loopback --passphrase '' --decrypt "$archive_with_av" | tar -xzf - -C "$fixture/extracted"
grep -Fxq 'TCPSocket 3310' "$fixture/extracted/metadata/runtime/docker/clamav/clamd.conf"
mv "$fixture/docker/clamav/clamd.conf" "$fixture/docker/clamav/clamd.conf.saved"
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"; then
    echo 'Backup without required antivirus configuration was unexpectedly accepted' >&2
    exit 1
fi
mv "$fixture/docker/clamav/clamd.conf.saved" "$fixture/docker/clamav/clamd.conf"
"${compose[@]}" stop antivirus >/dev/null
sed -i '/^  antivirus:$/,+2d' "$fixture/docker-compose.hostinger.yml"

# Verify the scheduler refuses insufficient capacity without stopping the
# stack, and records a successful verified encrypted archive otherwise.
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" BACKUP_MIN_FREE_KB=999999999999 bash "$script_dir/hostinger-scheduled-backup.sh"; then
    echo 'Scheduled backup ignored the disk-space threshold' >&2
    exit 1
fi
grep -Fxq 'status=failed' "$fixture/backups/scheduled-backup.status"
[[ $("${compose[@]}" ps --status running --services | wc -l) -eq 4 ]]
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" BACKUP_MIN_FREE_KB=1 BACKUP_MAX_ARCHIVES=1 bash "$script_dir/hostinger-scheduled-backup.sh"; then
    echo 'Scheduled backup ignored the archive limit' >&2
    exit 1
fi
grep -Fxq 'status=failed' "$fixture/backups/scheduled-backup.status"
DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" BACKUP_MIN_FREE_KB=1 bash "$script_dir/hostinger-scheduled-backup.sh"
grep -Fxq 'status=success' "$fixture/backups/scheduled-backup.status"
[[ -z $(find "$fixture/backups" -name '.scheduled-result.*' -o -name '.scheduled-state.*') ]]

# Concurrent archives could otherwise restart writers in the middle of a
# second capture. The second process must fail before stopping anything.
mkfifo "$fixture/release-lock"
( flock -x 9; touch "$fixture/lock-ready"; read -r _ < "$fixture/release-lock" ) 9>"$fixture/backups/.cold-backup.lock" &
lock_pid=$!
for attempt in $(seq 1 30); do [[ -f "$fixture/lock-ready" ]] && break; sleep 1; done
test -f "$fixture/lock-ready"
printf '%s\n' backend > "$fixture/backups/.cold-backup-services"
DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" bash "$script_dir/hostinger-backup-recovery-guard.sh"
test -f "$fixture/backups/.cold-backup-services"
rm "$fixture/backups/.cold-backup-services"
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"; then
    echo 'A concurrent backup was unexpectedly accepted' >&2
    exit 1
fi
[[ $("${compose[@]}" ps --status running --services | wc -l) -eq 4 ]]
printf 'release\n' > "$fixture/release-lock"
wait "$lock_pid"
lock_pid=""

# Backup and master-key maintenance must never overlap.
mkfifo "$fixture/release-kms-lock"
( flock -x 9; touch "$fixture/kms-lock-ready"; read -r _ < "$fixture/release-kms-lock" ) 9>"$fixture/.kms-rotation.lock" &
lock_pid=$!
for attempt in $(seq 1 30); do [[ -f "$fixture/kms-lock-ready" ]] && break; sleep 1; done
test -f "$fixture/kms-lock-ready"
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"; then
    echo 'A backup was unexpectedly accepted during KMS maintenance' >&2
    exit 1
fi
[[ $("${compose[@]}" ps --status running --services | wc -l) -eq 4 ]]
printf 'release\n' > "$fixture/release-kms-lock"
wait "$lock_pid"
lock_pid=""

# A signing-only key cannot encrypt. Verify that a failure after stop restarts
# the original services and leaves no plaintext or partial archive.
gpg --batch --pinentry-mode loopback --passphrase '' --quick-generate-key 'Signing Fixture <sign@example.com>' rsa2048 sign 1d >/dev/null 2>&1
gpg --batch --armor --export 'sign@example.com' > "$fixture/sign-only.asc"
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/sign-only.asc" bash "$script_dir/hostinger-cold-backup.sh"; then
    echo 'A non-encryption key was unexpectedly accepted' >&2
    exit 1
fi
[[ $("${compose[@]}" ps --status running --services | wc -l) -eq 4 ]]
[[ -z $(find "$fixture/backups" -name '*.partial' -print -quit) ]]

# Simulate the operating system killing the backup immediately after stopping
# its services. A shell EXIT trap cannot run after SIGKILL.
mkdir "$fixture/docker-wrapper"
real_docker=$(command -v docker)
cat > "$fixture/docker-wrapper/docker" <<'SH'
#!/usr/bin/env bash
"$REAL_DOCKER" "$@"
result=$?
if [[ "$*" == *' stop '* && $result -eq 0 ]]; then
    kill -KILL "$PPID"
fi
exit "$result"
SH
chmod +x "$fixture/docker-wrapper/docker"
if PATH="$fixture/docker-wrapper:$PATH" REAL_DOCKER="$real_docker" DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"; then
    echo 'The injected interruption did not occur' >&2
    exit 1
fi
test -f "$fixture/backups/.cold-backup-services"
[[ -z $("${compose[@]}" ps --status running --services) ]]
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" BACKUP_RECIPIENT_FILE="$fixture/recipient.asc" bash "$script_dir/hostinger-cold-backup.sh"; then
    echo 'A new backup ignored an incomplete recovery' >&2
    exit 1
fi
mkdir -p "$fixture/.kms-maintenance"
touch "$fixture/.kms-maintenance/journal"
if DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" bash "$script_dir/hostinger-backup-recovery-guard.sh"; then
    echo 'Backup recovery ignored incomplete KMS maintenance' >&2
    exit 1
fi
rm "$fixture/.kms-maintenance/journal"
DEPLOY_DIR="$fixture" BACKUP_DIR="$fixture/backups" COMPOSE_PROJECT_NAME="$project" bash "$script_dir/hostinger-backup-recovery-guard.sh"
[[ ! -e "$fixture/backups/.cold-backup-services" ]]
[[ $("${compose[@]}" ps --status running --services | wc -l) -eq 4 ]]
echo 'Isolated encrypted backup, decryption, locking and interruption recovery: OK'
