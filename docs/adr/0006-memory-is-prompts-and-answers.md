# Memory stores prompts and final answers

## Status

Accepted

## Context

History stays small and framework-neutral.

## Decision

The model re-observes the sandbox on the next turn.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Replaying every tool result would bloat the transcript.
