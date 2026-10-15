# One desktop planner for host and container

## Status

Accepted

## Context

Validation lives in one module and is unit-tested without a display.

## Decision

The image build copies sandbox/desktop_plan.py.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: A second planner in the image would drift.
