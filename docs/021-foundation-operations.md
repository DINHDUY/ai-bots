# Foundation operations

This runbook describes the foundation working tree built from `ac164dc`. The [implementation ledger](003-agent-control-implementation-status.md) records acceptance gaps; this is not an unattended-production qualification. Use one control process per SQLite deployment.

## Installation and artifacts

Use `uv sync --locked` with Python 3.11 or 3.13 and `npm ci --prefix packages/agent-control-frontend` with Node 24. The committed `.npmrc` enables the required peer-dependency compatibility. The interactive UFO environment still uses its separately pinned Python 3.11/native setup in the [Windows runbook](007-agent-control-ufo-runtime.md).

`agentbot` installs without web, Docker, model SDK or product dependencies. Its `gateway`, `docker`, `anthropic`, and `microsoft` extras enable those integrations. The control backend installs its required extras and `agentbot-product-tools[ufo]`. Workspace messaging and the UFO adapter live in `agentbot_tools`. ETL is a standalone documentation demo under `docs/usecases`; it has no installed handler, tool registration or frontend preset. Framework adapters still contain some connector/skill conventions pending the remainder of F1.

`AGENTBOT_TOOL_MANIFESTS` and `AGENTBOT_TOOL_ALLOWLIST` optionally add CLI tools and allowlisted Python tools to the catalog at startup. Leave both unset when the deployment uses only maintained tools. See [030](030-tool-plugins.md).

The sandbox pins Playwright 1.63.0. Build and record the image digest used by a deployment. In a corporate CA environment, a build may use `--secret id=build_ca,src=<trusted-public-CA-bundle.pem>`; the Dockerfile supplies that trust bundle to the browser downloader for that build step. Do not disable TLS verification. The build secret is not copied into the image.

CI is defined in `.github/workflows/check.yml`; this checkout has no configured remote, so hosted results, branch protection and live-provider jobs remain unverified. `--require-docker` fails the integration gate if Docker tests are missing or unexpectedly skipped.

## Capacity and readiness

Capacity checks run in the same SQLite transaction as admission. A duplicate command returns its existing receipt before checking new capacity. Quotas charge the bot owner, including work started by a collaborator, routine or channel.

| Setting | Default | Meaning |
| --- | --- | --- |
| `CONTROL_MAX_RUNS` | 32 | Deployment-wide active runs |
| `CONTROL_MAX_RUNS_PER_OWNER` | 8 | Active runs belonging to one bot owner |
| `CONTROL_MAX_COMPUTERS` | 64 | Deployment-wide non-closed computer sessions |
| `CONTROL_MAX_COMPUTERS_PER_OWNER` | 16 | Non-closed computers belonging to one bot owner |

All values must be positive integers. These are defensive ceilings, not measured throughput promises. Preparing, awaiting approval and stopping runs count as active. Failed, retained and hibernated computers consume capacity until closed. Exceeding run admission returns HTTP 429, `code: capacity_limit`, and `Retry-After: 5`. Lifecycle operations also enforce computer reservations and report rejection through their durable operation result. Lowering a limit does not terminate existing resources; it prevents additional reservations.

`GET /health` is process liveness. `GET /ready` returns 503 while startup/recovery is incomplete, persistence fails, or a required worker has stopped or stopped making progress. It can remain unready briefly after startup while workers complete their first iteration. Required workers cover runtime cleanup, computer monitoring, control leases, routines, channels, and capture cleanup. Disabled features do not enable unsafe admission.

Optional cloud reconciliation failures reject cloud work while allowing unrelated local work. No supervisor restarts an uncertain action or replays external side effects. Owner diagnostics report worker progress and cumulative database queue/work durations. The bounded database worker admits at most 128 jobs; overload produces a retryable 503. Some legacy database calls still execute on the event loop, so these counters do not yet measure all persistence.

Operational response:

