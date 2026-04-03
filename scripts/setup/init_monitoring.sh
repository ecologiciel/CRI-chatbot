#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — Node Exporter Deployment
# Deploie node_exporter comme service systemd pour metriques hardware Prometheus
# Execute sur chaque VPS
#
# Usage :
#   ./init_monitoring.sh
#   ./init_monitoring.sh --version 1.8.2
#   ./init_monitoring.sh --prometheus-host 10.0.0.3
#
# Exit codes:
#   0 = success
#   1 = pre-flight failure
#   2 = installation failure
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NODE_EXPORTER_VERSION="${1:-1.8.2}"
PROMETHEUS_HOST=""
PRIVATE_NETWORK="${PRIVATE_NETWORK:-10.0.0.0/24}"
NODE_EXPORTER_PORT=9100

log() {
    echo "[init_monitoring $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Deploy node_exporter as a systemd service for Prometheus hardware metrics.

Options:
  --version VERSION     node_exporter version (default: 1.8.2)
  --prometheus-host IP  Prometheus host IP (for UFW rule)
  --private-net CIDR    Private network CIDR (default: 10.0.0.0/24)
  -h, --help            Show this help
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)         NODE_EXPORTER_VERSION="$2"; shift 2 ;;
        --prometheus-host) PROMETHEUS_HOST="$2"; shift 2 ;;
        --private-net)     PRIVATE_NETWORK="$2"; shift 2 ;;
        -h|--help)         usage ;;
        *)                 log "ERROR: Unknown option: $1"; usage ;;
    esac
done

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    log "ERROR: This script must be run as root"
    exit 1
fi

log "============================================"
log "Node Exporter Deployment"
log "  Version: ${NODE_EXPORTER_VERSION}"
log "  Port: ${NODE_EXPORTER_PORT}"
log "============================================"

# ==========================================================================
# Phase 1: Download and install node_exporter
# ==========================================================================
log "Phase 1: Installing node_exporter v${NODE_EXPORTER_VERSION}..."

ARCH=$(uname -m)
case "${ARCH}" in
    x86_64)  ARCH_NAME="amd64" ;;
    aarch64) ARCH_NAME="arm64" ;;
    *)       log "ERROR: Unsupported architecture: ${ARCH}"; exit 2 ;;
esac

TARBALL="node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH_NAME}.tar.gz"
DOWNLOAD_URL="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/${TARBALL}"

if [[ -f /usr/local/bin/node_exporter ]]; then
    existing_version=$(/usr/local/bin/node_exporter --version 2>&1 | head -1 | awk '{print $3}' || echo "unknown")
    log "  node_exporter already installed: v${existing_version}"
    if [[ "${existing_version}" == "${NODE_EXPORTER_VERSION}" ]]; then
        log "  Already at requested version, skipping download"
    else
        log "  Upgrading from v${existing_version} to v${NODE_EXPORTER_VERSION}"
        systemctl stop node_exporter 2>/dev/null || true
    fi
fi

if [[ ! -f /usr/local/bin/node_exporter ]] || [[ "${existing_version:-}" != "${NODE_EXPORTER_VERSION}" ]]; then
    cd /tmp
    curl -fsSL -o "${TARBALL}" "${DOWNLOAD_URL}"
    tar -xzf "${TARBALL}"
    cp "node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH_NAME}/node_exporter" /usr/local/bin/
    chmod 755 /usr/local/bin/node_exporter
    rm -rf "${TARBALL}" "node_exporter-${NODE_EXPORTER_VERSION}.linux-${ARCH_NAME}"
    log "  Installed: /usr/local/bin/node_exporter"
fi

# ==========================================================================
# Phase 2: Create system user
# ==========================================================================
log "Phase 2: Creating node_exporter user..."

if id node_exporter &>/dev/null; then
    log "  User node_exporter already exists"
else
    useradd --system --no-create-home --shell /usr/sbin/nologin node_exporter
    log "  Created system user: node_exporter"
fi

# ==========================================================================
# Phase 3: Systemd service
# ==========================================================================
log "Phase 3: Creating systemd service..."

cat > /etc/systemd/system/node_exporter.service <<EOF
[Unit]
Description=Prometheus Node Exporter
Documentation=https://prometheus.io/docs/guides/node-exporter/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=node_exporter
Group=node_exporter
ExecStart=/usr/local/bin/node_exporter \\
    --web.listen-address=:${NODE_EXPORTER_PORT} \\
    --collector.systemd \\
    --collector.processes
Restart=always
RestartSec=5
SyslogIdentifier=node_exporter

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=/

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable node_exporter
systemctl restart node_exporter

# Verify service is running
sleep 2
if systemctl is-active --quiet node_exporter; then
    log "  Service started and enabled"
else
    log "  ERROR: Service failed to start"
    systemctl status node_exporter --no-pager || true
    exit 2
fi

# ==========================================================================
# Phase 4: UFW rule
# ==========================================================================
log "Phase 4: Configuring firewall rule..."

if [[ -n "${PROMETHEUS_HOST}" ]]; then
    ufw allow from "${PROMETHEUS_HOST}" to any port "${NODE_EXPORTER_PORT}" proto tcp \
        comment "node_exporter (Prometheus)" 2>/dev/null || true
    log "  UFW: port ${NODE_EXPORTER_PORT} allowed from ${PROMETHEUS_HOST}"
else
    # Allow from private network
    ufw allow from "${PRIVATE_NETWORK}" to any port "${NODE_EXPORTER_PORT}" proto tcp \
        comment "node_exporter (Prometheus)" 2>/dev/null || true
    log "  UFW: port ${NODE_EXPORTER_PORT} allowed from ${PRIVATE_NETWORK}"
fi

# ==========================================================================
# Phase 5: Verify
# ==========================================================================
log "Phase 5: Verifying installation..."

# Check metrics endpoint
if curl -sf "http://localhost:${NODE_EXPORTER_PORT}/metrics" >/dev/null 2>&1; then
    log "  Metrics endpoint: http://localhost:${NODE_EXPORTER_PORT}/metrics — OK"
else
    log "  WARNING: Metrics endpoint not responding"
fi

# Show a sample metric
sample=$(curl -sf "http://localhost:${NODE_EXPORTER_PORT}/metrics" 2>/dev/null | \
    grep "^node_cpu_seconds_total" | head -1 || echo "unavailable")
log "  Sample metric: ${sample}"

# ==========================================================================
# Summary
# ==========================================================================
log "============================================"
log "NODE EXPORTER DEPLOYMENT COMPLETE"
log "  Version: ${NODE_EXPORTER_VERSION}"
log "  Endpoint: http://$(hostname -I | awk '{print $1}'):${NODE_EXPORTER_PORT}/metrics"
log ""
log "  Next step: Add this target to Prometheus config"
log "  Edit docker/prometheus/prometheus.yml on VPS 3:"
log ""
log "    - job_name: 'node_$(hostname)'"
log "      static_configs:"
log "        - targets: ['$(hostname -I | awk '{print $1}'):${NODE_EXPORTER_PORT}']"
log "          labels:"
log "            role: '$(hostname | sed 's/cri-//')'"
log ""
log "  Then reload Prometheus:"
log "    docker exec cri-prometheus kill -HUP 1"
log "============================================"
