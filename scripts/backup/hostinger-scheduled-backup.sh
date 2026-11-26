#!/usr/bin/env bash
# Local encrypted backup only; this does not create an off-host copy.
set -Eeuo pipefail
umask 077

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
BACKUP_DIR="${BACKUP_DIR:-/root/chatbot-backups}"
export DEPLOY_DIR BACKUP_DIR
RECIPIENT="${BACKUP_RECIPIENT_FILE:-$BACKUP_DIR/recipient-public.asc}"
MIN_FREE_KB="${BACKUP_MIN_FREE_KB:-10485760}"
MAX_ARCHIVES="${BACKUP_MAX_ARCHIVES:-120}"
[[ "$MIN_FREE_KB" =~ ^[1-9][0-9]*$ && ${#MIN_FREE_KB} -le 12 ]] || exit 2
[[ "$MAX_ARCHIVES" =~ ^[1-9][0-9]*$ && ${#MAX_ARCHIVES} -le 6 ]] || exit 2
[[ -d "$BACKUP_DIR" && ! -L "$BACKUP_DIR" ]] || { echo 'Unsafe backup directory.' >&2; exit 1; }
[[ ! -L "$BACKUP_DIR/.scheduled-backup.lock" ]] || { echo 'Unsafe backup lock.' >&2; exit 1; }
exec 7> "$BACKUP_DIR/.scheduled-backup.lock"
if ! flock -n 7; then echo 'A scheduled backup is already running.' >&2; exit 1; fi
result=$(mktemp "$BACKUP_DIR/.scheduled-result.XXXXXXXX")
state_tmp=$(mktemp "$BACKUP_DIR/.scheduled-state.XXXXXXXX")
outcome=failed
archive_name=""
finish() {
    code=$?
    trap - EXIT
    if (( code != 0 )); then outcome=failed; fi
    printf 'finished_utc=%s\nstatus=%s\n' "$(date -u +%FT%TZ)" "$outcome" > "$state_tmp"
    if [[ "$outcome" == success ]]; then printf 'archive=%s\n' "$archive_name" >> "$state_tmp"; fi
    mv -f -- "$state_tmp" "$BACKUP_DIR/scheduled-backup.status" || code=1
    rm -f -- "$result"
    exit "$code"
}
trap finish EXIT
trap 'exit 1' INT TERM

available=$(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}')
[[ "$available" =~ ^[0-9]+$ ]] && (( available >= MIN_FREE_KB )) || { echo 'Insufficient free disk space.' >&2; exit 1; }
archive_count=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'hostinger-data-*.tar.gz.gpg' -print | wc -l)
(( archive_count < MAX_ARCHIVES )) || { echo 'Archive limit reached; verify independent copies and manage retention.' >&2; exit 1; }
[[ -f "$RECIPIENT" && ! -L "$RECIPIENT" ]] || { echo 'Public backup recipient is missing.' >&2; exit 1; }
BACKUP_RECIPIENT_FILE="$RECIPIENT" BACKUP_RESULT_FILE="$result" bash "$DEPLOY_DIR/scripts/backup/hostinger-cold-backup.sh"
archive=$(cat "$result")
archive_name=${archive##*/}
[[ "$archive" == "$BACKUP_DIR/$archive_name" && "$archive_name" =~ ^hostinger-data-[0-9]{8}T[0-9]{6}Z-[0-9]+\.tar\.gz\.gpg$ ]] || { echo 'Invalid backup result path.' >&2; exit 1; }
[[ -f "$archive" && ! -L "$archive" && -f "$archive.sha256" && ! -L "$archive.sha256" ]] || { echo 'Backup or checksum is missing.' >&2; exit 1; }
expected=$(cat "$archive.sha256")
[[ "$expected" =~ ^[0-9a-f]{64}'  '"$archive_name"$ ]] || { echo 'Invalid checksum manifest.' >&2; exit 1; }
(cd "$BACKUP_DIR" && sha256sum -c "$archive_name.sha256")
outcome=success
echo "Scheduled encrypted backup verified: $archive_name"
