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
set_manifest() {
    local digest
    digest=$(sha256sum "$fixture/$archive")
    printf '%s  %s\n' "${digest%% *}" "$archive" > "$fixture/$archive.sha256"
}
set_manifest
BACKUP_DIR="$fixture" BACKUP_VERIFY_HASH=1 bash "$script_dir/check-hostinger-backup.sh"
printf 'corrupted\n' >> "$fixture/$archive"
if BACKUP_DIR="$fixture" BACKUP_VERIFY_HASH=1 bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
set_manifest
printf '%s  other-file\n' "$(printf '%064d' 0)" > "$fixture/$archive.sha256"
if BACKUP_DIR="$fixture" BACKUP_VERIFY_HASH=1 bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
set_manifest
if BACKUP_DIR="$fixture" BACKUP_VERIFY_HASH=invalid bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
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
mkdir "$fixture/broken-tools"
printf '#!/bin/sh\nexit 127\n' > "$fixture/broken-tools/flock"
chmod +x "$fixture/broken-tools/flock"
if PATH="$fixture/broken-tools:$PATH" BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
touch -d '2 hours ago' "$fixture/.cold-backup-services"
if BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
touch -d '10 minutes' "$fixture/.cold-backup-services"
if BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
rm "$fixture/.cold-backup-services"
ln -s "$fixture/scheduled-backup.status" "$fixture/.cold-backup-services"
if BACKUP_DIR="$fixture" bash "$script_dir/check-hostinger-backup.sh"; then exit 1; fi
printf 'release\n' > "$fixture/release"
wait "$holder"
echo 'Backup monitoring checks: OK'
