# SRS-003 Kernel and adapters

The framework-blind library and the model adapters. Invariants `INV-001` through `INV-005` and decisions `DEC-001` and `DEC-006` apply throughout.

## Interfaces

| ID | Requirement |
| --- | --- |
| KRN-001 | `ISandboxClient` MUST expose `run_bash`, `browser_open`, `browser_click`, `write_workspace_file`, `read_workspace_file`, `list_workspace`, `workspace_kind`, `screenshot`, `desktop_action`, and `close`. It MUST NOT contain LLM concepts. `browser_open` and `browser_click` MUST return PNG bytes. `browser_open` MUST accept only `http` and `https` URLs. |
| KRN-002 | `workspace_kind` MUST return `file`, `dir`, or `missing`. |
| KRN-003 | Optional capabilities MUST be `@runtime_checkable` Protocols: `SandboxManager`, `CheckedSandbox`, `CancellableSandbox`, `UncertainSandbox`, `ProtocolSandbox`, and `FileServiceSandbox`. |
| KRN-004 | `IAgentFrameworkAdapter.initialize` MUST bind sandbox, memory, and streamer, and MUST raise when the credential provider is not allowed for that framework. `execute_step` MUST yield event frames and MUST end every turn with exactly one `log/RESULT` frame, which MAY have an empty payload. |
| KRN-005 | Errors the model should see MUST be returned as tool-error strings. Exceptions MUST be reserved for adapter bugs. |
| KRN-006 | The registry MUST construct a fresh adapter per turn. Cross-turn state MUST live in memory context or the sandbox, not on grafted streamer attributes. |
| KRN-007 | `model=None` MUST mean process environment keys and MUST be used only by the raw gateway. The control plane MUST always pass a `ModelConfig`. |
| KRN-008 | `FrameworkRegistry` MUST map a lower-cased name to a zero-argument factory. `known(name)` MUST be the validation used by bot create. |

## Kernel

| ID | Requirement |
| --- | --- |
| KRN-009 | `process_agent_request` MUST reject a `session_id` that fails `^[A-Za-z0-9_-]{1,64}$` and MUST reject an empty prompt. |
| KRN-010 | The kernel MUST reject a session that is already busy, then clear busy state in `finally`. |
| KRN-011 | Unless the caller injects a sandbox and memory, the kernel MUST get or create the sandbox and load JSON `SessionStore` memory. Saves MUST be atomic (temp file plus replace). `persist_history=False` MUST skip that save. |
| KRN-012 | Every yielded frame MUST touch the activity clock. |
| KRN-013 | `close_idle` MUST close sessions that are not busy and have been idle longer than `SESSION_IDLE_SECONDS`. Both apps MUST run that sweep in the FastAPI lifespan. |
| KRN-014 | `SandboxRouter` MUST sit in front of Docker, Windows, and cloud managers. The in-memory test fake MUST NOT pretend to be a `SandboxManager`. |

## Model configuration

| ID | Requirement |
| --- | --- |
| KRN-015 | `ModelConfig` MUST be a frozen value object. Provider MUST be in the allowed set. The key MUST be 8–4096 characters on one line. The model id MUST match `^[A-Za-z0-9._:/-]{1,128}$`. `endpoint` MUST be present only for `azure_foundry` and MUST be https with no credentials, query, or fragment. |
| KRN-016 | `providers_for_framework` MUST be the only map from framework to credential providers: `anthropic` accepts only `anthropic`; `microsoft` accepts `openai` and `azure_foundry`. Bot create, bot update, and `initialize` MUST all enforce it. A Microsoft bot using Foundry MUST be able to select catalog model ids including `grok-4`. |
| KRN-017 | `OpenAIChatClient` for the Microsoft adapter MUST take either an OpenAI key or a Foundry key plus `base_url`. |

## Anthropic adapter

| ID | Requirement |
| --- | --- |
| KRN-018 | `ClaudeAgentAdapter` MUST call the Anthropic Messages API with the computer toolset, `str_replace_based_edit_tool`, and the bash tool. The model client MUST be a `CompletionClient` protocol so tests inject a scripted client. |
| KRN-019 | The loop MUST stop at `MAX_AGENT_STEPS` (default 25). Text MUST be yielded as `THOUGHT`. No tool use MUST yield `RESULT` and stop. Tool blocks in a response MUST run in order. |
| KRN-020 | Each block MUST require approval unless it is an observation, then dispatch to `desktop_action`, `run_bash`, or editor operations, and yield `TOOL_CALL` plus optional screenshot and `artifact_written` frames. |
| KRN-021 | After one block fails or is denied, remaining blocks in that batch MUST NOT execute. They MUST receive an error result that uses the fixed halt text. |
| KRN-022 | Editor `create` MUST refuse to overwrite. `str_replace` MUST require exactly one match. `insert` MUST validate the line range. `view` MUST number lines, truncate at 16000 characters, and MUST NOT require approval. A nonzero tool result MUST be marked as a tool error. |

## Microsoft adapter

