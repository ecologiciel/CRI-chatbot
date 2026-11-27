#!/usr/bin/env bash
# Test updater decisions against a fake Docker CLI and synthetic local paths.
set -Eeuo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d "${TMPDIR:-/tmp}/codex-update-guard.XXXXXXXX")
cleanup() {
  case "$fixture" in "${TMPDIR:-/tmp}"/codex-update-guard.*) rm -rf -- "$fixture" ;; *) exit 1 ;; esac
}
trap cleanup EXIT
mkdir -p "$fixture/bin" "$fixture/deploy" "$fixture/backups"
printf 'SYNTHETIC_ONLY=1\n' > "$fixture/deploy/.env.demo"
cat > "$fixture/bin/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FIXTURE_LOG"
case " $* " in
  *' ps --status running --services '*) [[ -z "${FIXTURE_WORKER:-}" ]] || printf '%s\n' "$FIXTURE_WORKER" ;;
  *' exec -T postgres '*) cat >/dev/null 2>&1 || true; printf 'synthetic-backup' ;;
  *' run --rm --no-deps db-migrate '*) exit 71 ;;
esac
SH
chmod +x "$fixture/bin/docker"
export PATH="$fixture/bin:$PATH" DEPLOY_DIR="$fixture/deploy" BACKUP_DIR="$fixture/backups" FIXTURE_LOG="$fixture/calls"
for script in deploy-hostinger-web-console.sh update-hostinger-web-console.sh; do
  for worker in whatsapp-inbox-worker dossier-import-worker dossier-outbox-worker agent-reply-worker; do
    : > "$FIXTURE_LOG"
    if FIXTURE_WORKER="$worker" bash "$root/$script" >/dev/null 2>&1; then
      echo "Unexpected success with active $worker ($script)" >&2; exit 1
    fi
    if grep -Eq ' (build|stop|up|run|exec) ' "$FIXTURE_LOG"; then
      echo "Mutation attempted before the active worker guard ($script)" >&2; exit 1
    fi
  done
done
: > "$FIXTURE_LOG"
if FIXTURE_WORKER='' bash "$root/update-hostinger-web-console.sh" >/dev/null 2>&1; then
  echo 'Injected migration failure unexpectedly succeeded' >&2; exit 1
fi
grep -q ' stop backend ingestion-worker learning-worker purge-worker$' "$FIXTURE_LOG"
grep -q ' run --rm --no-deps db-migrate$' "$FIXTURE_LOG"
if grep -q ' up -d ' "$FIXTURE_LOG"; then
  echo 'Services restarted after failed migration' >&2; exit 1
fi
echo 'Synthetic update guard and migration failure checks: OK'
