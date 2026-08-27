#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Install native Docker Engine + Compose plugin inside Ubuntu 22.04 WSL.

set -euo pipefail

if [[ ! -r /etc/os-release ]]; then
  echo "[ERROR] /etc/os-release is missing" >&2
  exit 1
fi
. /etc/os-release
if [[ "${ID}" != "ubuntu" || "${VERSION_CODENAME}" != "jammy" ]]; then
  echo "[ERROR] this audited installer supports Ubuntu 22.04 (jammy), found ${ID} ${VERSION_CODENAME}" >&2
  exit 1
fi
if [[ "$(ps -p 1 -o comm=)" != "systemd" ]]; then
  echo "[ERROR] WSL systemd is not active" >&2
  exit 1
fi

echo "[INFO] sudo is required only for apt, systemd and docker-group setup."
sudo -v
sudo apt-get -o Acquire::ForceIPv4=true update
sudo apt-get -o Acquire::ForceIPv4=true install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl --fail --show-error --silent --location \
  --ipv4 --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 20 \
  https://download.docker.com/linux/ubuntu/gpg -o /tmp/docker.asc
sudo install -m 0644 /tmp/docker.asc /etc/apt/keyrings/docker.asc

ARCH="$(dpkg --print-architecture)"
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get -o Acquire::ForceIPv4=true update
sudo apt-get -o Acquire::ForceIPv4=true install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo groupadd --force docker
sudo usermod -aG docker "${USER}"

echo "[INFO] validating Docker through a fresh docker-group shell"
sg docker -c 'docker version && docker compose version && docker run --rm hello-world'

echo
echo "[PASS] Docker Engine and Compose are installed inside WSL."
echo "[NEXT] Close this terminal, run 'wsl.exe --shutdown' once from PowerShell, then reopen WSL."
