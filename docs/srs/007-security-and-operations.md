# SRS-007 Security and operations

Cross-cutting controls. Apply them in every build phase. Threat details specialize `INV-004` through `INV-008` and `DEC-017`.

## Threat controls

| ID | Threat | Requirement |
| --- | --- | --- |
| SEC-001 | Untrusted model output and prompt injection | Side effects MUST pass the sandbox and the approval gate. Secrets MUST NOT be placed in the container unless the user puts them there. A denial MUST halt the rest of that tool batch. |
| SEC-002 | Cross-tenant access | Owner-scoped queries MUST be used everywhere. Foreign ids MUST be 404. Session keys MUST be server-chosen. v2 ownership MUST be rechecked before protected sends and during idle reconciliation. |
| SEC-003 | Cross-site request | The session cookie MUST be HttpOnly. Default `SameSite` MUST be `lax`. Unsafe methods and WebSocket upgrade MUST check the Origin allowlist. Bodies that are not JSON objects MUST be rejected. CORS MUST NOT use `*` with credentials. |
| SEC-004 | Container escape | CMP-004 hardening MUST hold. The Docker socket MUST NOT be mounted. |
| SEC-005 | Resource exhaustion | Bash MUST die after 30 seconds. Output MUST be capped. PID, memory, and CPU limits MUST hold. Agent steps MUST cap at 25 and Microsoft tool turns at 20. Run deadline MUST default to 900 seconds. Approval timeout MUST default to 120 seconds. Capture size and quota limits MUST hold. |
| SEC-006 | Credential leakage | Fernet at rest, never returned, decrypted per turn. Redact known keys, URL userinfo, and `sig` / `token` / `api_key` / `access_token` query parameters before persistence. Conceal protected-file previews. |
| SEC-007 | Path traversal | `resolve_workspace_path` plus the session-id regex MUST run before filesystem use. Live file APIs MUST also refuse symlinks and special files. |
| SEC-008 | Raw gateway exposure | The raw gateway MUST bind `127.0.0.1` by default and MUST be documented as dev/test only. |
| SEC-009 | Untrusted rendering | Markdown MUST disable raw HTML and MUST omit remote images. Captures MUST be displayed only as images. Sandbox HTML MUST NOT be served as an application-origin document. Downloads MUST set `nosniff` and an attachment disposition. |

Trust zones are the public internet and model output (untrusted), the browser (user-trusted, cross-origin), the control plane (trusted), and the sandbox or Windows desktop (untrusted execution). Data that crosses into the control plane from a model or a sandbox MUST be treated as data, never as a control-plane command.

## Authentication limits

| ID | Requirement |
| --- | --- |
| SEC-010 | Login MUST allow at most 5 attempts per minute per account and 100 attempts per 15 minutes per source. Registration MUST allow at most 5 attempts per source per hour. Excess MUST return 429 with `Retry-After`. Expired counters MUST be removed and storage MUST be capped. |
| SEC-011 | A successful login MUST clear that account's counter. Source counters MUST remain. At most 4 password hashes MUST run at once. A cancelled caller MUST keep its slot until the CPU operation settles. |
| SEC-012 | The source MUST be the ASGI client address. The application MUST NOT trust an arbitrary `X-Forwarded-For`. Operators MAY terminate TLS at a proxy they configure outside the app. |

## Keys and rotation

| ID | Requirement |
| --- | --- |
| SEC-013 | New ciphertext MUST use `v1:<key-id>:<Fernet-token>`. With no keyring, the vault MUST derive the key from `AGENTBOT_SECRET` with HKDF-SHA256 and info `agentbot:encryption:v1`. Legacy Fernet tokens MUST remain readable through the previous derivation. Unknown versions and missing keys MUST fail closed. |
| SEC-014 | `AGENTBOT_KEYRING_FILE` MUST point at protected JSON `{"active":"<id>","keys":{"<id>":"<Fernet-key>"}}`. Keys MUST be generated with `Fernet.generate_key()`. A key id MUST identify immutable material. Rotation MUST add a new id and change `active`. Real keys MUST NOT appear in arguments, source, logs, or docs. |
| SEC-015 | The sealed inventory MUST cover model credentials, connector secrets, webhook secrets, action arguments, policy constraints, and cloud continuation material. |
| SEC-016 | Rotation MUST run offline under the process lock, in restartable batches of 100, and MUST refuse an active deployment. A final dry run MUST report zero remaining candidates. Output MUST contain counts and the active key id, never plaintext. Old keys MUST stay until every live record and every retained backup can be read. |
| SEC-017 | Rotating only the encryption key MUST NOT invalidate login cookies. Changing `AGENTBOT_SECRET` MUST invalidate cookies. Without an explicit keyring, that change also changes the derived encryption key, so the operator MUST finish keyring migration before changing the signing secret. Rollback after rotation MUST restore the matching database, blobs, and keys. |
| SEC-018 | The maintenance command MUST accept repeated `--legacy-secret-file` values so both legacy tokens and versioned derived-key tokens can be rewritten. The operator SHOULD dry-run against an isolated restore before the stopped deployment. |

