#!/usr/bin/env bash
# =============================================================================
# CRI Chatbot Platform — VPS Initial Setup (Nindohost Ubuntu 22.04/24.04)
#
# Usage :
#   ssh root@<vps-ip> 'bash -s' < init_vps.sh --role api
#   ./init_vps.sh --role api --ssh-allow-from 196.200.0.0/16
#
# Roles :
#   api     — VPS 1 : Backend API, Orchestrateur, Qdrant (no public ports)
#   data    — VPS 2 : PostgreSQL, Redis, MinIO (no public ports)
#   front   — VPS 3 : Frontend, Traefik, Monitoring (ports 80/443)
#   staging — VPS Pre-Prod : all services (ports 80/443)
#
# Exit codes:
#   0 = success
#   1 = pre-flight failure
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROLE=""
HOSTNAME_OVERRIDE=""
SSH_ALLOW_FROM="${SSH_ALLOW_FROM:-}"
SSH_KEYS_FILE=""
SKIP_SWAP=false
PRIVATE_NETWORK="${PRIVATE_NETWORK:-10.0.0.0/24}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() {
    echo "[init_vps $(date '+%Y-%m-%d %H:%M:%S')] $*"
}

usage() {
    cat <<EOF
Usage: $(basename "$0") --role ROLE [OPTIONS]

Provision a Nindohost VPS for the CRI Chatbot Platform.

Required:
  --role ROLE           VPS role: api | data | front | staging

Options:
  --hostname NAME       Custom hostname (default: cri-ROLE)
  --ssh-allow-from CIDR CIDR range for SSH whitelist (e.g. 196.200.0.0/16)
  --ssh-keys FILE       Path to authorized_keys file for deploy/backup users
  --private-net CIDR    Private network CIDR (default: 10.0.0.0/24)
  --skip-swap           Do not create swap file
  -h, --help            Show this help
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --role)           ROLE="$2"; shift 2 ;;
        --hostname)       HOSTNAME_OVERRIDE="$2"; shift 2 ;;
        --ssh-allow-from) SSH_ALLOW_FROM="$2"; shift 2 ;;
        --ssh-keys)       SSH_KEYS_FILE="$2"; shift 2 ;;
        --private-net)    PRIVATE_NETWORK="$2"; shift 2 ;;
        --skip-swap)      SKIP_SWAP=true; shift ;;
        -h|--help)        usage ;;
        *)                log "ERROR: Unknown option: $1"; usage ;;
    esac
done

# Validate role
case "${ROLE}" in
    api|data|front|staging) ;;
    *) log "ERROR: --role is required (api|data|front|staging)"; usage ;;
esac

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    log "ERROR: This script must be run as root"
    exit 1
fi

# Detect OS
if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    if [[ "${ID}" != "ubuntu" ]]; then
        log "WARNING: Expected Ubuntu, detected ${ID}. Proceeding anyway..."
    fi
    log "OS: ${PRETTY_NAME}"
else
    log "WARNING: Cannot detect OS version"
fi

VPS_HOSTNAME="${HOSTNAME_OVERRIDE:-cri-${ROLE}}"

log "============================================"
log "CRI Platform VPS Provisioning"
log "  Role: ${ROLE}"
log "  Hostname: ${VPS_HOSTNAME}"
log "============================================"

# ==========================================================================
# Phase 1: System update
# ==========================================================================
log "Phase 1: System update..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    curl wget gnupg2 unzip jq htop vim \
    logrotate fail2ban ufw \
    ca-certificates lsb-release \
    apt-transport-https software-properties-common

# ==========================================================================
# Phase 2: Set hostname
# ==========================================================================
log "Phase 2: Setting hostname to ${VPS_HOSTNAME}..."
hostnamectl set-hostname "${VPS_HOSTNAME}"

# ==========================================================================
# Phase 3: Create users
# ==========================================================================
log "Phase 3: Creating users..."

create_user() {
    local username="$1"
    if id "${username}" &>/dev/null; then
        log "  User '${username}' already exists"
    else
        useradd -m -s /bin/bash "${username}"
        log "  Created user: ${username}"
    fi

    # SSH setup
    local ssh_dir="/home/${username}/.ssh"
    mkdir -p "${ssh_dir}"

    if [[ -n "${SSH_KEYS_FILE}" ]] && [[ -f "${SSH_KEYS_FILE}" ]]; then
        cp "${SSH_KEYS_FILE}" "${ssh_dir}/authorized_keys"
    elif [[ -f /root/.ssh/authorized_keys ]]; then
        cp /root/.ssh/authorized_keys "${ssh_dir}/authorized_keys"
    fi

    chown -R "${username}:${username}" "${ssh_dir}"
    chmod 700 "${ssh_dir}"
    chmod 600 "${ssh_dir}/authorized_keys" 2>/dev/null || true
}

# Deploy user (deployments, docker operations)
create_user "deploy"

# Backup user (backup operations only)
create_user "backup"

# ==========================================================================
# Phase 4: SSH hardening
# ==========================================================================
log "Phase 4: Hardening SSH..."

