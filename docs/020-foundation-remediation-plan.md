# Foundation remediation plan

Status: implementation in progress. Baseline: `ac164dc`; working-tree changes and acceptance gaps are tracked in the [implementation ledger](003-agent-control-implementation-status.md). No F0-F7 milestone is declared complete without its full acceptance evidence.

This document consolidates the [v0.3.0 architecture review](code-reviews/v0.3.0-reviews.md), the seven findings from the subsequent workspace review, and the earlier remediation draft. It is an implementation plan, not evidence that the changes have been made. Existing foundation improvements remain part of the baseline.

The objective is a maintainable, measurable single-process platform with consistent execution guarantees. Keep the framework-independent kernel, server-owned runs, SQLite transaction boundaries, per-bot identities, and explicit recovery of uncertain outcomes. Implement the work in small, independently verified changes.

## Scope and findings

| ID | Finding to address | Implementation milestones | Completion evidence |
| --- | --- | --- | --- |
| R1 | Services still depend on the whole runtime; most composition fields are `Any`; routers and callbacks obscure dependencies | F1, F2 | Typed composition, explicit consumer interfaces, import/dependency checks, service tests without constructing the entire runtime |
| R2 | Synchronous SQLite access remains in async paths; replay reads acquire write transactions; every event socket polls at 100 ms | F4, F6 | Worker-owned persistence, read transaction discipline, commit notifications, cancellation/race tests, recorded concurrency results |
| R3 | Docker, Azure, and Windows have different containment guarantees; unattended actions need resource-level restrictions | F3 | Provider-specific trust model, enforced network policy, dispatch fencing, real network tests, verified desktop limits |
| R4 | Internal errors and API/event payloads lack stable typed contracts; scheduling depends on error wording | F2, F5, F6 | Domain error codes, complete HTTP/event schemas, generated wire types, compatibility tests, one SPA protocol |
| R5 | Gates are local; dependency installation and Python compatibility are not reproducible; warnings mask type defects | F0, F1, F2 | Clean locked installs, automated required checks, strict public contracts, required integration execution |
| R6 | Metrics and diagnostics exist, but worker readiness, operational alerting, and key rotation are incomplete | F3, F7 | Supervised workers, readiness tests, bounded-cardinality metrics, restore drill, all encrypted records rotatable |
| R7 | Large modules mix responsibilities; application tools live in the core package; current architecture docs conflict | F0, F1, F5, F7 | Responsibility-based decomposition, portable core, accurate capability/status documentation and ADRs |

Additional concerns from the earlier review are explicitly included: login/registration throttling in F3, Chromium isolation review in F3, distribution dependencies in F1, legacy protocol retirement in F6, frontend Fast Refresh warnings in F5, and package/release version consistency in F7.

### Verified baseline

Measurements below describe `ac164dc`, not future targets. Counts were obtained by reading the code and using Python AST inspection; the reusable `scripts/arch_metrics.py --revision ac164dc` now reproduces the baseline without changing the working tree. Working-tree measurements are recorded separately.

| Area | Baseline | Target |
| --- | --- | --- |
| Composition | 20 of 21 `Services` fields are `Any`; 10 subsystem constructors accept `runtime` | Concrete types or narrow protocols on all service fields; no subsystem accepts the coordinator or the whole service graph |
| Persistence | 160 synchronous transaction blocks inside async functions; architecture ceiling is 163; 25 modules are on the SQL allowlist | No direct or indirect blocking database access from the event loop; business SQL owned by repositories |
| Replay | Per-bot event sockets poll at 100 ms; `events()` uses `BEGIN IMMEDIATE` | Event-driven delivery, read-only replay transactions, bounded reconciliation and permission checks |
| Quality | Local Ruff/Pyright/pytest/frontend gates exist; no hosted workflow | Repeatable local and CI gates, required Docker job, visible platform-specific integration evidence |
| Packaging | Packages declare Python >=3.11; untracked `uv.lock` declares >=3.13 | One tested support matrix and compatible lock strategy; separate qualified Python 3.11 UFO environment retained |
| Size | `channels.py` 1,947 lines; `cloud.py` 1,579; `runtime.py` 891; `WorkspaceCenter.tsx` 1,860, including blank lines | Separate domain, transport, orchestration, and presentation responsibilities; file size is a review signal |
| Security | Local Docker default bridge; Azure blocks private/metadata destinations; paired Windows uses a real user session | Documented and tested guarantees per provider, with resource-scoped unattended policy |
| Operations | Run timing events, diagnostics, and backup guidance exist; `/health` returns a static status | Worker-aware readiness, actionable metrics/alerts, practiced recovery, versioned key rotation |
| Verification | Workspace review: 392 Python tests passed; 10 Docker/desktop tests deselected | Preserve regression behavior and add targeted failure, compatibility, network, and load coverage |
| Documentation | README and ADRs reflect some foundation work; blueprint still labels implemented capabilities as planned | One current status source, clear historical documents, checked links and generated contract references |

