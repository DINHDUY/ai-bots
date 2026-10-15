# Agent bot platform

Framework-agnostic kernel for autonomous agent sessions. A request names `microsoft` or `anthropic`. The kernel resolves that adapter, attaches the session's Docker sandbox, and streams event frames over a WebSocket.

People using the web app should start with the [user guide](docs/user-guide/README.md).

Start with [docs/architecture-blueprint.md](docs/architecture-blueprint.md). The older narrative is in [docs/architecture.md](docs/architecture.md) and [docs/implementation-plan.md](docs/implementation-plan.md). Numbered design notes:

| Doc | Topic |
| --- | --- |
| [001](docs/001-agent-control-design-system.md)–[009](docs/009-agent-control-frontend.md) | Design system, control plane, sandbox, UFO, frontend |
| [010](docs/010-agent-control-azure-runtime.md)–[019](docs/019-agent-control-capture-retention-runtime.md) | Cloud, Autopilot, tool libraries, channels, capture retention |
| [024](docs/024-markdown-workflow-import-plan.md)–[025](docs/025-markdown-workflow-import.md) | Import agent Markdown workflows into a new workspace |
| [026](docs/026-workspace-deletion-plan.md)–[028](docs/028-workspace-deletion-audit.md) | [Delete a workspace](docs/027-workspace-deletion.md), cleanup, and recovery |
| [code review](docs/code-reviews/v0.3.0-reviews.md) | Architecture review for tag `v0.3.0` |
| [ADRs](docs/adr/0001-async-generator-adapter-boundary.md) | Decisions 0001–0016 |

The control plane registers three frameworks: `microsoft`, `anthropic`, and `ufo` (a local Windows desktop). Computers can be the Docker sandbox, a paired Windows PC, or an Azure cloud computer. Autopilot can approve eligible actions when the owner turns it on.

**Workspace settings → Import workflow** turns local agent Markdown files into a
new workspace: one bot per file, instructions without YAML frontmatter, a shared
Docker computer by default, and Bot channel messaging enabled for every bot.
Review names and model settings before importing. See the
[import guide](docs/025-markdown-workflow-import.md) for limits and recovery.

## Run

Use Python 3.11 (the default) or 3.13, Node 24, and uv 0.11.14. The native UFO companion retains its separate qualified Python 3.11 setup.

```powershell
uv sync --locked
# For a new checkout only; keep an existing .env.
Copy-Item .env.example .env
```

Set `AGENTBOT_SECRET` before starting the control plane. Without an explicit `AGENTBOT_KEYRING_FILE`, that secret also derives a purpose-separated encryption key. Read the [key rotation and backup runbook](docs/021-foundation-operations.md) before changing it; the offline rotation command preserves existing encrypted records. Signing-secret changes invalidate login cookies. The raw `agentbot` gateway still reads `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the environment. Signed-in bots do not use those process keys: each user adds an OpenAI key, an Anthropic key, or an Azure AI Foundry key (endpoint plus key) and picks it on the bot. A Microsoft bot can use OpenAI or Foundry xAI (`grok-4` and the other catalog model ids). An Anthropic bot can only use an Anthropic key. Build the sandbox image from the repo root:

```bash
docker build -f docker/sandbox/Dockerfile -t agentbot-sandbox .
uv run --no-sync agentbot-control
```

The control plane listens on `http://127.0.0.1:8000` and serves the API only. `GET /health` reports process liveness; `GET /ready` checks persistence and required worker progress and returns 503 until ready. `ALLOW_REGISTER=0` closes registration. `agentbot` still starts the raw gateway on the same port, so run only one of them at a time.

`make install` runs the locked workspace installation and verifies the installed backend import. The portable `agentbot` distribution has no mandatory runtime dependencies; gateway, Docker and model SDK support are explicit extras. The control backend installs these extras and the separate `agentbot-product-tools` package.

The web UI is a separate package. In another terminal:

