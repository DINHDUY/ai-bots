# Containers

Podman-based containerization for the agentbot platform. Replaces Docker Desktop with rootless [Podman](https://podman.io/).

**Desktop users:** See [desktop/README.md](../desktop/README.md) for the Tauri desktop app that wraps these containers with a native UI.

## Directory layout

```
containers/
├── backend/
│   └── Containerfile          # agent-control-backend (FastAPI control plane)
├── frontend/
│   ├── Containerfile          # Production: Node 24 build → nginx static serve
│   ├── Containerfile.dev      # Dev: Vite dev server with hot-reload volume mounts
│   └── nginx.conf             # Proxies /api/ → backend, /ws → gateway
├── gateway/
│   └── Containerfile          # agentbot[gateway] (FastAPI WebSocket gateway)
└── agentbot/
    └── Containerfile          # agentbot-computer-agent (Linux host agent)

Root (repo root):
├── compose.dev.yml            # Local dev stack
├── compose.prd.yml            # Production stack
├── .env.compose.example       # Compose-specific env vars (PODMAN_SOCK, etc.)
└── docker/sandbox/
    └── Containerfile          # Sandbox image (Ubuntu + Playwright + Xvfb)
```

## Architecture

```
Browser
  │
  ▼
frontend (:5174 dev / :80 prod)
  │
  ├── /api/*  ──► backend (:8000 internal / :8001 host in dev)
  │                  │
  │                  └── Podman socket ──► sandbox containers
  │
  └── /ws     ──► gateway (:8000 internal / :8000 host in dev)
                     │
                     └── Podman socket ──► sandbox containers
```

In production, nginx serves the built React app and proxies API and WebSocket traffic on the same origin. In dev, the browser talks directly to the backend on `localhost:8001` via `VITE_API_BASE`.

## Prerequisites

Install Podman for your platform (one-time):

| Platform | Script |
|---|---|
| Linux | `bash scripts/install-podman-linux.sh` |
| macOS | `bash scripts/install-podman-mac.sh` |
| Windows | `.\scripts\install-podman-windows.ps1` (elevated PowerShell) |

After installing, run the setup script to detect the socket path and configure registries:

```bash
source scripts/podman-setup.sh
```

This writes `PODMAN_SOCK` to `.env.compose` automatically.

## Quick start

### Dev

```bash
# 1. Secrets and API keys
cp .env.example .env
$EDITOR .env          # set AGENTBOT_SECRET, OPENAI_API_KEY or ANTHROPIC_API_KEY

# 2. Compose env (socket path written by podman-setup.sh)
cp .env.compose.example .env.compose

# 3. Start all services with live rebuild
podman compose -f compose.dev.yml up --build
# or: make compose-dev
```

Services available after startup:

| Service | URL |
|---|---|
| Frontend (Vite) | http://localhost:5174 |
| Backend API | http://localhost:8001 |
| Gateway (WebSocket) | ws://localhost:8000/ws |

Frontend source files are volume-mounted for hot reload. Changing `src/` is reflected in the browser instantly without rebuilding the image.

### Production

```bash
podman compose -f compose.prd.yml up --build -d
# or: make compose-prd
```

The frontend is built into a static nginx image. All traffic goes through port 80. Backend and gateway are not exposed on the host.

To change the public port: set `FRONTEND_PORT=443` in `.env.compose` (then add TLS termination in front).

## Makefile targets

```
make sandbox-podman   # Build sandbox image with Podman
make podman-setup     # Run scripts/podman-setup.sh
make compose-dev      # podman compose -f compose.dev.yml up --build
make compose-prd      # podman compose -f compose.prd.yml up --build -d
make compose-down     # Stop both dev and prd stacks
make compose-logs     # Follow dev stack logs
```

## Containerfile details

### backend

- Base: `python:3.11-slim`
- Installs `agent-control-backend` from the uv workspace (`uv sync --locked --package agent-control-backend --no-dev`)
- Entry point: `agentbot-control` (FastAPI + Uvicorn on `0.0.0.0:8000`)
- Mounts: `./data` (SQLite db + session blobs), Podman socket
- Env: all vars from `.env`; `HOST`, `PORT`, `DOCKER_HOST` overridden by compose

### gateway

- Base: `python:3.11-slim`
- Installs `agentbot[gateway]` (`uv sync --locked --package agentbot --extra gateway --no-dev`)
- Entry point: `agentbot` (WebSocket gateway on `0.0.0.0:8000`)
- Mounts: Podman socket
- Stateless; no persistent volume needed

### frontend (production)

Two-stage build:
1. `node:24-alpine` — `npm ci` + `npm run build` (TypeScript check + Vite bundle)
2. `nginx:alpine` — serves `dist/` with SPA fallback and upstream proxies

`VITE_API_BASE` is empty at build time; nginx handles routing so no hardcoded host is needed.

### frontend (dev)

- Base: `node:24-alpine`
- Runs `npm run dev -- --host 0.0.0.0 --port 5174`
- `VITE_API_BASE=http://localhost:8001` so the browser reaches the backend directly
- `src/`, `public/`, and `index.html` are volume-mounted for hot reload; `node_modules` stays in the container

### agentbot (computer-agent)

- Base: `python:3.11-slim`
- Installs `agentbot-computer-agent` (`uv sync --locked --package agentbot-computer-agent --no-dev`)
- Entry point: `agentbot-computer-agent`
- Deployed on agent computers (Linux VMs / sandbox hosts), not in the main compose stack

### sandbox

- Location: `docker/sandbox/Containerfile`
- Base: `ubuntu:24.04`
- Includes: Python 3, Playwright (Chromium), Xvfb, Openbox, xdotool, scrot
- Spawned dynamically by the backend/gateway at runtime via the Podman socket
- Build: `make sandbox-podman` or `podman build -f docker/sandbox/Containerfile -t agentbot-sandbox .`

## Environment variables

### `.env` (app config — from `.env.example`)

All runtime secrets and tuning knobs live here. Key required fields:

| Variable | Description |
|---|---|
| `AGENTBOT_SECRET` | Session-signing secret (256-bit hex or plain string) |
| `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` | At least one LLM provider key |
| `SANDBOX_IMAGE` | Container image for sandboxes (default: `agentbot-sandbox`) |

### `.env.compose` (compose overrides — from `.env.compose.example`)

| Variable | Description | Default |
|---|---|---|
| `PODMAN_SOCK` | Path to the Podman socket on the host | `/run/user/1000/podman/podman.sock` |
| `FRONTEND_PORT` | Host port for the nginx container (prod only) | `80` |
| `CORS_ORIGINS` | Backend CORS allowed origin (prod only) | `http://localhost` |

## Podman notes

- **Rootless by default** — containers run without root privileges.
- **Socket path** — Podman uses `$XDG_RUNTIME_DIR/podman/podman.sock`, not `/var/run/docker.sock`. The socket is mounted into backend and gateway containers as `/run/podman.sock`, and `DOCKER_HOST=unix:///run/podman.sock` tells the Python Docker SDK where to find it.
- **Windows** — requires WSL2. The socket is exposed as a named pipe (`npipe:////./pipe/podman-machine-default`). Set both `PODMAN_SOCK` and `DOCKER_HOST` in `.env.compose`.
- **Registry search** — `podman-setup.sh` adds `docker.io`, `quay.io`, and `ghcr.io` to `~/.config/containers/registries.conf` so unqualified image names resolve without the `docker.io/` prefix.
- **BuildKit cache** — Containerfiles use `--mount=type=cache,target=/root/.cache/uv` for fast incremental uv installs. Podman supports this via `--layers` (enabled by default in recent versions).
