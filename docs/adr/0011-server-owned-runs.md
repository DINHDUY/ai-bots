# The server owns runs

## Status

Accepted

## Context

Refresh and disconnect must not lose work or approvals.

## Decision

Runs, receipts, and events are durable and idempotent.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Client-owned execution cannot be recovered.