```bash
cd packages/agent-control-frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. An optional, manually configured demo lives in [docs/usecases](docs/usecases/azure-blob-etl-playbook.md); it is not bundled as an application preset or tool. `CORS_ORIGINS` must include that origin (`.env.example` already does). If `.env` was created before that line existed, add `CORS_ORIGINS=http://127.0.0.1:5173`. `COOKIE_SAMESITE` defaults to `lax`, which is enough here because both processes use `127.0.0.1`. A fully cross-site deployment needs `COOKIE_SAMESITE=none` and `COOKIE_SECURE=1`. See [docs/009-agent-control-frontend.md](docs/009-agent-control-frontend.md).

## Authenticated commands and replay

The SPA requires protocol v2: HTTP commands with durable request IDs, snapshots, and `/api/bots/{bot_id}/events/ws?after_seq=...`. It validates the generated event schema, catches up before enabling controls, and never replays commands on reconnect. Approvals and automatic policies are server-owned. See the [frontend contract](docs/009-agent-control-frontend.md).

## Legacy control-plane WebSocket

This compatibility endpoint is retained for existing external clients; the current SPA does not use it. Its removal requires the consumer inventory and release notice described in the operations runbook. Sign in first. The client sends the `agentbot_session` cookie. Connect to `ws://127.0.0.1:8000/ws` and start a turn with a bot you own:

```json
{"action":"start","bot_id":"<id from POST /api/bots>","prompt":"List the files in the workspace."}
```

The server sends `{"event":"session","session_id":"<bot id>"}`, then log, artifact, and screenshot frames, then `{"event":"done"}`. `framework` and `session_id` are not accepted on this socket. Approvals, `stop`, and `close` use the same messages as the raw gateway. `close` removes the container and keeps the bot and its transcript.

## Raw gateway WebSocket

`agentbot` serves `ws://127.0.0.1:8000/ws` with no account. Start a turn:

```json
{"action":"start","framework":"anthropic","prompt":"List the files in the workspace.","session_id":"demo-1"}
```

The server sends `{"event":"session","session_id":"demo-1"}`, then log, artifact, and screenshot frames, then `{"event":"done"}`.

Bash, file writes, browser navigation, and most desktop actions pause until the client answers:

```json
{"action":"approve","approval_id":"<id from approval_required>","decision":"approve"}
```

`decision` may be `deny`. `{"action":"stop"}` cancels the current turn. `{"action":"close"}` removes that session's container.

`screenshot`, `zoom`, `cursor_position`, `wait`, and editor `view` do not ask for approval. `wait` and `hold_key` are capped at 30 seconds. Browser navigation accepts only `http` and `https` URLs.

## Development workflow

```bash
make install    # editable packages into .venv
make hooks      # pre-commit: ruff, pyright, line endings, frontend tsc
make check      # ruff, pyright, pytest, frontend lint, build, and unit tests
make check-docker   # pytest -m docker and Playwright, when the sandbox image exists
```

`make check` runs the local gates, schema drift check, documentation links, and a clean core-wheel installation probe. [CI](.github/workflows/check.yml) defines Windows/Linux checks on Python 3.11/3.13 and a required Docker/Playwright job. This checkout has no configured remote, so hosted execution and branch protection have not been verified. `npm ci` uses the committed peer-dependency configuration and TypeScript 6 lint parser beside the TypeScript 7 application compiler.

The [foundation implementation ledger](docs/003-agent-control-implementation-status.md) records completed changes, validation and remaining F0-F7 work; the full remediation plan remains in progress.

## Tests

For an existing Windows desktop, use the [Microsoft UFO companion setup and runbook](docs/007-agent-control-ufo-runtime.md). It adds a **Microsoft UFO** framework and **Local Windows PC** workspace with local sharing/control permission and the existing approvals/Autopilot dispatcher.

```bash
pytest
behave
npm test --prefix packages/agent-control-frontend
```

`pytest -m docker --require-docker` requires the sandbox image and fails on unexpected skips. `SANDBOX_IMAGE` selects an alternate test image. Use `pytest -m "not docker and not windows_desktop"` for the ordinary suite. Live model calls are not part of the test run.

`behave` runs `docs/usecases/tests/behavior/azure-blob-etl.feature`. It needs Docker, the `agentbot-sandbox` image, and a local Azurite blob service, which the steps start.
