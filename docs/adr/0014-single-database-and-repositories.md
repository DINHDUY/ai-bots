# One database connection, repositories, and async offload

## Status

Accepted

## Context

Catalog and EventStore each opened the same SQLite file, and sync transactions inside async handlers blocked the event loop.

## Decision

Database owns the connection, the lock, migrations (including 000_catalog.sql), and Database.run on a single worker thread. EventStore.offload uses that worker. repositories/ holds SQL for events, receipts, approvals, runs, computers, and workspaces. Catalog.seal and unseal are the public secret API.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Two connections could observe different locks and pragmas. Moving every module in one change was rejected; the rest stay on the allowlist.