| ID | Requirement |
| --- | --- |
| KRN-023 | `MicrosoftAgentAdapter` MUST bind `run_terminal_command`, `mutate_file`, `open_browser`, and `browser_click` with the SDK's own approval mode set to `never_require`. The adapter MUST gate every mutating call itself. |
| KRN-024 | The SDK MUST run in a background task. Tool callbacks and streamed text MUST push frames into an `asyncio.Queue` drained until a sentinel. The task MUST be cancelled in `finally`. The runner MUST be injectable. |
| KRN-025 | Tool calls MUST stop at `MAX_TOOL_TURNS` (default 20). History MUST be replayed as a `role: content` prefix of prompts and final answers. |
| KRN-026 | The adapter SHOULD send bounded conversation history with preserved roles, explicit resume intent, and exact file patches. `run.metrics` timing, text batching, shared Docker health inspections, and the checked-action path MUST keep dispatch authorization and stale-target checks. These behaviors MUST apply with Autopilot on or off. |

## Frames the kernel understands

| ID | Requirement |
| --- | --- |
| KRN-027 | Log types MUST be `SYSTEM`, `THOUGHT`, `TOOL_CALL`, `RESULT`, `ERROR`, and `SCREENSHOT_CAPTURE`. `source` MUST be the adapter engine name. Screenshot payload MUST be base64 PNG on the v1 frame. `artifact_written` MUST include `path` and a preview of at most 200 characters. |
| KRN-028 | `begin_approval` MUST create an `asyncio.Future` under a random id. `wait_for_approval` MUST use `APPROVAL_TIMEOUT_SECONDS`. Timeout MUST set the future false. |
| KRN-029 | Adapters MAY emit `emit_plan` with unique step ids, titles, and explicit statuses, producing `plan.updated`. The kernel MUST NOT infer a plan from prose or tool counts. |
| KRN-030 | A completed model run MAY contain failed actions. `run.finished` MUST report `failed_actions`. Exit code 0 MUST NOT be treated as proof of an external publication. |

## Optional CLI runtimes

Implement only if needed. If implemented, all of the following are MUST.

| ID | Requirement |
| --- | --- |
| KRN-031 | Cursor CLI, Codex, and Copilot CLIs MUST run inside the sandbox with `cwd=/workspace`. They MUST NOT emit desktop frames. Approval MUST be one `run_cli` decision per turn before the process starts. `CLI_TURN_APPROVAL=0` MAY skip that gate for operators. |
| KRN-032 | The prompt MUST be written to a mode-0600 tmpfs file and MUST NOT appear in argv. Only named environment variables MUST be forwarded. `CLI_TURN_TIMEOUT_SECONDS` MUST default to 900. Cancel or timeout MUST kill the process group (`setsid`, then TERM, then KILL after 5 seconds) and emit `ERROR`. |
| KRN-033 | A single stdout line MUST be capped at 1 MB. The stderr tail on ERROR MUST be at most 4 KB. Unknown vendor event types MUST be ignored. On a fresh container, transcript re-seed MUST use the last 20 messages and at most 8000 characters. |
| KRN-034 | Session continuity MUST use `agent create-chat` and `--resume` for Cursor, `thread_id` and `codex exec resume` for Codex, and `--session-id` for Copilot. `model_required` MUST be false for these three. Codex against Azure AI Foundry is out of scope. Full-auto CLI flags are acceptable only because the process is inside the container. |

## Optional Cursor SDK adapter

| ID | Requirement |
| --- | --- |
| KRN-035 | A Cursor SDK adapter MAY drive `cursor-sdk` from the gateway process. It MUST register as `cursor`. A CLI adapter, if both exist, MUST register as `cursor-cli`. Built-in shell, task, and web search tools MUST be disallowed. No `setting_sources` or `mcp_servers` MUST be passed. |
| KRN-036 | Scratch directory MUST default to `data/cursor-scratch` and MUST start empty. One fresh agent MUST be used per turn. `MAX_TOOL_TURNS` MUST cap the turn. `CursorAgentError` with `is_retryable=True` MUST be logged and MUST NOT be retried automatically. |
| KRN-037 | Host tools MUST be `run_terminal_command` and browser actions (approval required) plus `read_file`, `list_dir`, and `screenshot` (no approval). `write_file` MUST still hit the sandbox write approval. Sandbox errors MUST return as `"<tool> error: …"` strings. Durable `Agent.resume` and Cursor-hosted cloud agents are out of scope. |

## Traceability

| IDs | Sources |
| --- | --- |
| KRN-001–KRN-017 | Blueprint §§6.1–6.5; ADR-0001, ADR-0013 |
| KRN-018–KRN-030 | Blueprint §§6.4 and 8.1; [011](../011-agent-control-autopilot-performance.md); [016](../016-agent-control-backend-runtime.md) |
| KRN-031–KRN-037 | [cli-runtimes.md](../cli-runtimes.md); [cursor-sdk-adapter.md](../cursor-sdk-adapter.md); blueprint §11.4 |