The Python test result is historical review evidence. Frontend, live-provider, Azure, and interactive-desktop validation were not performed by that review.

## Delivery order and ownership

One engineer may execute the work sequentially. Independent workstreams below describe scheduling opportunities, not a requirement for multiple agents or teams. Assign a named implementation owner and reviewer when each milestone starts.

| Milestone | Deliverable | Dependencies | Rough effort |
| --- | --- | --- | --- |
| F0 | Reproducible installs, quality gates, baseline measurements, documentation reconciliation | None | 3-5 engineer-days |
| F1 | Portable core and explicit tool/provider extension boundaries | F0; coordinate public contracts with F2 | 3-5 days |
| F2 | Typed services, domain errors, explicit composition | F0; integrate F1 contract changes before closure | 5-8 days |
| F3 | Provider security policies, auth throttling, complete key rotation | F0; vault integration uses the F4 database API | 8-12 days |
| F4 | Consistent database worker ownership and repository migration | F0 for worker API; F2 interfaces for remaining service migrations | 6-10 days |
| F5 | HTTP/event contracts and responsibility-based decomposition | F2; coordinate repository boundaries with F4 | 5-8 days |
| F6 | Commit-driven subscriptions and SPA v2 consolidation | F4 notification boundary and F5 event schemas | 3-5 days |
| F7 | Operational supervision, recovery drills, release assessment | Start diagnostics after F0; close after F1-F6 | 5-8 days |

Total planning range: approximately 38-61 engineer-days, plus access/setup time for real Azure and Windows validation. Re-estimate after F0 and the first service/database slice. These are effort estimates, not a committed delivery date.

Recommended sequence:

1. Complete F0. Start worker/readiness instrumentation early so subsequent changes have observable results.
2. Establish F2 interfaces and the F4 database API. Start F3 threat-model, authentication, and network work alongside them where files do not overlap.
3. Complete F1 tool/provider separation, then migrate remaining services and repositories using the established patterns.
4. Finish F3 vault/network integration and F5 contracts/decomposition.
5. Complete F6 protocol/subscription migration and F7 acceptance drills.

Recommend limiting additional execution features while the foundation work is active. Before expanding unattended or externally reachable deployments, require the relevant F3 security checks, F4 concurrency checks, and F7 readiness/restore checks. Existing compatibility paths may remain during migration with explicit removal conditions.

## Invariants preserved throughout

- A command receipt, its domain state change, and related durable events commit atomically.
- Only one active run and authorized writer may own a bot/computer at a time. Human-control leases and computer generations remain authoritative.
- Approvals bind exact arguments and current permissions; expiration, revocation, stale targets, and missing decisions prevent dispatch.
- A browser disconnect does not stop server-owned execution. A process restart interrupts unfinished execution; it does not silently replay unknown side effects.
- Foreign resources remain inaccessible through HTTP, sockets, files, captures, and diagnostics. Permission revocation applies to existing subscriptions.
- Kernel contracts do not depend on control-plane users, authorization storage, or product services.
- Secrets are excluded from responses, logs, event data, schema examples, and test artifacts.
- Event delivery and compatibility changes cannot re-enable browser-owned automatic approval.

## F0 — Reproducible verification and an accurate baseline

Primary files: `pyproject.toml`, package manifests, `Makefile`, `.pre-commit-config.yaml`, frontend lock/configuration, proposed `.github/workflows/check.yml`, proposed `scripts/arch_metrics.py`, and documentation checks.

### Work

