#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — TLS Let's Encrypt Setup
# Configure TLS automatique via Traefik + ACME HTTP Challenge
# Execute uniquement sur VPS front et staging
#
# Usage :
#   ./init_ssl.sh --domain cri-platform.ma --email admin@cri-rsk.ma
#   ./init_ssl.sh                          # Reads from .env
#
# Exit codes:
#   0 = success
#   1 = pre-flight failure
#   2 = DNS verification failure
#   3 = certificate issuance failure
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEPLOY_DIR="/opt/cri-platform"
COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE="${DEPLOY_DIR}/.env"
DOMAIN=""
ACME_EMAIL_ARG=""
CERT_TIMEOUT=120  # seconds to wait for cert issuance

log() {
    echo "[init_ssl $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Configure TLS certificates via Traefik and Let's Encrypt.

Options:
  --domain DOMAIN   Base domain (e.g. cri-platform.ma)
  --email EMAIL     ACME email for Let's Encrypt
  --timeout SECS    Cert issuance timeout (default: 120)
  -h, --help        Show this help

If not provided, domain and email are read from ${ENV_FILE}.
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)   DOMAIN="$2"; shift 2 ;;
        --email)    ACME_EMAIL_ARG="$2"; shift 2 ;;
        --timeout)  CERT_TIMEOUT="$2"; shift 2 ;;
        -h|--help)  usage ;;
        *)          log "ERROR: Unknown option: $1"; usage ;;
    esac
done

# Load env if needed
if [[ -z "${DOMAIN}" ]] || [[ -z "${ACME_EMAIL_ARG}" ]]; then
    if [[ -f "${ENV_FILE}" ]]; then
        set -a
        source "${ENV_FILE}"
        set +a
        DOMAIN="${DOMAIN:-}"
        ACME_EMAIL_ARG="${ACME_EMAIL_ARG:-${ACME_EMAIL:-}}"
    fi
fi

if [[ -z "${DOMAIN}" ]]; then
    log "ERROR: --domain is required (or set DOMAIN in ${ENV_FILE})"
    exit 1
fi

if [[ -z "${ACME_EMAIL_ARG}" ]]; then
    log "ERROR: --email is required (or set ACME_EMAIL in ${ENV_FILE})"
    exit 1
fi

log "============================================"
log "TLS Certificate Setup"
log "  Domain: ${DOMAIN}"
log "  API: api.${DOMAIN}"
log "  Admin: admin.${DOMAIN}"
log "  ACME email: ${ACME_EMAIL_ARG}"
log "============================================"

# ==========================================================================
# Phase 1: DNS verification
# ==========================================================================
log "Phase 1: Verifying DNS records..."

# Get this server's public IP
MY_IP=$(curl -sf https://api.ipify.org 2>/dev/null || curl -sf https://ifconfig.me 2>/dev/null || echo "unknown")
log "  This server's public IP: ${MY_IP}"

dns_check() {
    local hostname="$1"
    local resolved
    resolved=$(dig +short "${hostname}" 2>/dev/null | head -1)

    if [[ -z "${resolved}" ]]; then
        log "  ERROR: ${hostname} does not resolve"
        return 1
    fi

    if [[ "${resolved}" != "${MY_IP}" ]]; then
        log "  WARNING: ${hostname} resolves to ${resolved} (expected ${MY_IP})"
        log "  Let's Encrypt HTTP challenge may fail if this is not correct"
        return 1
    fi

    log "  OK: ${hostname} → ${resolved}"
    return 0
}

dns_ok=true
dns_check "api.${DOMAIN}" || dns_ok=false
dns_check "admin.${DOMAIN}" || dns_ok=false

if [[ "${dns_ok}" == "false" ]]; then
    log ""
    log "DNS verification failed. Please ensure:"
    log "  1. api.${DOMAIN} → ${MY_IP} (A record)"
    log "  2. admin.${DOMAIN} → ${MY_IP} (A record)"
    log ""
    log "DNS propagation can take up to 48 hours."
    log "Once DNS is correct, re-run this script."
    exit 2
fi

# ==========================================================================
# Phase 2: Ensure Traefik certificate volume
# ==========================================================================
log "Phase 2: Ensuring certificate volume..."

if ! docker volume inspect traefik_certs >/dev/null 2>&1; then
    docker volume create traefik_certs
    log "  Created Docker volume: traefik_certs"
else
    log "  Volume traefik_certs already exists"
fi

# ==========================================================================
# Phase 3: Start Traefik
# ==========================================================================
log "Phase 3: Starting Traefik..."

cd "${DEPLOY_DIR}"

# Ensure ACME_EMAIL is set in env for docker compose
export ACME_EMAIL="${ACME_EMAIL_ARG}"

docker compose -f "${COMPOSE_FILE}" up -d traefik
log "  Traefik started"

# ==========================================================================
# Phase 4: Wait for certificate issuance
# ==========================================================================
log "Phase 4: Waiting for certificate issuance (timeout: ${CERT_TIMEOUT}s)..."

cert_acquired=false
elapsed=0
while [[ "${elapsed}" -lt "${CERT_TIMEOUT}" ]]; do
    # Check Traefik logs for certificate acquisition
    if docker compose -f "${COMPOSE_FILE}" logs traefik 2>&1 | grep -qi "certificate obtained"; then
        cert_acquired=true
        break
    fi

    # Also check if the ACME storage has content
    acme_size=$(docker exec cri-traefik stat -c '%s' /letsencrypt/acme.json 2>/dev/null || echo "0")
    if [[ "${acme_size}" -gt 100 ]]; then
        cert_acquired=true
        break
    fi

    sleep 5
    elapsed=$((elapsed + 5))
    log "  Waiting... (${elapsed}/${CERT_TIMEOUT}s)"
done

if [[ "${cert_acquired}" == "false" ]]; then
    log "WARNING: Certificate not confirmed within ${CERT_TIMEOUT}s"
    log "This may be normal — Let's Encrypt can take time."
    log "Check logs: docker compose -f ${COMPOSE_FILE} logs traefik"
fi

# ==========================================================================
# Phase 5: Verify TLS
# ==========================================================================
log "Phase 5: Verifying TLS certificates..."

# Give Traefik a moment to apply certs
sleep 5

verify_tls() {
    local hostname="$1"
    if curl -sf --max-time 10 "https://${hostname}" >/dev/null 2>&1; then
        log "  OK: https://${hostname} — TLS working"
        return 0
    fi

    # More detailed check
    local ssl_output
    ssl_output=$(curl -vI "https://${hostname}" 2>&1 || true)
    if echo "${ssl_output}" | grep -qi "SSL certificate verify ok"; then
        log "  OK: https://${hostname} — TLS certificate valid"
        return 0
    fi

    log "  WARNING: https://${hostname} — TLS not verified yet"
    return 1
}

tls_ok=true
verify_tls "api.${DOMAIN}" || tls_ok=false
verify_tls "admin.${DOMAIN}" || tls_ok=false

# ==========================================================================
# Summary
# ==========================================================================
log "============================================"
if [[ "${tls_ok}" == "true" ]]; then
    log "TLS SETUP COMPLETE"
    log "  https://api.${DOMAIN} — Backend API"
    log "  https://admin.${DOMAIN} — Back-Office"
else
    log "TLS SETUP PARTIALLY COMPLETE"
    log "  Certificates may still be issuing."
    log "  Check: docker compose -f ${COMPOSE_FILE} logs traefik"
    log "  Re-verify: curl -vI https://api.${DOMAIN}"
fi
log "============================================"
