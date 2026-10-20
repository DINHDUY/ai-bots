#!/usr/bin/env bash
# Install Podman + podman-compose on Linux.
# Supports Debian/Ubuntu (apt), Fedora/RHEL/CentOS (dnf), and openSUSE (zypper).
set -euo pipefail

echo "==> Detecting package manager..."

if command -v apt-get &>/dev/null; then
    echo "==> Installing via apt..."
    sudo apt-get update -qq
    sudo apt-get install -y podman

    # podman-compose from pip (distro package may be outdated)
    if ! command -v pip3 &>/dev/null; then
        sudo apt-get install -y python3-pip
    fi
    pip3 install --user podman-compose

elif command -v dnf &>/dev/null; then
    echo "==> Installing via dnf..."
    sudo dnf install -y podman podman-compose

elif command -v zypper &>/dev/null; then
    echo "==> Installing via zypper..."
    sudo zypper install -y podman
    pip3 install --user podman-compose

else
    echo "ERROR: No supported package manager found (apt/dnf/zypper)."
    echo "Install Podman manually: https://podman.io/getting-started/installation"
    exit 1
fi

# Enable rootless Podman socket for the current user
echo "==> Enabling rootless Podman socket..."
systemctl --user enable --now podman.socket 2>/dev/null || \
    echo "WARN: Could not enable systemd user socket (headless server?). Start manually: podman system service --time=0"

echo ""
echo "Podman $(podman --version) installed."
echo "Next: run  source scripts/podman-setup.sh  to configure registries and detect socket path."
