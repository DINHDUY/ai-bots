# Blob Autopilot performance investigation

Investigated on 2026-10-08 (America/New_York), using read-only queries against the local runtime database and a review of the execution path. No tasks were replayed or bot settings changed during the investigation. The implementation following that investigation is recorded below.

## Finding

Autopilot is already resolving Blob's approvals immediately. The biggest opportunity is to reduce unnecessary continuation of historical tasks, model round trips, and repeated script generation. Removing approval validation would address very little of the measured delay.

The latest completed Blob run received **`Hello`**, but continued an earlier ETL task. It inspected the workspace and configuration, generated a missing script, ran it, investigated a `BlobNotFound` response, rewrote the script, and ran it again.

Blob uses the Microsoft adapter with `grok-4.7`. Autopilot controls backend approval decisions; the adapter does not receive a distinct Autopilot execution strategy.

## Measured run

Run: `run_4c2a65daabdd49c5bd5361af6c318b39`, 2026-10-09 00:00:08–00:02:05 UTC (October 8, 8:00–8:02 PM EDT).

| Measurement | Time |
| --- | ---: |
| Total elapsed | 117.53 s |
| Seven tool executions, including sandbox overhead | 0.89 s |
| Approval registration to execution, summed across tools | 0.54 s |
| Remaining time outside those intervals | 116.10 s |

The remaining interval includes model inference, generated tool arguments, initial context checks, orchestration, logging, and finalization. Existing telemetry does not separate these costs. It should not be described as a precise model-only measurement.

| Action | Gap since preceding action ended, or run start | Outcome |
| --- | ---: | --- |
| List workspace and inspect time | 4.55 s | Completed |
| Inspect environment keys and SAS metadata | 13.96 s | Completed |
| Generate/write ETL script | 36.36 s | Completed |
| Run script | 1.70 s | Failed: HTTP 404 `BlobNotFound` |
| Inspect storage layout | 17.04 s | Completed |
| Rewrite ETL script with corrected URL construction | 35.88 s | Completed |
| Run script again | 1.76 s | Completed |

The two gaps before full script writes total **72.25 seconds**, about 61% of the run. The task encountered a real missing script and an incorrect blob URL, so several checks were useful once ETL execution began. The unnecessary step was beginning that work in response to a greeting.

The preceding Blob run, `run_c8b6989abfd44be486fa02e997db34e3`, took 145.45 seconds and ended with a model-client connection error approximately 90 seconds after its final tool action. It was a human-resume request that explicitly asked the model to re-observe the workspace and screen. That failure is distinct from approval latency.

## Code findings

1. **Historical tasks compete with the current request.** `Runtime.start` supplies prior conversation messages. At the latest run's admission there were 25 earlier messages totaling about 28,282 characters. The Microsoft runner flattens them into a single text prompt containing `user:` and `assistant:` prefixes, then appends the current request. It does not preserve these as separate API messages or provide an explicit completed-task boundary. This is a plausible contributor to the observed continuation; the logs do not establish it as the sole cause. See [runtime.py](../packages/agent-control-backend/src/agentbot_control/runtime/__init__.py) and [microsoft.py](../packages/agentbot/src/agentbot/adapters/microsoft.py).

2. **Only whole-file writing is exposed as a dedicated file mutation tool.** The Microsoft adapter exposes `mutate_file(path, content)`, but no bounded patch tool. Blob generated the whole ETL script twice to repair URL construction. A reusable, parameterized ETL operation or a small patch would reduce model-generated output. Shell commands could already patch a file, but the adapter does not guide this choice.

3. **Revision checks repeat even without a human approval wait.** `ActionArbiter` obtains context before registering approval and again before claiming it. Shell execution subsequently checks the expected workspace revision inside the command supervisor. These are three workspace revisions for a normal shell action when supported. The second check is a potential optimization for immediately authorized actions whose mutation endpoint still enforces the expected revision atomically. It must remain for paths that waited or lack such enforcement. See [approvals.py](../packages/agent-control-backend/src/agentbot_control/approvals/__init__.py), [docker.py](../packages/agentbot/src/agentbot/sandbox/docker/__init__.py), and [command.py](../docker/sandbox/agentbot_sandbox/command.py). The measured approval-to-execution intervals include the second check and total only 0.54 seconds here; the first and final checks are outside that total.

4. **Streamed text creates many durable events.** The latest run stored 345 `THOUGHT` text chunks within 355 observation events. These are streamed text fragments, not 345 tool checks. Each chunk passes through a SQLite transaction; the frontend joins consecutive chunks into one message. Coalescing text chunks would reduce database and UI work. Its wall-clock benefit has not been measured. See [microsoft.py](../packages/agentbot/src/agentbot/adapters/microsoft.py), [event_store.py](../packages/agent-control-backend/src/agentbot_control/event_store/__init__.py), and [reduce.ts](../packages/agent-control-frontend/src/session/reduce.ts).

5. **Monitoring is separate from Autopilot.** The run's time window includes 15 health events and 10 background captures. Both the backend monitor and the `/computer` endpoint perform inspections; the frontend polls computer status every 10 seconds and human-control state every 2 seconds. These intervals are not delays inserted between agent actions. Sharing a recent inspection result could reduce duplicate work without removing health reporting. See [computer.py](../packages/agent-control-backend/src/agentbot_control/computer.py) and [useComputerControl.ts](../packages/agent-control-frontend/src/features/workspace/useComputerControl.ts).

## Recommended implementation order

