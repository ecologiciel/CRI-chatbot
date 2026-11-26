#!/usr/bin/env bash
set -Eeuo pipefail
fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
archive=hostinger-data-20261126T040000Z-123.tar.gz.gpg
printf 'encrypted fixture\n' > "$fixture/$archive"
printf 'checksum fixture\n' > "$fixture/$archive.sha256"
printf 'finished_utc=%s\nstatus=success\narchive=%s\n' "$(date -u +%FT%TZ)" "$archive" > "$fixture/scheduled-backup.status"
touch "$fixture/recovery-guard.heartbeat"
BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"
printf 'finished_utc=%s\nstatus=failed\n' "$(date -u +%FT%TZ)" > "$fixture/scheduled-backup.status"
if BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
printf 'finished_utc=%s\nstatus=success\narchive=%s\n' "$(date -u -d '2 days ago' +%FT%TZ)" "$archive" > "$fixture/scheduled-backup.status"
if BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
printf 'finished_utc=%s\nstatus=success\narchive=%s\n' "$(date -u +%FT%TZ)" "$archive" > "$fixture/scheduled-backup.status"
touch -d '10 minutes ago' "$fixture/recovery-guard.heartbeat"
if BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
touch "$fixture/recovery-guard.heartbeat" "$fixture/.cold-backup-services"
if BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
mkfifo "$fixture/release"
(flock -x 9; touch "$fixture/ready"; read -r _ < "$fixture/release") 9>"$fixture/.cold-backup.lock" &
holder=$!
while [[ ! -f "$fixture/ready" ]]; do sleep 0.1; done
BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"
printf 'release\n' > "$fixture/release"
wait "$holder"
echo 'Backup monitoring checks: OK'
