# Sandbox termination must be verified

## Status

Accepted

## Context

A command that might still be running must not be treated as finished.

## Decision

GuardedSandbox.drain raises TerminationUnverified when UncertainSandbox.uncertain is set. Docker exposes that flag as a property.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Ignoring an unknown outcome would let the next run share a dirty sandbox.
