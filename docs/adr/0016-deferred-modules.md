# Deferred repository modules and the counted baseline

## Status

Accepted

## Context

Foundation scope stops once new SQL is forced into repositories and the hot path no longer blocks the loop.

## Decision

cloud.py, channels.py, routines.py, groups.py, toolkit.py, workspaces.py, and windows.py stay on the LEGACY_SQL allowlist, as do modules that still contain SQL (runtime, event_store, app, approvals, lifecycle, control, computer, autopilot, tool_libraries, and the other names in tests/test_architecture.py). ASYNC_TRANSACTION_BASELINE is 163 and may only decrease. uv.lock is untracked because it requires Python 3.13 while packages require 3.11. Package version fields stay 0.1.0; git tag v0.3.0 is the reviewed baseline.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Migrating every module in the same change would mix a mechanical SQL move with the composition and connection work.