1. Define and test the supported Python/Node matrix. Preserve Python 3.11 for the qualified UFO companion. Resolve SDK requirements before changing advertised Python support; do not silently raise it to match the current untracked lock.
2. Choose a documented Python lock workflow covering local packages and optional provider dependencies. A uv workspace is the preferred starting point if it resolves on the supported matrix; regenerate its lock from compatible manifests. Keep the companion's qualified environment separately reproducible. Verify the frontend with `npm ci` and an explicit parser/compiler compatibility configuration.
3. Pin deployment artifacts: lock Python tools/dependencies, pin the sandbox's Playwright/browser installation, and record sandbox image digests. Retain a scheduled dependency/security update process.
4. Automate Ruff, Pyright, Python tests without Docker/interactive desktop, frontend lint/type checking/build/unit tests, and document checks. Use Ubuntu and Windows where applicable, with explicit shell/Makefile settings and dependency installation.
5. Add a dedicated Linux Docker job that builds the image and runs marked integration tests plus Playwright. Require at least one collected Docker test and fail on unexpected skips using a pytest hook or structured report; ordinary unit runs may intentionally deselect them. Live Azure and interactive Windows suites remain separately provisioned jobs with explicit evidence.
6. Use the existing remote if configured. Adding or publishing a remote, enabling branch protection, and publishing releases are later implementation actions, not part of creating this plan. Local verification and workflow authoring can proceed before hosted execution is available.
7. Add AST-based metrics for dependency edges, untyped public boundaries, legacy SQL, and synchronous transaction sites. Do not interpret syntax counts as proof that synchronous helper calls are absent.
8. Reconcile the current blueprint with implementation status. Add a link checker and one machine-readable capability/status source for generated tables. Preserve dated reviews as historical evidence; fix their broken links without rewriting their findings.
9. Add a brief PR template covering behavior, verification, migration/rollback, and documentation impact. Ratchet existing type/lint findings using module-specific diagnostics; new public interfaces must fail on type errors.

### Acceptance

- Clean installs on the chosen support matrix produce no lock changes and pass the supported gates without relying on repository `pythonpath` to hide packaging errors.
- Missing optional SDKs give actionable errors; required dependency incompatibilities fail installation checks.
- A deliberately broken test/type contract fails CI. A missing sandbox image or unexpectedly skipped Docker test fails the required integration job.
- Baselines record source revision, tooling, hardware, workload, and metric definitions. Historical review numbers are not treated as current measurements.
- Current status tables agree and local links resolve. No document claims hosted CI is operational until a hosted run exists.

Documentation: update [README](../README.md), [implementation status](003-agent-control-implementation-status.md), [blueprint](architecture-blueprint.md), and relevant quality-gate ADRs as the work lands.

## F1 — Portable kernel and explicit extensions

Primary files: `agentbot/interfaces.py`, `events.py`, `kernel.py`, `gateway/app.py`, adapters, tools, package manifests, host-bundle and sandbox build scripts.

### Work

1. Move daily-orders business logic out of `agentbot/workflows` and `tools/blob.py` into a control-plane product-tools module or a small dedicated tool package. Inject tools through a generic binding contract; adapters must not import the control plane.
2. Separate generic conversation/yield contracts from workspace-channel tool definitions. Product-specific messaging belongs beside the channel service; adapters consume schemas, invocation callbacks, and context providers.
3. Move UFO adapter registration to control-plane composition. Keep Windows protocol/model types importable on Linux and native desktop execution in the Windows companion. Place the adapter in the control plane or a dedicated integration package to avoid introducing a companion-to-core dependency cycle.
4. Distinguish the minimal sandbox factory (`get_or_create`, `close`) from lifecycle, revision, file, and cancellation capabilities. Use explicit protocols and factories. Preserve the guarded dispatcher and uncertain-outcome checks for every provider.
5. Replace product-specific/untyped `RunContext` callbacks with typed tool bindings and explicit execution/yield interfaces. Preserve tool schema, approval requirement, binding revision, manifest identity, and authorization checks; do not merge semantically different operations into an unvalidated callback dictionary.
6. Make core imports independent of FastAPI, Docker, and provider SDKs. Put gateway/provider requirements behind documented extras or separate distributions. A zero-dependency core is desirable only where contracts permit it; portability is the acceptance criterion.
7. Move kernel construction out of the web gateway dependency path. Explicitly install the required extras in each host, backend, gateway, and developer entry point. Console scripts cannot declare their own dependency sets.
8. Update tool manifests/digests when handler locations change. Drain or finish pinned runs before deployment, or retain compatible handlers; never silently execute a new handler under an old manifest digest.

### Acceptance

