# One container per bot, reused across turns

## Status

Accepted

## Context

Follow-up prompts keep files, the browser, and the desktop.

## Decision

DockerSessionManager reattaches by session label and idle-sweeps unused containers.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: A fresh container per turn would drop workspace state.
