# ADR-0018: Optional shared workspace computer

## Status

Accepted

## Context

ADR-0002 and the architecture blueprint give each bot its own live computer. Bots in one workspace sometimes need the same files, browser, and desktop. That isolation is still the default.

## Decision

A workspace owner can switch computer mode from `per_bot` to `shared`. In shared mode, eligible bots (Docker sandbox or Azure cloud; not Microsoft UFO and not a paired Windows PC) run on one workspace-owned computer. Runs may overlap. Each individual action still takes the computer's existing action lock. Bot-level lifecycle is rejected; the owner manages the shared computer. Approvals, Autopilot, credentials, and transcripts stay on each bot.

## Consequences

The [Markdown workflow import](../025-markdown-workflow-import.md) is an explicit
creation flow that defaults its new workspace to shared Docker mode and shows
that choice in review. Ordinary workspace creation retains per-bot mode.

Overlapping runs share focus, tabs, files, and processes. The lock does not isolate one bot's work from another's. Switching mode is refused while a computer is still open, and nothing is migrated. See [023](../023-shared-workspace-computer.md). Per-bot mode is unchanged.
