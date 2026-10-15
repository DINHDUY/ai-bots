# Explicit composition root and RunContext

## Status

Accepted

## Context

The control plane was grafting attributes onto EventStore and the streamer and probing them with hasattr.

## Decision

composition.build_services publishes a frozen Services graph. Adapters read streamer.context. StoreHooks replace attribute grafting. SandboxRouter is the one sandbox entry point. build_kernel(control=True) registers ufo.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Leaving the service locator in place hid the dependency graph from reviewers and from the type checker.