SSHD_CONFIG="/etc/ssh/sshd_config"

# Backup original config
cp "${SSHD_CONFIG}" "${SSHD_CONFIG}.bak.$(date +%Y%m%d)"

# Apply hardening settings
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "${SSHD_CONFIG}"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "${SSHD_CONFIG}"
sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication no/' "${SSHD_CONFIG}"
sed -i 's/^PubkeyAuthentication no/PubkeyAuthentication yes/' "${SSHD_CONFIG}"
sed -i 's/^#\?MaxAuthTries.*/MaxAuthTries 3/' "${SSHD_CONFIG}"
sed -i 's/^#\?LoginGraceTime.*/LoginGraceTime 30/' "${SSHD_CONFIG}"
sed -i 's/^#\?X11Forwarding.*/X11Forwarding no/' "${SSHD_CONFIG}"

# AllowUsers (remove existing, add new)
sed -i '/^AllowUsers/d' "${SSHD_CONFIG}"
echo "AllowUsers deploy backup" >> "${SSHD_CONFIG}"

# Validate and restart
sshd -t && systemctl restart sshd
log "  SSH hardened: root login disabled, password auth disabled, AllowUsers deploy backup"

# ==========================================================================
# Phase 5: Firewall (UFW)
# ==========================================================================
log "Phase 5: Configuring firewall (UFW)..."

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# SSH: whitelist only
if [[ -n "${SSH_ALLOW_FROM}" ]]; then
    ufw allow from "${SSH_ALLOW_FROM}" to any port 22 proto tcp comment "SSH admin whitelist"
    log "  SSH allowed from: ${SSH_ALLOW_FROM}"
else
    ufw allow 22/tcp comment "SSH (restrict to whitelist in production)"
    log "  WARNING: SSH open to all — set --ssh-allow-from in production"
fi

# Role-specific public ports
case "${ROLE}" in
    front|staging)
        ufw allow 80/tcp comment "HTTP (Traefik)"
        ufw allow 443/tcp comment "HTTPS (Traefik)"
        log "  Ports 80/443 opened (role: ${ROLE})"
        ;;
    api|data)
        log "  No public ports (role: ${ROLE})"
        ;;
esac

# Private network (inter-VPS communication)
ufw allow from "${PRIVATE_NETWORK}" comment "Private network inter-VPS"
log "  Private network allowed: ${PRIVATE_NETWORK}"

ufw --force enable
log "  UFW enabled"

# ==========================================================================
# Phase 6: fail2ban
# ==========================================================================
log "Phase 6: Configuring fail2ban..."

cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
findtime = 600
EOF

systemctl enable fail2ban
systemctl restart fail2ban
log "  fail2ban configured: SSH jail, maxretry=3, bantime=1h"

# ==========================================================================
# Phase 7: Docker + Docker Compose V2
# ==========================================================================
log "Phase 7: Installing Docker..."

if command -v docker &>/dev/null; then
    log "  Docker already installed: $(docker --version)"
else
    # Official Docker APT repository
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

    systemctl enable docker
    systemctl start docker
    log "  Docker installed: $(docker --version)"
fi

# Add users to docker group
usermod -aG docker deploy
usermod -aG docker backup
log "  Users deploy and backup added to docker group"

# Docker daemon config (logging, live restore)
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "50m",
        "max-file": "5"
    },
    "live-restore": true,
    "default-address-pools": [
        {"base": "172.17.0.0/12", "size": 24}
    ]
}
EOF
systemctl restart docker

# ==========================================================================
# Phase 8: Directory structure
# ==========================================================================
log "Phase 8: Creating directory structure..."

# Application root (owned by deploy)
mkdir -p /opt/cri-platform
chown deploy:deploy /opt/cri-platform
chmod 750 /opt/cri-platform

# Backup directories (owned by backup)
mkdir -p /var/backups/cri/{postgres,qdrant,minio/archives}
chown -R backup:backup /var/backups/cri
chmod -R 750 /var/backups/cri

# Backup logs (owned by backup)
mkdir -p /var/log/cri-backup/restore-tests
chown -R backup:backup /var/log/cri-backup
chmod -R 750 /var/log/cri-backup

log "  /opt/cri-platform (deploy), /var/backups/cri (backup), /var/log/cri-backup (backup)"

# ==========================================================================
# Phase 9: Logrotate for backup logs
# ==========================================================================
log "Phase 9: Configuring logrotate..."

cat > /etc/logrotate.d/cri-backup <<'EOF'
/var/log/cri-backup/*.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 640 backup backup
}
EOF

cat > /etc/logrotate.d/docker-containers <<'EOF'
/var/lib/docker/containers/*/*.log {
    rotate 10
    daily
    compress
    missingok
    delaycompress
    copytruncate
    maxsize 50M
}
EOF

log "  Logrotate configured for cri-backup and Docker containers"