- Install a built core wheel into a clean environment without provider/web extras and import kernel/contracts/registry successfully with isolated Python.
- A separate clean installation with selected extras runs each supported entry point. No test relies on a modified `PYTHONPATH` to simulate installation.
- Kernel import checks reject control-plane/product imports. The existing kernel-to-control-plane guard remains.
- Scripted tests exercise Microsoft, Anthropic, and UFO adapter contracts, including denial, cancellation, communication-only runs, and tool binding drift.
- Docker planner packaging, the ETL acceptance scenario, and the cloud host wheel bundle still work after moves.

Documentation: blueprint dependency/extension diagrams, package install instructions, [CLI runtime design](cli-runtimes.md), [Cursor adapter design](cursor-sdk-adapter.md), and a dependency-boundary ADR. These documents are updated for compatibility; implementing new CLI adapters is outside this remediation.

## F2 — Typed composition and domain behavior

Primary files: `composition.py`, `runtime.py`, `hooks.py`, `authorization.py`, service modules, proposed `ports.py` and domain error definitions.

### Work

1. Define narrow interfaces from each consumer's needs: run admission, workspace authorization, computer lifecycle, action dispatch, event persistence, tool access, clocks, and identifiers.
2. Construct the graph in `build_services`. Inject individual collaborators into the coordinator and services; do not replace `Runtime(self)` with `Service(services)`. Split query/policy and coordination dependencies where needed to remove construction cycles.
3. Remove `catalog.access` attribute grafting and configure hooks/capabilities explicitly. Type all hook methods actually used, including tool-validity and admission operations.
4. Migrate the 10 runtime-dependent constructors one service at a time. Retain provider-specific behavior behind declared capabilities rather than chains of `__getattr__` routers. Keep intentional proxy behavior only with an explicit tested dispatch surface.
5. Introduce domain error codes such as busy, permission revoked, computer unavailable, human control held, and outcome unknown. Translate them into HTTP status/user messages at the boundary. Replace channel/routine substring matching with structured retry/wait/terminal classifications.
6. Centralize permitted run, action, approval, and computer transitions. Keep database compare-and-set constraints and exact approval/lease validation; avoid parallel state machines in routes.
7. Configure real supported Pyright strict settings for migrated modules and remove diagnostic downgrades from those boundaries. Use typed fakes and contract tests; reduce legacy warnings by module without casting everything to `Any`.

### Acceptance

- All `Services` fields and public service collaborators are typed. No subsystem constructor accepts the coordinator or the complete service graph.
- Representative approval, channel, and lifecycle services can be tested with their declared collaborators alone.
- Rewording an error message does not change scheduler behavior. Each domain error has an explicit mapping and unrecognized errors are handled conservatively.
- Imports and type checks reject accidental dependency cycles or invalid callbacks.
- Existing behavioral regression checks remain meaningful; fixture changes are expected. Changes to assertions require a documented behavior change, not a blanket ban on test edits.

Documentation: composition diagram, service ownership table, transition/error contracts, and ADR-0013 follow-up. Supersede only decisions actually changed.

## F3 — Provider-specific containment, authentication, and keys

Primary files: Docker manager/image, Azure host/bootstrap and bridge, Windows companion/control paths, `approvals.py`, `autopilot.py`, `auth.py`, `store.py`, `policies.py`, migrations, and operator/UI settings.

### F3a: Execution and resource policy

1. Specify guarantees for local Docker, Azure-hosted containers, and a paired Windows desktop. Include filesystem persistence, reachable networks, host privileges, computer ownership, human interaction, and process termination. Document the trusted Azure host's dedicated workspace mount separately from unrestricted host mounts.
2. Define versioned per-bot/workspace resource policies: allowed tools, destinations/resources, and unattended eligibility. Enforce them at dispatch for user prompts, routines, channels, skills, and connectors. Bind approvals to policy revisions and invalidate undispatched actions when policy or permission changes.
3. Route Docker workload traffic through a maintained egress enforcement component on isolated networks. Prevent direct bypass even if a command ignores proxy environment variables. Choose per-session versus shared proxy deployment based on isolation and resource measurements; do not introduce a custom minimal CONNECT proxy.
4. Validate destination names and resolved addresses, including redirects, IPv4/IPv6, rebinding, literal IPs, and alternate protocols. Default-deny metadata/link-local, loopback/host, private infrastructure, and other tenants. Ensure DNS resolution itself cannot bypass the intended policy. An isolated development Azurite exception must identify the exact test service and never become a broad production private-network exception.
5. Preserve Azure's existing network fences and verified startup. Apply workload destination policy through an appropriate proxy/firewall; NSGs alone cannot implement hostname allowlists. Keep trusted host enrollment/identity traffic separate from workload traffic.
6. Treat Windows as a user-controlled desktop, not equivalent to container containment. Require local consent and current scope, preserve immediate input/stop fencing, and report unavailable isolation. Permit unattended actions only when their required controls can be enforced; unsupported guarantees must disable those actions.
7. Scope server-side connector/provider clients separately. A sandbox proxy does not constrain backend HTTP calls. Retain credential/resource binding, endpoint validation, and revocation in those clients.
8. Review Chromium's `--no-sandbox` setting under the actual unprivileged container configuration. Enable its sandbox if compatible; otherwise document the tested compensating boundary and residual exposure. Stronger VM isolation remains a future option for a different threat model.
9. Add deployment-wide and per-user limits for active runs/computers and pending work. Existing per-bot exclusivity, routine limits, and container CPU/memory limits remain; reject excess admission predictably rather than allowing unbounded resource use.

