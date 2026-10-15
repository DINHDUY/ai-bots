# The kernel runs inside the control process

## Status

Accepted

## Context

There is no RPC layer between admission and execution.

## Decision

A process lock allows one control process per database.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: A separate kernel service can wait until scale requires it.
