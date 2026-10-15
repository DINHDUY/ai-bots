# Local quality gates

Foundation update: the CI workflow and supported strict-project configuration in [ADR-0017](0017-foundation-boundaries-and-recovery.md) supersede the local-only and per-environment type-checking details below. The dated measurements below remain historical evidence.

## Status

Accepted

## Context

The repository has no git remote, so a hosted workflow cannot run yet.

## Decision

make check runs ruff, pyright, pytest, eslint, the frontend build, and vitest. pre-commit runs ruff, pyright, line endings, and tsc. tests/test_architecture.py guards the kernel import boundary, the SQL allowlist, and the async transaction baseline. Frontend lint uses a TypeScript 6 parser next to the app TypeScript 7 compiler because typescript-eslint does not accept TypeScript 7 yet. Pyright is strict for agentbot and agentbot-computer-agent. The backend and Windows companion use basic mode. These rules are warnings: reportAttributeAccessIssue, reportArgumentType, reportMissingImports, reportOptionalMemberAccess, reportCallIssue, reportOptionalSubscript, reportIndexIssue, reportGeneralTypeIssues, reportOperatorIssue, reportOptionalIterable, reportOptionalOperand.

## Consequences

See the architecture blueprint and docs/003-agent-control-implementation-status.md. Rejected alternative: Adding GitHub Actions or Azure Pipelines before a remote exists would not execute.
