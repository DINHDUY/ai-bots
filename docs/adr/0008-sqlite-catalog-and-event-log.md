# SQLite holds the catalog and the event log

## Status

Accepted

## Context

One file, transactions, and WAL reads are enough for a single writer.

## Decision

Multi-worker scale would move to Postgres.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: A network database is not required for this deployment.