- Unready or stopped worker: inspect authenticated diagnostics and process logs, stop new submissions, reconcile active/uncertain runs, then restart the single control process after its previous writer has drained.
- Capacity rejection: inspect active runs and retained computers, stop unnecessary work, or close unused computers after retaining their files. Increase limits only after measuring the intended workload.
- Persistence errors or disk pressure: stop new work, retain database/WAL/blob evidence, restore free space, and verify database integrity before resuming. Do not delete uncertain execution records to free space.
- Unverified termination: retain the computer quarantine and investigate the provider. A process restart is not proof that its external action stopped.

Aggregate metrics export, automated alerts, correlated logs across every bridge, and the five-minute capacity benchmark remain F7 acceptance work.

## Authentication

Login is bounded per account (five attempts per minute) and source (100 per 15 minutes). Registration allows five attempts per source per hour. Expired counters are removed and storage is capped. Successful login clears its account counter; source counters remain. Throttling returns 429 and `Retry-After`. At most four password jobs run concurrently; cancelled callers retain their slot until the CPU operation settles.

The source is the ASGI client address. Configure trusted proxy addresses at the server boundary; the application does not independently trust an arbitrary `X-Forwarded-For`. Behind a proxy that does not provide a trusted client address, clients share the proxy's source quota.

## Encryption and key rotation

New encrypted values use `v1:<key-id>:<Fernet-token>`. With no keyring, the vault derives an encryption key from `AGENTBOT_SECRET` with HKDF-SHA256 and the purpose label `agentbot:encryption:v1`. Legacy Fernet values remain readable using the prior derivation. Unknown versions and missing keys fail closed.

For independently managed encryption, set `AGENTBOT_KEYRING_FILE` to a protected JSON file:

```json
{"active":"key-2026-10","keys":{"key-2026-10":"<generated-Fernet-key>"}}
```

Generate keys with `cryptography.fernet.Fernet.generate_key()` into an access-controlled file or secret-management workflow. Do not put real keys in command arguments, source control, logs or documentation. Restrict the keyring, legacy-secret files, database and backups to the service/operator account using OS permissions. Key IDs identify immutable material: never replace a key under an existing ID. To rotate, retain old entries and change `active` to a new ID.

The complete rotation inventory is `repositories/vault.py`: model credentials, connector secrets, webhook secrets, sealed action arguments, policy constraints, and cloud continuation material. Procedure:

1. Stop admissions, drain or explicitly stop active work, and stop the control process. The maintenance command takes the same OS process lock and refuses an active deployment.
2. Take a consistent database/blob backup and securely retain the keys required by it. Upgrade the database to this application's migration set before invoking this version of maintenance.
3. Prepare the new keyring containing all retained explicit keys. For values derived from an old signing secret, supply a protected file containing that original secret. The command accepts repeated `--legacy-secret-file` options. It can recover both legacy tokens and versioned derived-key tokens.
4. Verify on an isolated restore first, then run against the stopped deployment:

```powershell
uv run --no-sync agentbot-maintenance rotate-keys --database data/control.sqlite --keyring C:/protected/keyring.json --legacy-secret-file C:/protected/old-signing-secret.txt --dry-run
uv run --no-sync agentbot-maintenance rotate-keys --database data/control.sqlite --keyring C:/protected/keyring.json --legacy-secret-file C:/protected/old-signing-secret.txt
uv run --no-sync agentbot-maintenance rotate-keys --database data/control.sqlite --keyring C:/protected/keyring.json --legacy-secret-file C:/protected/old-signing-secret.txt --dry-run
```

5. Require the final dry run to verify all records and report zero rotation candidates. Update `AGENTBOT_KEYRING_FILE`, start the service, and verify the relevant credential/connector/policy workflows without launching unintended side effects.

Dry run does not apply schema migrations or rewrite values. Rotation commits batches of 100; after interruption, repeat the same command. Already current records are verified and skipped. Output contains counts and the active key ID, never plaintext secrets. Do not remove old keys until active records and every retained backup have a recovery path. An interrupted rotation requires both old and new keys.

Rotating only the encryption key does not invalidate login cookies. Changing `AGENTBOT_SECRET` invalidates existing cookies and, without an explicit keyring, changes the derived encryption key. Complete migration to the explicit keyring before changing the signing secret. Older application versions cannot read v1 envelopes; rollback requires the matching pre-upgrade database/blob/key backup after fencing execution.

