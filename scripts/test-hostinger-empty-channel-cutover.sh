#!/usr/bin/env bash
# Synthetic CLI tests. Never run against production paths or containers.
set -Eeuo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fixture=$(mktemp -d "${TMPDIR:-/tmp}/codex-channel-cutover-test.XXXXXXXX")
cleanup() { case "$fixture" in "${TMPDIR:-/tmp}"/codex-channel-cutover-test.*) rm -rf -- "$fixture" ;; *) exit 1 ;; esac; }
trap cleanup EXIT
mkdir -p "$fixture/bin" "$fixture/deploy/scripts/backup" "$fixture/backups"
printf '#!/bin/sh\nexit 0\n' > "$fixture/deploy/scripts/backup/check-hostinger-backup.sh"
cat > "$fixture/bin/git" <<'SH'
#!/usr/bin/env bash
[[ "$1" == rev-parse ]] && printf '%s\n' synthetic-head
exit 0
SH
cat > "$fixture/bin/docker" <<'SH'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FIXTURE_LOG"
a="sha256:$(printf 'a%.0s' {1..64})"
b="sha256:$(printf 'b%.0s' {1..64})"
c="sha256:$(printf 'c%.0s' {1..64})"
d="sha256:$(printf 'd%.0s' {1..64})"
case " $* " in
  *' image inspect '*candidate-backend*) echo "$a" ;;
  *' image inspect '*candidate-admin*) echo "$b" ;;
  *' inspect -f {{.Image}} '*frontend-admin*) if [[ -f "$FIXTURE_STARTED" ]]; then echo "$b"; else echo "$d"; fi ;;
  *' inspect -f {{.Image}} '*) if [[ -f "$FIXTURE_STARTED" ]]; then echo "$a"; else echo "$c"; fi ;;
  *' inspect -f {{.State.Running}} '*) echo true ;;
  *' ps --status running --services '*) printf '%s\n' backend ingestion-worker learning-worker purge-worker frontend-admin ;;
  *' ps -q '*) printf '%s\n' "${*: -1}" ;;
  *' config --images frontend-admin '*) echo 'fixture/admin:main' ;;
  *' config --images backend '*) echo 'fixture/backend:main' ;;
  *' exec -T postgres '*)
    if [[ -f "$FIXTURE_STARTED" ]]; then echo "${FIXTURE_AFTER_COUNT:-0}"; else echo "${FIXTURE_BEFORE_COUNT:-0}"; fi ;;
  *' exec -T backend python -m app.scripts.healthcheck '*) [[ "${FIXTURE_FAIL_HEALTH:-0}" != 1 ]] ;;
  *rollback.yml*' up -d '*) echo rollback >> "$FIXTURE_ACTIONS" ;;
  *' up -d '*) touch "$FIXTURE_STARTED" ;;
esac
SH
chmod +x "$fixture/bin/git" "$fixture/bin/docker"
export PATH="$fixture/bin:$PATH" DEPLOY_DIR="$fixture/deploy" BACKUP_DIR="$fixture/backups"
export FIXTURE_LOG="$fixture/log" FIXTURE_ACTIONS="$fixture/actions" FIXTURE_STARTED="$fixture/started"
export EXPECTED_HEAD=synthetic-head CANDIDATE_BACKEND=candidate-backend CANDIDATE_ADMIN=candidate-admin
run_case() {
  rm -f "$FIXTURE_STARTED" "$FIXTURE_LOG" "$FIXTURE_ACTIONS"
  printf 'SYNTHETIC_ONLY=1\n' > "$DEPLOY_DIR/.env.demo"
  env "$@" bash "$root/cutover-hostinger-empty-channels.sh" > "$fixture/output" 2>&1
}
run_case
grep -q '^WHATSAPP_CONFIG_REQUIRE_ENCRYPTION=true$' "$DEPLOY_DIR/.env.demo"
grep -q 'cutover complete' "$fixture/output"
if run_case FIXTURE_FAIL_HEALTH=1; then echo 'Expected failed health check' >&2; exit 1; fi
! grep -q '^WHATSAPP_CONFIG_REQUIRE_ENCRYPTION=' "$DEPLOY_DIR/.env.demo"
grep -q rollback "$FIXTURE_ACTIONS"
if run_case FIXTURE_BEFORE_COUNT=1; then echo 'Expected existing channel refusal' >&2; exit 1; fi
! grep -q '^WHATSAPP_CONFIG_REQUIRE_ENCRYPTION=' "$DEPLOY_DIR/.env.demo"
grep -q rollback "$FIXTURE_ACTIONS"
if run_case FIXTURE_FAIL_HEALTH=1 FIXTURE_AFTER_COUNT=1; then echo 'Expected rollback refusal' >&2; exit 1; fi
grep -q '^WHATSAPP_CONFIG_REQUIRE_ENCRYPTION=true$' "$DEPLOY_DIR/.env.demo"
[[ ! -f "$FIXTURE_ACTIONS" ]] || { echo 'Unsafe rollback occurred' >&2; exit 1; }
grep -q 'Rollback refused' "$fixture/output"
echo CUTOVER_SYNTHETIC_CASES_OK