## Capacity

| Name | Default |
| --- | --- |
| `CONTROL_MAX_RUNS` | 32 deployment-wide active runs |
| `CONTROL_MAX_RUNS_PER_OWNER` | 8 |
| `CONTROL_MAX_COMPUTERS` | 64 non-closed computer sessions |
| `CONTROL_MAX_COMPUTERS_PER_OWNER` | 16 |

| ID | Requirement |
| --- | --- |
| SEC-019 | Preparing, awaiting approval, and stopping runs MUST count as active. A duplicate command MUST return its receipt before a new capacity check. Lowering a limit MUST NOT terminate existing resources. Exceeding run admission MUST return 429 `capacity_limit` with `Retry-After: 5`. Lifecycle rejection MUST be a durable operation result. |
| SEC-020 | Optional cloud dependency failure MUST degrade cloud features rather than crash unrelated bots. Admission MUST be rejected when a required worker is stopped or stalled. |

## Backup and restore

| ID | Requirement |
| --- | --- |
| SEC-021 | Writers MUST be stopped first. `agentbot-backup create` MUST take the process lock, copy the database with the SQLite backup API including committed WAL pages, copy blobs without following symlinks, and write the SHA-256 manifest last. A directory without a complete manifest MUST NOT be a valid backup. The tool MUST refuse to overwrite a destination. |
| SEC-022 | `restore-for-verification` MUST write `control.restore-only` before copying. Application startup MUST refuse that marker. Keys MUST be excluded from the snapshot. Hashes detect corruption; they MUST NOT be treated as authentication of a modified backup. |
| SEC-023 | Activation MUST fence the original deployment and computer identities, choose the intended deployment identity, reconcile uncertain outcomes and provider ownership, and only then remove the restore marker. A copied database MUST NOT run concurrently against the original computers. |
| SEC-024 | Create and restore commands MUST be `uv run --no-sync agentbot-backup create --database <db> --destination <path>` and `uv run --no-sync agentbot-backup restore-for-verification --snapshot <path> --destination <path>`. |

## Environment

| Name | Default | Rule |
| --- | --- | --- |
| `AGENTBOT_SECRET` | required | Cookie signing. Also the HKDF input when no keyring file is set. |
| `AGENTBOT_KEYRING_FILE` | unset | Explicit Fernet keyring. |
| `ALLOW_REGISTER` | `1` | `0` closes registration. |
| `COOKIE_SECURE` | empty | Required when `SameSite=none`. |
| `COOKIE_SAMESITE` | `lax` | `none` requires `COOKIE_SECURE=1`. |
| `CORS_ORIGINS` | `http://127.0.0.1:5174` | Credentialed allowlist. No `*`. |
| `SANDBOX_IMAGE` | `agentbot-sandbox` | Container image. |
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Bind address. |
| `VITE_API_BASE` | `http://127.0.0.1:8000` | Frontend API origin. WebSocket URL is the scheme swap. |
| `CONTROL_WORKSPACE_FEATURES` | enabled when `1` | `0` is the staged-upgrade posture. |
| `CONTROL_COMPUTE_PROFILES` | unset | Absolute path when Azure profiles are used. |

Startup with an empty `AGENTBOT_SECRET`, a `*` CORS origin, or `SameSite=none` without `COOKIE_SECURE=1` MUST fail fast.

## Hardening a rebuild should add

These are not current MUST behavior. A rebuild SHOULD close them in this order:

| ID | Requirement |
| --- | --- |
| SEC-025 | Per-bot egress control that blocks IMDS `169.254.169.254` and private ranges. Azure hosts already MUST do this (`CMP-043`); the local Docker bridge still has unrestricted egress. |
| SEC-026 | Stronger isolation for hostile multi-tenant use: gVisor, Kata, or Firecracker, a read-only root, a custom seccomp profile, and user-namespace remapping. |
| SEC-027 | Confirmed cancellation of a running `docker exec` via process-group supervision, not only cancellation of the host task. |
| SEC-028 | Audit export that includes actor identity on every decision. External KMS and a fully populated provider-rotation drill remain follow-up evidence, not a second on-disk format. |

## Traceability

| IDs | Sources |
| --- | --- |
| SEC-001–SEC-009 | Blueprint §§10.1–10.2 |
| SEC-010–SEC-024 | [021](../021-foundation-operations.md); ADR-0009, ADR-0017 |
| SEC-025–SEC-028 | Blueprint §10.4 |
