#!/usr/bin/env bash
# Invoked independently of the backup process, for example by host cron.
set -Eeuo pipefail
umask 077

DEPLOY_DIR="${DEPLOY_DIR:-/opt/chatbot-demo}"
BACKUP_DIR="${BACKUP_DIR:-/root/chatbot-backups}"
journal="$BACKUP_DIR/.cold-backup-services"
lock="$BACKUP_DIR/.cold-backup.lock"

# During a normal backup the journal is expected. Leave its owner alone.
[[ -e "$journal" || -L "$journal" ]] || exit 0
[[ -d "$BACKUP_DIR" && ! -L "$lock" ]] || { echo 'Unsafe backup lock.' >&2; exit 1; }
exec 7> "$lock"
if ! flock -n 7; then exit 0; fi
flock -u 7
exec 7>&-

# The recovery script takes the authoritative locks again and validates both
# the KMS journal and the recorded service names before starting anything.
echo "$(date -u +%FT%TZ) Attempting interrupted backup recovery."
exec bash "$DEPLOY_DIR/scripts/backup/hostinger-cold-backup.sh" --recover
