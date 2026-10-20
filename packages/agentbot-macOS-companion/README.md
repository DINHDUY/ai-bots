# Agent Control macOS companion

Native Open-Interface runtime and portable UFO³ TaskStar bridge. Development implementation; interactive macOS and live-model qualification remain required. See the [runbook](../../docs/030-agent-control-macos-runtime.md) and [approved plan](../../docs/029-agent-control-macos-companion-plan.md).

From the repository root on an Apple Silicon Mac:

```sh
uv sync --locked
make BIN=.venv/bin macos-setup
data/oi/venv/bin/agentbot-macos doctor
data/oi/venv/bin/agentbot-macos pair --backend http://127.0.0.1:8000
make BIN=.venv/bin macos-companion
```

Create an **Open Interface · macOS** bot, choose **Pair a Mac** in settings, and enter the one-time code at the local prompt. The credential is stored in Keychain. Enable Screen Recording and Accessibility for the actual native interpreter/launcher in System Settings and restart it. The CLI never grants permissions. In the local menu, select a window, enable **Share screen**, then **Allow agent control**. Select that Mac in bot settings, save, and connect.

`agentbot-macos status` and `stop` use a private same-user Unix socket. Pairing and running require the separate native interpreter; portable contracts work in the Python 3.11/3.13 workspace without native imports. Run as the signed-in user, never root or a background system daemon. HTTP pairing is restricted to loopback; other servers require HTTPS/WSS.

The runtime observes AX elements, captures the selected window using ScreenCaptureKit, provides local Vision OCR candidates, and executes an explicit input allowlist through patched Open-Interface. The primary-display capture path uses OI's screenshot implementation. Each mutation needs a backend-signed permit and a durable local receipt. The controller returns one proposal per observation through the existing approval dispatcher; model credentials stay in the backend.

`TaskStarBridge` implements the pinned upstream `TaskStar.execute(device_manager)` seam. Producers supply an authenticated `httpx.AsyncClient`, bot ID, and stable producer/task identity. The backend persists submission with run admission, returns the same receipt on retries, and rejects changed input. Whole Galaxy graphs and AIP registration are outside this package.

```sh
make BIN=.venv/bin macos-bridge-test
make BIN=.venv/bin macos-test
```

The bridge probe uses the actual pinned TaskStar and scripted HTTP. The native gate launches only a disposable owned editor; missing permissions or an unavailable interactive session fail the required gate. Portable tests use OS/transport doubles and do not establish native support.

Sources and dependency hashes are in `upstream.json` and `requirements-oi.lock`; qualification dependencies use `requirements-test.lock`. [Patch inventory](patches/README.md) records maintained upstream changes. Never delete the receipt journal to resolve an unknown result. Back up Keychain credentials and `~/Library/Application Support/AgentControl/macOS/` together using the recovery procedure.
