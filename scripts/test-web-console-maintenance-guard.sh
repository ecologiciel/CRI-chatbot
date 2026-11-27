#!/usr/bin/env bash
# Test updater decisions against a fake Docker CLI and synthetic local paths.
set -Eeuo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d "${TMPDIR:-/tmp}/codex-update-guard.XXXXXXXX")
holder=''
cleanup() {
  if [[ -n "$holder" ]]; then kill "$holder" 2>/dev/null || true; wait "$holder" 2>/dev/null || true; fi
  case "$fixture" in "${TMPDIR:-/tmp}"/codex-update-guard.*) rm -rf -- "$fixture" ;; *) exit 1 ;; esac
}
trap cleanup EXIT
mkdir -p "$fixture/bin" "$fixture/deploy" "$fixture/backups"
printf 'SYNTHETIC_ONLY=1\n' > "$fixture/deploy/.env.demo"
cat > "$fixture/bin/docker" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FIXTURE_LOG"
case " $* " in
  *' ps --status running --services '*)
    if [[ -n "${FIXTURE_WORKER:-}" ]]; then printf '%s\n' "$FIXTURE_WORKER"
    elif [[ -f "$FIXTURE_BUILT_MARKER" && -n "${FIXTURE_WORKER_AFTER_BUILD:-}" ]]; then printf '%s\n' "$FIXTURE_WORKER_AFTER_BUILD"; fi ;;
  *' build '*) touch "$FIXTURE_BUILT_MARKER" ;;
  *' exec -T postgres '*) cat >/dev/null 2>&1 || true; printf 'synthetic-backup' ;;
  *' run --rm --no-deps db-migrate '*) exit 71 ;;
esac
SH
chmod +x "$fixture/bin/docker"
real_flock=0
if command -v flock >/dev/null; then
  real_flock=1
else
  [[ "${REQUIRE_REAL_FLOCK:-0}" != 1 ]] || { echo 'Real flock required' >&2; exit 1; }
  printf '#!/usr/bin/env bash\nexit 0\n' > "$fixture/bin/flock"
  chmod +x "$fixture/bin/flock"
fi
export PATH="$fixture/bin:$PATH" DEPLOY_DIR="$fixture/deploy" BACKUP_DIR="$fixture/backups" FIXTURE_LOG="$fixture/calls" FIXTURE_BUILT_MARKER="$fixture/built"
if (( real_flock )); then
  mkfifo "$fixture/release"
  (flock -x 9; touch "$fixture/held"; read -r _ < "$fixture/release") 9>"$DEPLOY_DIR/.kms-rotation.lock" &
  holder=$!
  for _ in {1..100}; do [[ -f "$fixture/held" ]] && break; sleep 0.05; done
  [[ -f "$fixture/held" ]] || { echo 'Could not hold the fixture lock' >&2; exit 1; }
  for script in deploy-hostinger-web-console.sh update-hostinger-web-console.sh; do
    : > "$FIXTURE_LOG"
    if bash "$root/$script" >/dev/null 2>&1; then echo "Lock ignored ($script)" >&2; exit 1; fi
    [[ ! -s "$FIXTURE_LOG" ]] || { echo "Docker invoked while lock held ($script)" >&2; exit 1; }
  done
  kill "$holder" 2>/dev/null || true
  wait "$holder" 2>/dev/null || true
  holder=''
fi
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
for script in deploy-hostinger-web-console.sh update-hostinger-web-console.sh; do
  : > "$FIXTURE_LOG"
  rm -f "$FIXTURE_BUILT_MARKER"
  if FIXTURE_WORKER_AFTER_BUILD=agent-reply-worker bash "$root/$script" >/dev/null 2>&1; then
    echo "Active worker after build was not detected ($script)" >&2; exit 1
  fi
  grep -q ' build ' "$FIXTURE_LOG"
  if grep -Eq ' (stop|up|run) ' "$FIXTURE_LOG"; then
    echo "Mutation attempted after the second worker guard ($script)" >&2; exit 1
  fi
done
: > "$FIXTURE_LOG"
rm -f "$FIXTURE_BUILT_MARKER"
if FIXTURE_WORKER='' bash "$root/update-hostinger-web-console.sh" >/dev/null 2>&1; then
  echo 'Injected migration failure unexpectedly succeeded' >&2; exit 1
fi
grep -q ' stop backend ingestion-worker learning-worker purge-worker$' "$FIXTURE_LOG"
grep -q ' run --rm --no-deps db-migrate$' "$FIXTURE_LOG"
if grep -q ' up -d ' "$FIXTURE_LOG"; then
  echo 'Services restarted after failed migration' >&2; exit 1
fi
echo 'Synthetic update guard and migration failure checks: OK'
