# Docker exec plus JSON stdout for in-container helpers

## Status

Accepted

## Context

Helpers expose no ports and are easy to test.

## Decision

Each call starts a process. The browser keeps state in a daemon.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: An open debug port inside the sandbox was rejected.