1. **Make current task intent explicit.** Preserve message roles, bound older history, and state that greetings/status questions do not resume previous work. Carry an explicit resume intent for the existing Resume action. Apply this behavior regardless of Autopilot state; automatic approval is not an instruction to start additional work.
2. **Reuse the ETL implementation.** Keep a validated, parameterized script or backend routine and run it with the requested date. Restore a retained script after a workspace reset instead of asking the model to regenerate it. Handle endpoint parsing and credential-expiry checks once in that implementation. Return a clear error when configured credentials are invalid instead of asking the model to invent an authentication fallback.
3. **Add a bounded patch tool and concise execution guidance.** Reuse successful observations until their inputs change; combine related read-only checks; patch the failing function instead of rewriting a whole file; verify the result once, then finish. Re-observe after errors, operator changes, or a new computer generation.
4. **Instrument model calls before changing models.** Measure model-call duration, time to first output, input/output tokens, context-check time, tool execution, and event persistence separately. Use these measurements to compare available models on the same ETL tasks and diagnose connection failures. Do not infer provider latency solely from gaps between actions.
5. **Optimize background overhead.** Batch streamed text on a short interval (for example, 50–100 ms, flushing at tool/final/error boundaries), share in-flight or recent health inspections, and then evaluate eliminating the redundant pre-dispatch context read on the narrowly eligible path described above.

Keep the final action claim, Autopilot revision check, argument validation, computer-generation checks, human-control checks, and checked mutation endpoint. These enforce stop/revocation and stale-target behavior and are not the dominant measured cost.

## Validation for implementation

- A greeting after an ETL conversation returns a greeting with no tool calls or workspace mutations.
- An explicit resume still continues the intended task after observing operator changes.
- A routine ETL rerun reuses the script; an endpoint error leads to a bounded repair rather than full regeneration.
- Empty/reset workspaces and expired credentials produce clear, bounded recovery behavior.
- Autopilot disabled before dispatch, workspace changes, and human takeover still prevent invalid execution.
- Text batching preserves all output and flushes before tool results, errors, and completion.
- Compare median and tail run times, model calls, generated tokens, tool count, and revision checks against the same task inputs. No speedup target is claimed until measured.

## Implemented

The Microsoft adapter used by Blob now:

- Preserves user/assistant API message roles and retains a suffix of at most 12 historical messages and 12,000 characters. It drops whole messages instead of cutting task parameters or credentials in half. The current request and standing bot instructions remain separate from history.
- Answers unambiguous standalone greetings without a model call or tools. Simple standalone status phrases use history with no tools. General requests receive explicit current-task instructions. The existing Resume action passes `human_resume` intent and instructions to re-observe operator changes; it remains an explicit continuation.
- Exposes `patch_file(path, old_text, new_text)` for a single literal replacement. Patch inputs are limited to 8 KiB per side and the resulting file to 64 KiB; ambiguous matches are rejected. The specialized `run_blob_orders(date, endpoint="")` tool is available only when selected in that bot?s tool libraries.
- Batches streamed text for up to 75 ms or 4,000 characters, flushing before tool, telemetry, final, and error events. The action iterator is fully drained before returning a tool result so authorization cleanup and timing events finish in order.
- Records per-model-call duration, time to first text/reasoning/tool-argument output, reported input/output tokens, and outcome through Microsoft SDK middleware. Missing usage is `null`, not an estimate. The tested SDK minimums are core 1.20 and OpenAI integration 1.15.

The backend now shares in-flight computer inspections and reuses Docker inspection results for up to two seconds. Cache keys include computer identity, generation, and persisted lifecycle state. Caller mutations do not modify cached reports, repeated observations produce one health event, and lifecycle changes force a fresh inspection. Local Windows status and Azure control-plane reports are not cached.

Immediately auto-approved shell/file mutations skip the second context observation only when an expected revision and a checked mutation endpoint are available. Manual approvals, actions that waited (including approvals enabled while pending), saved rules, browser/connector actions, and unguarded paths retain the existing behavior. Final claims, current Autopilot revision, argument digest, grants, generation, human-control state, and sandbox revision enforcement remain in place.

### Using the maintained ETL

The built-in ETL tool and frontend instruction presets have been retired. This workflow is a demo, not an application feature. The standalone [sample script](usecases/blob_orders.py) and [manual playbook](usecases/azure-blob-etl-playbook.md) remain outside the installed packages. Existing custom instructions remain user-owned; the former instruction marker does not enable a tool.

### Timing and verification

Durable `run.metrics` events expose these categories without prompts, tool arguments, URLs, or credentials:

| Category | Measurements |
| --- | --- |
| `model.call` | Call number, duration, time to first output, provider-reported input/output tokens, completion or exception type |
| `action.timing` | Action ID, context observation count/time, execution time (including checked sandbox dispatch) |
| `event.persistence` | Count and cumulative persistence time for adapter frames/captures; excludes other writers and the metrics event itself |

These metrics describe intervals with different scopes; they are not an additive accounting of every millisecond of a run. Model stream duration includes client processing/backpressure and excludes agent tool execution. An interrupted provider stream records its error type even when usage is unavailable.

Deterministic tests demonstrate two workspace revision reads for an immediately approved checked shell action (previously three), and one text event for 345 rapid fragments before a tool boundary (previously 345). Tests also cover real SDK tool-loop metrics using mocked HTTP, historical greetings, explicit resume intent, ETL reuse/reset/credential errors, exact patches and stale-file rejection, revocation before dispatch, manual waits, and shared health observations.

Live Azure/model ETL tasks have not been replayed. To compare models or claim an elapsed-time improvement, run the same dates, source data, workspace state, and valid credentials several times; compare median/p95 run time, model calls/tokens, tool count, context observations, and persistence time. Separate warm-workspace runs from resets and exclude credential failures from the success benchmark.
