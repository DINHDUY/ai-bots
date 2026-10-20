# Agent Control Desktop

A lightweight Tauri 2 desktop shell for the Agent Control Podman stack. The desktop app manages container lifecycle (start, health checks, stop) while the actual application UI runs in the containerized frontend.

## Quick start

### Prerequisites

1. **Podman** — Install for your platform:
   - Linux: `bash ../scripts/install-podman-linux.sh`
   - macOS: `bash ../scripts/install-podman-mac.sh`
   - Windows: `.\scripts\install-podman-windows.ps1` (from project root)

2. **Rust** — [Install from rustup.rs](https://rustup.rs) (stable toolchain 1.77.2+)

3. **Node.js** — 20+ (or use `nvm` / `fnm`)

### Run in development

```bash
# From the desktop/ directory
make install       # Install Node and Rust deps
make dev           # Start the desktop app with Podman stack

# In another terminal, watch the compose logs:
podman compose -f ../compose.dev.yml logs -f
```

The app will:
1. Detect Podman and ensure Podman Machine is running (macOS)
2. Start the compose stack (`../compose.dev.yml`)
3. Wait for services to be healthy
4. Open a window with the containerized frontend UI

### Build for release

```bash
make release       # Build optimized desktop binaries for your platform
# Output: src-tauri/target/release/bundle/
```

On Windows, the release build automatically downloads and bundles the Podman MSI installer.

## Architecture

```
┌──────────────────────────────────────────┐
│   Desktop Window (Tauri 2)               │
│  ┌────────────────────────────────────┐  │
│  │  Loading/Boot Screen (React)       │  │
│  │  • Checks Podman availability      │  │
│  │  • Waits for service health        │  │
│  │  • Navigates to UI once ready      │  │
│  └────────────────────────────────────┘  │
│           ▼                               │
│  ┌────────────────────────────────────┐  │
│  │  Containerized Frontend (http)     │  │
│  │  (loaded once compose is healthy)  │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
         ▼
┌──────────────────────────────────────────┐
│   Podman Compose Stack                   │
│  ┌──────────┐  ┌────────┐  ┌────────┐   │
│  │ Backend  │  │Gateway │  │Sandbox │   │
│  │ :8001    │  │:8000   │  │Mgmt    │   │
│  └──────────┘  └────────┘  └────────┘   │
│  (Connects via internal network)         │
└──────────────────────────────────────────┘
```

## Configuration

### `shell.toml` (stack config)

Defines how the stack launches:
- `compose_file` — which compose file to use (`compose.dev.yml` or `compose.prd.yml`)
- `health_url` — where to poll for readiness (e.g., `http://localhost:5174/health`)
- `wait_timeout` — max seconds to wait for services to start (default: 120)

### `.env` (secrets & tuning)

Copy from `.env.example` and fill in:
- `AGENTBOT_SECRET` — session-signing secret
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` — at least one LLM provider
- Other vars from main project's `.env`

### `COMPOSE_FILE` environment variable

Override which compose file to use:
```bash
COMPOSE_FILE=compose.prd.yml make dev    # Use production compose
```

## File structure

```
desktop/
├── src/                                  # React frontend (boot screen)
│   └── main.tsx
├── src-tauri/                           # Rust backend (Tauri)
│   ├── src/
│   │   ├── main.rs                      # Entry point
│   │   ├── compose.rs                   # Compose stack management
│   │   ├── engine.rs                    # Podman detection & commands
│   │   ├── stack.rs                     # Stack lifecycle
│   │   └── lib.rs
│   ├── Cargo.toml                       # Rust dependencies
│   ├── tauri.conf.json                  # Tauri configuration
│   └── build.rs
├── index.html                           # HTML entry point
├── package.json                         # Node dependencies
├── vite.config.ts                       # Vite build config
├── tsconfig.json                        # TypeScript config
├── Makefile                             # Build targets
├── shell.toml                           # Stack configuration
├── .env.example                         # Environment template
└── README.md
```

## How it works

### On startup (dev or release)

1. **Podman detection** — Rust backend checks if Podman is installed and running
   - On macOS: auto-starts Podman Machine if configured to do so
   - On Windows: prompts to install if missing (release builds)

2. **Compose up** — Starts the stack from `compose.dev.yml` (or `.prd.yml`)
   - Sets `PODMAN_SOCK` and `DOCKER_HOST` from env
   - Waits for all services to be healthy

3. **Health polling** — React boot screen polls a health endpoint
   - Backend: `http://localhost:8001/health`
   - Frontend: `http://localhost:5174/health` (from nginx in prod)
   - Retries for up to 120 seconds (configurable)

4. **UI load** — Once healthy, the Tauri webview navigates to the UI URL
   - Dev: `http://localhost:5174` (Vite dev server in container)
   - Prod: `http://localhost` (nginx serving built frontend)

### On close

- Runs `podman compose down` (keeps volumes by default, configurable via `PRESERVE_VOLUMES`)
- Does NOT stop the Podman machine (intentional — allows for quick restart)

## Podman notes

- **Rootless by default** — Containers run without root. Socket is at `$XDG_RUNTIME_DIR/podman/podman.sock` (Linux) or detected via `podman machine inspect` (macOS).
- **Podman Machine (macOS)** — QEMU-backed VM. The app auto-starts it if needed.
- **Windows** — Requires WSL2. Podman socket is `npipe:////./pipe/podman-machine-default`. Release builds bundle the MSI installer.
- **Socket mounting** — The Rust backend passes the socket path to Podman Compose so containers can spawn sandboxes.

## Troubleshooting

### "Podman not found"

Install Podman from the scripts in the main project:
```bash
cd ..
bash scripts/install-podman-linux.sh    # or -mac.sh on macOS
source scripts/podman-setup.sh
```

### "Podman not running"

**Linux/macOS:** Start the systemd user socket or Podman Machine:
```bash
systemctl --user start podman.socket   # Linux
podman machine start                    # macOS
```

**Windows:** Start Podman Desktop or the Podman service.

### Services not starting

Check the logs:
```bash
podman compose -f ../compose.dev.yml logs -f
```

Common issues:
- Port already in use: change `FRONTEND_PORT` or `PODMAN_SOCK` in `.env`
- Image pull failure: check network and `~/.config/containers/registries.conf`
- Secrets missing: ensure `.env` has `AGENTBOT_SECRET` and API keys filled in

### Boot screen stuck at "Starting services"

Increase the `wait_timeout` in `shell.toml` or set `HEALTH_CHECK_TIMEOUT` in `.env`. If services still fail to start, check Podman logs.

## Development

### Modifying the Rust backend

The backend lives in `src-tauri/src/`. Key modules:

| Module | Purpose |
|---|---|
| `main.rs` | Tauri entry point, command handlers |
| `engine.rs` | Podman detection, version checks |
| `compose.rs` | Stack lifecycle (up, down, health) |
| `stack.rs` | High-level stack orchestration |

Rebuild after changes:
```bash
make install      # Recompile Rust
make dev
```

### Modifying the frontend boot screen

Edit `src/main.tsx`. The boot screen shows progress while Podman starts services. Once healthy, it triggers navigation to the containerized UI.

Vite hot-reload applies changes instantly during `make dev`.

### Building for multiple platforms

Cross-compilation requires toolchains for each target. For simplicity, build on each platform:

```bash
# macOS
cargo tauri build --target universal-apple-darwin

# Windows
cargo tauri build --target x86_64-pc-windows-msvc

# Linux (x86_64)
cargo tauri build --target x86_64-unknown-linux-gnu
```

See [Tauri documentation](https://tauri.app/en/v2/guides/building/) for details.

## License

Follows the main project's license. See `LICENSE` in the repository root.