## Consistent backups and fenced restores

Stop the control process and all writers before backup. `agentbot-backup` takes the deployment process lock, uses SQLite's backup API (including committed WAL pages), copies retained blobs without following links, and writes a SHA-256 manifest last. A directory without a complete manifest is not a valid backup. Use a new protected destination; the tool refuses to overwrite an existing one.

```powershell
uv run --no-sync agentbot-backup create --database data/control.sqlite --destination C:/protected/backups/control-2026-10-09
uv run --no-sync agentbot-backup restore-for-verification --snapshot C:/protected/backups/control-2026-10-09 --destination C:/isolated/restore-2026-10-09
```

Keys are deliberately excluded from the snapshot. Retain the required keyring/signing-secret history separately under equivalent access controls, along with legacy transcript sources, compute profiles, image/package versions and provider deployment metadata. Hashes detect corruption; they do not authenticate an attacker-modified backup. Protect the entire backup location.

A restore verifies file inventory and hashes and writes `control.restore-only` before copying. Application startup refuses this marker. Keep it in place during inspection and rotation drills: these offline tools do not start cloud clients, schedulers, or sandbox bridges. Inspect SQLite integrity/foreign keys, users/permissions, receipts/events, blob hashes, all encrypted fields and interrupted-run/provider identities.

Activation is a separate operator operation. Fence the original deployment and production computer identities, choose the intended deployment identity, reconcile uncertain outcomes and provider ownership, and only then remove the restore marker. Never activate a copied database concurrently against its original computers. No production restore or provider-adoption drill has been executed by this change; recovery-time and backup-interval objectives still require measurement.

## Provider guarantees and remaining containment work

| Provider | Current boundary | Remaining F3 qualification |
| --- | --- | --- |
| Local Docker | Non-root workload, resource limits, scoped workspace, generation/approval fences; container isolation rather than a VM | Default bridge traffic is not restricted by a maintained egress proxy. Private/metadata/peer destination denial, DNS/redirect bypass and proxy-failure tests remain open. Chromium sandbox compatibility still requires review. |
| Azure | Existing private/metadata network fences, dedicated trusted host workspace, outbound bridge identity and operation fencing | No complete hostname/resource egress policy. Trusted host enrollment traffic must stay separate from workload traffic. Real isolated Azure lifecycle/network/recovery acceptance remains open. |
| Paired Windows | User-controlled interactive desktop, explicit local sharing/control consent, input/stop and stale-target fencing | It is not container containment. Native desktop/network behavior needs the qualified interactive environment; unsupported containment guarantees must not be represented as supported. |
| Backend connectors | Existing repository/credential binding and revocation, approved operations; credentials remain on backend | A workload proxy would not constrain backend clients. Versioned resource policy and broader endpoint enforcement remain open. |

The new capacity/authentication controls do not close F3a. Versioned per-resource unattended policy, maintained egress enforcement and live provider acceptance are still required before declaring the corresponding unattended deployment guarantees.

## Protocol, retention and upgrades

The SPA requires v2. Server compatibility `/ws` remains for external consumers and keeps disconnect-cancels semantics. Its deprecation starts with the release containing this change; retain it through at least the next minor release and remove only after recording the consumer inventory and publishing migration instructions. There is no scheduled removal date until that release exists. The standalone raw gateway retains its independent development protocol.

Commit-driven subscriptions read committed pages, bound sends to five seconds, and reconcile lost notifications and idle authorization at least every five seconds while the loop and database are responsive. Slow consumers disconnect and recover from their durable cursor. There is no durable queue of socket payloads or browser replay of execution commands.

Existing event/capture retention and quotas remain in effect. Complete policies for command receipts, completed automation jobs and host journals are still open; do not prune active or uncertain records or shorten retry deduplication without a documented compatibility window.

Drain runs before upgrading tool implementations: handler source digests intentionally invalidate pinned manifests after code changes. Retain a matching package/image/database/key set for rollback. Package versions remain 0.1.0; no release tag, publication, deployment or hosted branch-protection change is part of this working-tree implementation.
