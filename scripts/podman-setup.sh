#!/usr/bin/env bash
# Post-install Podman setup (Linux and macOS).
# Detects the rootless socket path and writes it to .env.compose.
# Source this script (do not execute it) so the exported vars take effect:
#   source scripts/podman-setup.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── 1. Default registry search order ─────────────────────────────────────────
REGISTRIES_CONF="${HOME}/.config/containers/registries.conf"
mkdir -p "$(dirname "$REGISTRIES_CONF")"
if ! grep -q 'docker.io' "$REGISTRIES_CONF" 2>/dev/null; then
    cat >> "$REGISTRIES_CONF" <<'EOF'

[registries.search]
registries = ["docker.io", "quay.io", "ghcr.io"]
EOF
    echo "==> Set default registries in ${REGISTRIES_CONF}"
fi

# ── 2. Detect Podman socket ───────────────────────────────────────────────────
if [[ "$(uname)" == "Darwin" ]]; then
    SOCK="$(podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}' 2>/dev/null || true)"
    if [[ -z "$SOCK" ]]; then
        echo "WARN: Could not detect Podman Machine socket. Is the machine running?"
        echo "      Run: podman machine start"
        SOCK="/var/folders/UNKNOWN/podman.sock"
    fi
else
    # Linux rootless
    RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
    SOCK="${RUNTIME_DIR}/podman/podman.sock"
fi

echo "==> Detected Podman socket: ${SOCK}"

# ── 3. Write (or update) .env.compose ────────────────────────────────────────
ENV_COMPOSE="${REPO_ROOT}/.env.compose"
if [[ ! -f "$ENV_COMPOSE" ]]; then
    cp "${REPO_ROOT}/.env.compose.example" "$ENV_COMPOSE"
    echo "==> Created ${ENV_COMPOSE} from example"
fi

# Replace PODMAN_SOCK line (or append if missing)
if grep -q '^PODMAN_SOCK=' "$ENV_COMPOSE"; then
    sed -i.bak "s|^PODMAN_SOCK=.*|PODMAN_SOCK=${SOCK}|" "$ENV_COMPOSE" && rm -f "${ENV_COMPOSE}.bak"
else
    echo "PODMAN_SOCK=${SOCK}" >> "$ENV_COMPOSE"
fi
echo "==> PODMAN_SOCK written to ${ENV_COMPOSE}"

# ── 4. Smoke test ─────────────────────────────────────────────────────────────
echo "==> Verifying Podman..."
podman info --format 'Podman {{.Version.Version}} on {{.Host.Os}}/{{.Host.Arch}}'
echo ""
echo "Setup complete. Start the dev stack with:"
echo "  podman compose -f compose.dev.yml up --build"
