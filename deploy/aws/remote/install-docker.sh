#!/usr/bin/env bash
# Install Docker Engine and the Compose plugin on Ubuntu or Amazon Linux 2023.
set -euo pipefail
# shellcheck source=common.sh
. "$(cd "$(dirname "$0")" && pwd)/common.sh"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  log "Docker Engine and Compose already installed"
  docker --version
  docker compose version
  exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  die "install-docker.sh must run as root (sudo)"
fi

. /etc/os-release
log "Installing Docker on ${ID:-unknown} ${VERSION_ID:-}"

if [[ "${ID:-}" == "amzn" ]]; then
  dnf install -y docker python3 openssl rsync gettext tar gzip
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  systemctl enable --now docker
elif [[ "${ID:-}" == "ubuntu" || "${ID:-}" == "debian" ]]; then
  apt-get update -y
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/${ID}/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    python3 openssl rsync gettext-base tar gzip
  systemctl enable --now docker
else
  die "Unsupported OS ${ID:-unknown}. Install Docker Engine and the Compose plugin manually."
fi

DEPLOY_USER="${SUDO_USER:-${UNS_DEPLOY_USER:-ubuntu}}"
if id "${DEPLOY_USER}" >/dev/null 2>&1; then
  usermod -aG docker "${DEPLOY_USER}"
  log "Added ${DEPLOY_USER} to the docker group (new SSH session required for group to apply)"
fi

docker --version
docker compose version
log "Docker installation complete"