Acceptance: real container tests cover permitted destinations, blocked metadata/private/peer access, direct network bypass, redirects/DNS changes, policy disable/revocation races, and proxy failure. Azure and interactive Windows require provider-specific verification evidence before their unattended policies are declared supported.

### F3b: Authentication hardening

- Add bounded per-account and per-source login backoff and registration throttling, using trusted proxy configuration for client IPs.
- Avoid permanent account lockout as an attacker-controlled denial of service. Use uniform authentication failures, bounded state retention, and `Retry-After`.
- Offload password hashing/verification to a bounded CPU executor, outside the database writer. Limit concurrent expensive attempts.
- Test concurrent attempts, backoff expiry, successful-login behavior, registration limits, proxy spoofing, and event-loop responsiveness.

### F3c: Versioned encryption and rotation

1. Inventory every `Catalog.seal/unseal` and `Policies.seal/unseal` consumer. Cover model keys, connector credentials, webhook secrets, sealed action arguments, approval-policy scopes, cloud continuation material, and any other encrypted records found.
2. Introduce a versioned envelope/key identifier with legacy version-0 support. Separate encryption and session-signing purposes; use a reviewed derivation/keyring design such as HKDF with explicit purpose labels and stable persisted context.
3. Add an offline/drained rotation command with dry-run, resumable progress, verification, and recovery. Read old/new material through protected configuration or file input rather than command-line plaintext. Integrate writes through F4's persistence boundary.
4. During migration read legacy/current versions and write the current version. Retain old keys until all active records and retained backups have a documented recovery path. Unknown key versions fail closed with an actionable operator error.
5. Specify session-cookie behavior during signing-key rotation: either controlled invalidation or a bounded previous-key grace period. Encryption rotation must not accidentally destroy access to unrelated encrypted data.

Acceptance: rotate a restored database containing every encrypted record type; verify reads, connector/webhook use, policy/action recovery, and cloud continuation handling. Interrupt rotation and resume it. Verify no secret reaches logs/output and document rollback and backup-key retention.

Documentation: provider security matrix, Autopilot policy prerequisites, [Azure runbook](010-agent-control-azure-runtime.md), [Windows runbook](007-agent-control-ufo-runtime.md), ETL configuration guidance, authentication/rotation operations, and updated security ADRs.

## F4 — Database ownership and transaction discipline

Primary files: `db.py`, `store.py`, `event_store.py`, repositories, runtime/approval/automation services, HTTP/socket authorization, file/capture services.

### Work

1. Make database connection ownership explicit. Initially use one dedicated worker that owns the connection and executes bounded read/write jobs. Remove event-loop access to raw connections and locks, including indirect synchronous helpers called by async routes.
2. Add read and write APIs. Writes use explicit atomic transactions; read-only replay and snapshots do not acquire `BEGIN IMMEDIATE`. Multi-query snapshots use a consistent read transaction. Introduce additional read connections only if measured contention warrants them, with separate ownership, configured pragmas, and an ADR.
3. Move business SQL into aggregate repositories. Migrate run admission/receipts, approvals/dispatch checks, replay/snapshots/auth, then automation and remaining services. The database layer owns migrations; the event-store facade orchestrates typed repository operations.
4. Preserve multi-repository atomicity with a unit of work: state, receipt, event, and transactional projections succeed or roll back together. Never split approval validation and authorization into independently committing calls.
5. Define cancellation semantics. Once a job starts, cancelling the await does not imply rollback. Reconcile its committed outcome using durable receipts/state before returning or launching work. Prevent abandoned jobs from leaving approvals or admission in an ambiguous state.
6. Return committed results to the event loop before resolving futures or creating run tasks. Worker callbacks must not manipulate asyncio objects directly or await the loop while holding a transaction.
7. Expose a post-commit notification boundary for F6; failed notification must never invalidate an already committed command. Keep filesystem/network work outside database transactions.
8. Retire `CatalogConnection`, duplicated transaction wrappers, direct executor access, and legacy SQL access after callers migrate. Include capture/file cleanup loops and startup/shutdown paths in the ownership audit.
9. Bound the database queue and report overload with a typed, retryable response before unbounded work accumulates.

