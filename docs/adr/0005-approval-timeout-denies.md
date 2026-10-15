# Approval timeout means deny

## Status

Accepted

## Context

A missing human fails closed.

## Decision

Routines park work instead of waiting forever.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Leaving the approval pending would stall the bot indefinitely.
