#!/usr/bin/env bash
# The old test called the generic restore against a configured deployment,
# rather than proving that its target was an isolated disposable environment.
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf '%s\n' 'Legacy generic restore test is disabled; no data is changed.'
    printf '%s\n' 'See docs/securite/verification-sauvegarde-locale.md for isolated backup verification.'
    exit 0
fi

printf '%s\n' 'ERROR: Legacy generic restore test is disabled: target isolation was not guaranteed.' >&2
printf '%s\n' 'No data has been changed. See docs/securite/verification-sauvegarde-locale.md.' >&2
exit 1