### Acceptance

- The SQL allowlist is empty for business modules; direct and indirect database access is verified to occur on the owning worker using an instrumented connection/factory.
- The async transaction syntax count reaches zero, accompanied by runtime tests proving sync helpers no longer block the loop.
- Read-only replay never starts a write transaction; snapshots cannot combine events/state from different read snapshots.
- Duplicate concurrent commands, approval/stop races, cancellation during commit, rollback, worker failure, and shutdown drain preserve invariants.
- A slow database operation does not block independent websocket/task processing. Load measurements meet the workload targets below.
- Fresh, upgraded, and restored databases retain migration history, foreign keys, receipts, and encrypted values.

Documentation: database ownership and unit-of-work ADR, update ADR-0014/0016 status where appropriate, repository boundaries, performance evidence, and backup guidance.

## F5 — Complete contracts and decompose mixed responsibilities

Primary files: backend schemas/routes/domain services, frontend `src/api`, session models, `WorkspaceCenter.tsx`, `ChannelPanel.tsx`, and provider settings components.

### Work

1. Define request and response models for actual HTTP routes. FastAPI cannot infer complete bodies/responses from arbitrary `Request` parsing and untyped dictionaries. Separate internal models from safe public schemas.
2. Define discriminated, versioned WebSocket event/snapshot schemas, including domain errors, observations, approval decisions, capture metadata, and nullable/unknown states. Export these as a schema artifact; HTTP OpenAPI alone does not cover WebSockets.
3. Generate TypeScript wire types for both HTTP and events. Retain intentional UI view models. Validate external event envelopes at runtime; unsupported/malformed data triggers a controlled resync or compatibility error.
4. Add deterministic schema export without application startup, production credentials, database creation, background workers, or cloud calls. CI regenerates artifacts and checks for drift.
5. Decompose by responsibility: channel membership/thread policy, delivery/continuations, tools, and routes; cloud bindings, operations, reconciliation, and routes; coordinator, guarded dispatch, streamer, and recovery; workspace settings shell and individual feature panels/hooks.
6. Keep a clear owner for React Query server data, durable session state, and local UI preferences. Share query keys and invalidation rules so mutations and replay cannot leave contradictory UI state.
7. Move non-component exports out of React component modules where needed, then make the relevant Fast Refresh rule enforceable.
8. Review large files after decomposition. Do not manufacture thin wrappers or arbitrary packages solely to meet a line limit; assess dependency direction, cohesive behavior, and independent testability.

### Acceptance

- Generated HTTP/event schemas match actual serialized fixtures, including errors, permissions, unknown outcomes, and historical supported events.
- Incompatible contract changes fail generation/consumer checks or require an explicit version migration.
- Export works in an isolated process without side effects or secrets.
- Frontend component/reducer tests and relevant Playwright flows cover reconnect, approval, sharing, routines, files, captures, and provider settings.
- Extracted service modules have focused tests and declared dependencies; the settings shell does not implement every feature's API logic.
- Targeted frontend development checks produce no Fast Refresh warnings from the affected components.

Documentation: public API/event contracts, [frontend guide](009-agent-control-frontend.md), new module map, and relevant cloud/channel runtime links.

## F6 — Event-driven delivery and one SPA protocol

Primary files: `transport.py`, event-store notification integration, authorization, `sessionConnection.ts`, `botSocket.ts`, `v2.ts`, `reduce.ts`, and session stores.

### Work

