#!/usr/bin/env bash
# Local machine-readable monitoring check; it does not send external alerts.
set -Eeuo pipefail
BACKUP_DIR="${BACKUP_DIR:-/root/chatbot-backups}"
MAX_BACKUP_AGE_SECONDS="${BACKUP_MAX_AGE_SECONDS:-108000}"
MAX_GUARD_AGE_SECONDS="${BACKUP_GUARD_MAX_AGE_SECONDS:-300}"
for limit in "$MAX_BACKUP_AGE_SECONDS" "$MAX_GUARD_AGE_SECONDS"; do
    [[ "$limit" =~ ^[1-9][0-9]*$ && ${#limit} -le 9 ]] || exit 2
done
fail() { echo "BACKUP_ALERT: $*" >&2; exit 1; }
[[ -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || fail 'backup directory missing or unsafe'
status="$BACKUP_DIR/scheduled-backup.status"
heartbeat="$BACKUP_DIR/recovery-guard.heartbeat"
[[ -f "$status" && ! -L "$status" ]] || fail 'last backup status missing'
[[ -f "$heartbeat" && ! -L "$heartbeat" ]] || fail 'recovery guard heartbeat missing'
mapfile -t lines < "$status"
[[ ${#lines[@]} -eq 3 && "${lines[0]}" =~ ^finished_utc=[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ && "${lines[1]}" == status=success ]] || fail 'last backup failed or its status is invalid'
[[ "${lines[2]}" =~ ^archive=(hostinger-data-[0-9]{8}T[0-9]{6}Z-[0-9]+\.tar\.gz\.gpg)$ ]] || fail 'backup filename invalid'
archive="${BASH_REMATCH[1]}"
[[ -f "$BACKUP_DIR/$archive" && ! -L "$BACKUP_DIR/$archive" && -s "$BACKUP_DIR/$archive" ]] || fail 'last archive missing or empty'
[[ -f "$BACKUP_DIR/$archive.sha256" && ! -L "$BACKUP_DIR/$archive.sha256" && -s "$BACKUP_DIR/$archive.sha256" ]] || fail 'last checksum missing or empty'
now=$(date -u +%s)
finished=$(date -u -d "${lines[0]#finished_utc=}" +%s) || fail 'invalid backup timestamp'
guard_time=$(stat -c %Y "$heartbeat")
(( finished <= now && now - finished <= MAX_BACKUP_AGE_SECONDS )) || fail 'last backup is stale or timestamp is in the future'
(( guard_time <= now && now - guard_time <= MAX_GUARD_AGE_SECONDS )) || fail 'recovery guard heartbeat is stale or in the future'
if [[ -e "$BACKUP_DIR/.cold-backup-services" ]]; then
    [[ ! -L "$BACKUP_DIR/.cold-backup.lock" ]] || fail 'backup lock is unsafe'
    exec 8> "$BACKUP_DIR/.cold-backup.lock"
    if flock -n 8; then fail 'backup recovery journal is present'; fi
    echo 'BACKUP_OK: backup is currently running'
    exit 0
fi
echo 'BACKUP_OK: recent backup and recovery guard heartbeat found'
