# The UI opens one WebSocket per bot

## Status

Accepted

## Context

v1 frames do not carry a bot id.

## Decision

Many bots mean many sockets. v2 envelopes can carry ids later.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Multiplexing v1 frames on one socket would mix bots.