1. Implement a per-bot commit notifier after F4 transactions. The database remains the source of truth; notifications carry identity/watermarks and prompt consumers to read committed events.
2. Make subscription setup race-safe: register interest, read/catch up from a cursor, and use a generation/watermark check before waiting. Test commits between each step. Cross from the database worker with a thread-safe loop handoff.
3. Replace 100 ms event queries with notification-driven catch-up. Coalesce notifications and use bounded queues/pages/send deadlines. Retain a low-frequency reconciliation/heartbeat path for lost notifications and an explicit authorization-recheck deadline.
4. Preserve resync at retention gaps, stable event identity, sequence ordering, and snapshots. Disconnect/resync slow consumers rather than blocking a run or retaining unbounded per-client payloads.
5. Recheck current permissions before sending protected data and on permission/session invalidation. Define a bounded idle revocation delay, initially no more than five seconds; revocation events should wake affected subscriptions promptly.
6. Migrate the authenticated SPA fully to the v2 command/replay contract. Keep useful pure presentation reducers while removing v1 transport behavior and page-local auto-approval. Preserve ambiguous-request IDs for explicit retries; reconnect never queues execution automatically.
7. Inventory legacy consumers before removing the control-plane compatibility socket. Document a deprecation window and an intentional unsupported-client response. The standalone raw gateway retains its own dev/test protocol and cannot import control-plane compatibility code.
8. Retain one subscription per observed bot initially. Multiplexing is optional after measurement and requires its own per-bot cursor/authorization design; it is not necessary to retire v1.

### Acceptance

- An idle subscriber performs no high-frequency event polling. The configured reconciliation and permission checks are measurable and bounded.
- Commit-before-subscribe, commit-during-catch-up, dropped notification, sequence gap, retention pruning, revocation, slow client, and restart tests produce no missing authoritative state.
- Slow or disconnected observers cannot delay sandbox execution or cause a command to execute twice.
- The SPA runs one documented protocol with no browser-owned approval fallback; raw gateway tests still pass.
- Record connection count, database read rate, delivery latency, and queue/memory behavior before and after the change.

Documentation: transport/reconnect contract, raw-versus-authenticated gateway guidance, compatibility schedule, and ADR-0010 rationale if connection topology changes.

## F7 — Operational supervision, recovery, and closure

Primary files: application lifespan, runtime/background loops, health/diagnostic endpoints, logging/metrics support, deployment instructions, release manifests.

### Work

1. Supervise required background tasks: run coordination, computer monitoring, control leases, routines, channels, capture cleanup, and configured cloud reconciliation. Track last successful progress and task termination; a task existing is not sufficient evidence that it is healthy.
2. Keep liveness separate from readiness. Readiness requires successful migrations/recovery, responsive persistence, an accepting coordinator, and healthy enabled workers. Optional provider outages should degrade the relevant capability rather than unnecessarily disabling unrelated bots. Protect detailed diagnostics.
3. Surface dead/stalled workers, fail admission where correctness depends on them, and implement bounded recovery where safe. A supervisor must not replay uncertain side effects or restart against an un-drained writer.
4. Export aggregate metrics for active runs, approval age, event delivery lag, worker health, database queue/latency, storage/quota, denied egress, and unverified termination. Use low-cardinality labels such as provider/status; keep bot/run/user identifiers in structured logs, not metric labels.
5. Use ordinary process counters/histograms for observations and repository-derived gauges for durable state. Specify restart semantics rather than persisting every metric in the database.
6. Emit structured correlated logs using request/run/bot/action identifiers, including executor and bridge boundaries. Redact sensitive payloads and test exception paths. Configure alerts and write the investigation steps for each alert.
7. Define retention and cleanup for events, captures, files, receipts, completed jobs, and host journals. Preserve receipt deduplication for the documented retry window and never prune active/uncertain execution evidence.
8. Practice a consistent backup/restore: drain/fence writers as needed, back up SQLite through supported methods, include blobs and required keys, and retain deployment/workspace metadata. An online database backup alone is not a consistent database-plus-blob snapshot.
9. Restore into an isolated environment that cannot reconnect to production computers. Verify credentials, permissions, events, files/captures, interrupted runs, and provider identities. Measure recovery time and document the recoverable backup interval.
10. Document upgrade/downgrade compatibility and package/image/protocol versioning. Produce a release candidate/changelog and a new assessment after gates pass. Choose the actual release version then; tagging, pushing, and deployment are explicit release steps.

### Acceptance