# ==========================================================================
# Phase 10: Swap (unless --skip-swap)
# ==========================================================================
if [[ "${SKIP_SWAP}" == "false" ]]; then
    log "Phase 10: Configuring swap..."

    # Check total RAM
    total_ram_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)

    if [[ ! -f /swapfile ]]; then
        # 4GB swap for all VPS sizes
        fallocate -l 4G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile

        # Persist across reboots
        if ! grep -q '/swapfile' /etc/fstab; then
            echo '/swapfile none swap sw 0 0' >> /etc/fstab
        fi

        # Reduce swappiness (prefer RAM)
        sysctl vm.swappiness=10
        echo 'vm.swappiness=10' >> /etc/sysctl.d/99-cri.conf

        log "  4GB swap created (RAM: ${total_ram_gb}GB, swappiness: 10)"
    else
        log "  Swap already exists"
    fi
else
    log "Phase 10: Swap skipped (--skip-swap)"
fi

# ==========================================================================
# Phase 11: Timezone
# ==========================================================================
log "Phase 11: Setting timezone..."
timedatectl set-timezone Africa/Casablanca
log "  Timezone: Africa/Casablanca"

# ==========================================================================
# Phase 12: Role-specific tuning
# ==========================================================================
log "Phase 12: Role-specific configuration (${ROLE})..."

case "${ROLE}" in
    api)
        # Qdrant requires higher vm.max_map_count
        sysctl -w vm.max_map_count=262144
        echo 'vm.max_map_count=262144' >> /etc/sysctl.d/99-cri.conf
        # Network tuning for API server
        sysctl -w net.core.somaxconn=1024
        echo 'net.core.somaxconn=1024' >> /etc/sysctl.d/99-cri.conf
        log "  API tuning: vm.max_map_count=262144, somaxconn=1024"
        ;;
    data)
        # PostgreSQL shared memory
        sysctl -w kernel.shmmax=8589934592    # 8GB
        sysctl -w kernel.shmall=2097152       # 8GB / 4KB pages
        echo 'kernel.shmmax=8589934592' >> /etc/sysctl.d/99-cri.conf
        echo 'kernel.shmall=2097152' >> /etc/sysctl.d/99-cri.conf
        # Overcommit: PostgreSQL prefers mode 2
        sysctl -w vm.overcommit_memory=2
        sysctl -w vm.overcommit_ratio=80
        echo 'vm.overcommit_memory=2' >> /etc/sysctl.d/99-cri.conf
        echo 'vm.overcommit_ratio=80' >> /etc/sysctl.d/99-cri.conf
        log "  Data tuning: PostgreSQL shmmax=8GB, overcommit_memory=2"
        ;;
    front)
        log "  Front role: minimal tuning (monitoring prep only)"
        ;;
    staging)
        # Staging needs all tuning
        sysctl -w vm.max_map_count=262144
        sysctl -w net.core.somaxconn=1024
        echo 'vm.max_map_count=262144' >> /etc/sysctl.d/99-cri.conf
        echo 'net.core.somaxconn=1024' >> /etc/sysctl.d/99-cri.conf
        log "  Staging tuning: combined api+data settings"
        ;;
esac

# Reload sysctl
sysctl -p /etc/sysctl.d/99-cri.conf 2>/dev/null || true

# ==========================================================================
# Phase 13: Install backup crontab (data and staging roles only)
# ==========================================================================
if [[ "${ROLE}" == "data" || "${ROLE}" == "staging" ]]; then
    log "Phase 13: Installing backup crontab..."
    crontab_src="/opt/cri-platform/scripts/backup/crontab.template"
    if [[ -f "${crontab_src}" ]]; then
        cp "${crontab_src}" /etc/cron.d/cri-backup
        chmod 644 /etc/cron.d/cri-backup
        log "  Crontab installed: /etc/cron.d/cri-backup"
    else
        log "  WARNING: Crontab template not found at ${crontab_src}"
        log "  Install manually after deployment: cp scripts/backup/crontab.template /etc/cron.d/cri-backup"
    fi
else
    log "Phase 13: Crontab skipped (role: ${ROLE})"
fi

# ==========================================================================
# Summary
# ==========================================================================
log "============================================"
log "VPS PROVISIONING COMPLETE"
log "  Hostname: ${VPS_HOSTNAME}"
log "  Role: ${ROLE}"
log "  Users: deploy, backup (docker group)"
log "  SSH: root disabled, password disabled"
log "  Firewall: UFW active"
log "  fail2ban: SSH jail active"
log "  Docker: $(docker --version 2>/dev/null | head -1)"
log "  Compose: $(docker compose version 2>/dev/null | head -1)"
log "  Timezone: Africa/Casablanca"
log "  Swap: $(swapon --show --noheadings 2>/dev/null | awk '{print $3}' || echo 'none')"
log ""
log "  Next steps:"
log "    1. Copy SSH keys for deploy/backup users"
log "    2. Deploy application: scp docker-compose.prod.yml deploy@${VPS_HOSTNAME}:/opt/cri-platform/"
log "    3. Create .env: scp .env deploy@${VPS_HOSTNAME}:/opt/cri-platform/.env"
log "    4. Run init_ssl.sh (front/staging only)"
log "    5. Run init_monitoring.sh"
log "============================================"
