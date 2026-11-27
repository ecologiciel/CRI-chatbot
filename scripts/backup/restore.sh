#!/usr/bin/env bash
# The old generic restore could report success after a failed PostgreSQL,
# Qdrant, MinIO or migration step. Keep it unavailable until a complete,
# isolated and failure-tested replacement exists.
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    printf '%s\n' 'Legacy generic restore is disabled; no data is changed.'
    printf '%s\n' 'See docs/securite/verification-sauvegarde-locale.md for isolated backup verification.'
    exit 0
fi

printf '%s\n' 'ERROR: Legacy generic restore is disabled: it cannot verify a complete restore safely.' >&2
printf '%s\n' 'No data has been changed. See docs/securite/verification-sauvegarde-locale.md.' >&2
exit 1
