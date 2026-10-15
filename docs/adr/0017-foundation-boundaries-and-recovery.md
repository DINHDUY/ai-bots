# ADR-0017: Foundation boundaries and recoverable operations

Status: accepted for the implemented slice; full remediation remains in progress.

## Context

The v0.3.0 review found runtime-wide service dependencies, product code in the core distribution, synchronous persistence in async paths, polling replay sockets, and encryption without a rotation path. Existing atomic receipts/events and conservative interruption recovery must survive changes to these boundaries.

## Decisions

- Keep one process and SQLite. Introduce bounded worker read/write APIs, cancellation settlement, and commit notifications. Read replay through a consistent read transaction. Legacy synchronous callers and `CatalogConnection` remain temporarily and are measured explicitly; this ADR does not claim exclusive worker ownership yet.
- Compose typed service collaborators in `composition.py`; consumers receive individual services/callbacks rather than the entire runtime. Keep the coordinator compatibility constructor during migration. Architecture checks reject whole-graph constructor dependencies and core imports of product packages.
- Move workspace messaging and UFO into `agentbot-product-tools`; keep demo workflows under `docs/usecases` outside installed application packages; inject tool factories and include implementation sources in manifest digests. Keep core imports usable without backend, Docker or model SDK installations. Some adapter connector/skill conventions remain to be generalized.
- Publish versioned event/snapshot envelopes through a side-effect-free schema exporter and generated frontend types. The SPA requires v2 and never owns automatic approval. Domain payload and HTTP schema completion are separate tracked work.
- Use per-bot commit wakeups as hints, never authoritative state. Register before catch-up, clear before reading, and reconcile periodically. Bound pages and sends; use durable cursors for recovery.
- Separate session signing from encryption purpose with HKDF and explicit versioned keyrings. Rotate offline in restartable batches under the same process lock. Retain legacy readers and old backup keys; fail closed for missing versions/keys.
- Track required worker progress and reject unsafe admission if workers stop/stall. Do not restart unknown external side effects. Enforce capacity inside run/computer reservation transactions.
- Back up the stopped database and blobs together. Restore into a new directory with a startup fence before copying. Provider identity reconciliation precedes activation.

## Alternatives

Postgres/distributed queues would introduce another operational model before capacity evidence requires one. An async SQLite wrapper alone would still leave indirect synchronous calls and transaction ownership unresolved. Multiple read connections may be useful later, but require measured contention and separate ownership rules.

Unbounded payload queues and a notification-only stream can lose authoritative state or memory bounds. Continuing SPA v1 fallback would preserve a second execution/approval behavior. Rewriting the raw gateway protocol is unnecessary to consolidate the authenticated SPA.

Changing the signing secret without a keyring/legacy reader would lose access to encrypted records. Online rotation and online database-only backup would complicate concurrent state/blob consistency; offline operations are appropriate for this single-process foundation.

## Consequences and closure

New boundaries have focused tests, but the remaining SQL allowlist, incomplete domain schemas and provider egress guarantees prevent closing the full plan. Startup readiness can lag liveness. Capacity defaults require load qualification. Key custody and backup permissions remain operator responsibilities. Versioned ciphertext is incompatible with older writers/readers unless the matching backup is restored.

See the [implementation ledger](../003-agent-control-implementation-status.md), [operations runbook](../021-foundation-operations.md), and [full acceptance plan](../020-foundation-remediation-plan.md). ADR-0014's database direction remains, while exclusive worker ownership is still pending. ADR-0015's local-only gate description is superseded by the authored CI workflow; hosted evidence remains pending.
