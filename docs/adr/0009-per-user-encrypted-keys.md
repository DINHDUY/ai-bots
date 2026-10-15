# API keys are encrypted per user

## Status

Accepted

## Context

Tenants do not share process environment keys.

## Decision

Rotating AGENTBOT_SECRET makes stored keys unreadable.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Process-wide keys cannot attribute cost or isolate tenants.
