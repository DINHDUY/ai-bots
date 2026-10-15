# Async generator as the adapter boundary

## Status

Accepted

## Context

Adapters stream frames to FastAPI and the model SDKs.

## Decision

execute_step is an async generator. Callback SDKs use a queue bridge.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: A pull-based iterator would not match the async stack.
