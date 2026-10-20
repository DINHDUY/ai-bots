#!/usr/bin/env bash
# Install Podman + podman-compose on macOS via Homebrew.
# Podman Machine provides a lightweight WSL-style Linux VM backed by QEMU.
set -euo pipefail

if ! command -v brew &>/dev/null; then
    echo "ERROR: Homebrew is required."
    echo "Install from https://brew.sh then re-run this script."
    exit 1
fi

echo "==> Installing Podman via Homebrew..."
brew install podman

echo "==> Installing podman-compose..."
pip3 install --user podman-compose || brew install podman-compose

echo "==> Initialising Podman Machine (QEMU, 2 CPUs, 4 GB RAM, 40 GB disk)..."
if podman machine list 2>/dev/null | grep -q 'podman-machine-default'; then
    echo "    Machine already exists, skipping init."
else
    podman machine init --cpus 2 --memory 4096 --disk-size 40
fi

echo "==> Starting Podman Machine..."
podman machine start 2>/dev/null || echo "    Machine may already be running."

echo ""
echo "Podman $(podman --version) installed and machine is running."
echo "Next: run  source scripts/podman-setup.sh  to configure registries and detect socket path."
