#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker() { printf '%s\n' 'FORBIDDEN_DOCKER_CALL' >&2; return 99; }
ssh() { printf '%s\n' 'FORBIDDEN_SSH_CALL' >&2; return 99; }
export -f docker ssh

for script in restore.sh test_restore.sh; do
    for args in '--date 2026-11-27' '--dry-run --date 2026-11-27' '--remote example.invalid'; do
        # Intentional word splitting exercises each legacy argument sequence.
        # shellcheck disable=SC2086
        if output=$(bash "$script_dir/$script" $args 2>&1); then
            printf 'Unexpected success: %s %s\n' "$script" "$args" >&2
            exit 1
        fi
        [[ "$output" == *'disabled'* && "$output" != *'FORBIDDEN_'* ]]
    done
    output=$(bash "$script_dir/$script" --help)
    [[ "$output" == *'disabled'* && "$output" != *'FORBIDDEN_'* ]]
done
printf '%s\n' 'Legacy restore entrypoints refuse execution: OK'