- Kill or stall each required worker in tests: readiness changes, diagnostics identify it, and dependent work is safely rejected or recovered.
- Database unavailability, disk pressure, provider disconnect, and uncertain termination produce actionable, redacted signals.
- Operators can trace a run across request, coordinator, sandbox/bridge, and completion records without exposing secrets.
- A restore/rotation drill demonstrates all protected data and execution metadata remain usable; no production resource is accidentally adopted.
- The final assessment records evidence for R1-R7, supported provider/environment combinations, and any explicitly deferred residual risk. Do not mark a milestone complete solely because tests unrelated to its risk passed.

Documentation: [backend operations](016-agent-control-backend-runtime.md), provider runbooks, dashboards/alerts, retention and backup policy, meaningful ADR alternatives/consequences, changelog, and final review.

## Workload and verification plan

F0 records a reproducible workload and reference hardware before performance claims are made. The initial proposed profile is 10 scripted active bots emitting two observation frames per second each, 100 authenticated event subscriptions, periodic snapshots, and concurrent approvals/stops. Model and cloud latency are measured separately. Use one minute of warm-up and five minutes of measurement on a recorded machine.

Initial acceptance targets for that profile are p95 event-loop lag below 50 ms and p95 commit-to-local-subscriber delivery below 250 ms. Confirm these targets against intended deployment capacity in F0; any revision needs a documented capacity rationale. Functional concurrency/race checks run in CI; stable-machine performance runs produce release evidence without flaky shared-runner timing gates.

| Layer | Required verification |
| --- | --- |
| Core/services | Existing regression suites plus typed extension, state transition, approval/cancellation, and dependency tests |
| Persistence | Worker ownership, read consistency, atomic receipts/events, overload, rollback, in-flight cancellation, migration and restore |
| Transport | Cursor race matrix, lost notifications, slow readers, revocation, historical events, protocol compatibility |
| Frontend | Wire generation, malformed/unknown events, session reducers, feature panels, responsive/reconnect/approval Playwright flows |
| Docker | Real network denial/bypass checks, image protocols, filesystem confinement, process draining, lifecycle, ETL |
| Windows | Qualified Python/native environment, scope/consent, local input stop, stale target, permit/lease expiry, uncertain outcomes |
| Azure | Isolated resource lifecycle, trusted host/workload traffic separation, network policy, identity/bridge fencing, recovery |
| Operations | Worker failure/stall, key rotation across all sealed fields, database-plus-blob restore, alerts/redaction, capacity limits |

Stress beyond the reference profile must show bounded admission/database/subscriber queues, a stable resource ceiling, and explicit overload behavior. Fix capacity limits based on those results. Per-bot containers and the single control process remain intentional constraints; a distributed queue/Postgres/microservice migration is a separate decision if required scale or availability cannot be met.

## Rollout, documentation, and completion

- Start each milestone with a concrete issue describing the invariant, affected modules, migration, and acceptance evidence. Keep mechanical moves separate from behavioral changes when practical.
- Make schema changes additive first. Roll out compatible readers before writers switch format, then remove compatibility after the documented window.
- Stage network policies and legacy-client retirement with explicit operator-visible state. Do not silently grant broader access or leave active runs on an incompatible policy.
- Rehearse persistence and encryption changes on copied data. Drain active runs for upgrades that alter handler digests, schemas, or dispatch semantics.
- Before each deployment retain a compatible image/package set and consistent backup. Roll back only to software that understands the current schema, otherwise restore the matching backup after stopping/fencing execution.
- Treat the implementation-status document as the current milestone ledger. Plans describe intended work; reviews describe dated evidence. Update architecture/runtime documents in the same change when their contracts change.
- Add ADRs for consequential choices, with alternatives and consequences. Preserve superseded decisions; do not require an ADR for every mechanical move or routine migration.
- Check links and generated artifacts automatically. Record documentation impact in reviews without forcing meaningless edits to unrelated documents.
- Close each R1-R7 row with test/benchmark/drill evidence and remaining limits. Keep unresolved work visible; changing a status word does not close an issue.

### First implementation slice

Begin with F0 installation/lock verification and gates, then implement one complete slice: typed replay repository -> worker-owned read -> versioned event fixture -> commit notification -> reconnect/revocation test. In parallel scheduling, prioritize F3 authentication/network design and F7 worker-health instrumentation. This validates the cross-cutting approach before migrating all services.

### Deferred architectural choices

Horizontal runtime scaling, Postgres, transparent resumption of interrupted tool loops, hardware-VM isolation, arbitrary third-party plugins, and a mandatory single multiplexed socket are not prerequisites for closing this review. Revisit them only against measured capacity, availability, or threat-model requirements, with separate designs and acceptance criteria.
