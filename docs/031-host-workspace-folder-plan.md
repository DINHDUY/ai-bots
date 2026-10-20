# Host folder for the shared workspace computer

Status: proposed (H1-H4). Awaiting approval; nothing is implemented.

This plan lets a workspace owner back the shared Docker computer's `/workspace`
with a folder on the machine that runs Docker. Files the bots write appear on the
host, and files placed in the folder on the host appear in the computer. Without
this feature, `/workspace` lives inside the container and is destroyed when the
computer closes ([CMP-002, CMP-025](srs/004-computers-and-sandboxes.md)).

Decisions taken with the requester on 2026-10-20:

- The operator lists allowed host roots. The workspace owner picks one root and
  an optional subfolder in Workspace settings. Nobody types a free host path in
  the product UI.
- Only the shared workspace computer on the Docker provider can use a host
  folder. Per-bot computers, Azure computers, UFO, and paired Windows PCs cannot.
- The folder is always mounted read-write.

## Decisions

| Concern | Behavior |
| --- | --- |
| Operator config | `AGENTBOT_HOST_FOLDERS` names a JSON file of roots. If it is unset, the feature is off and the settings UI does not show it. A missing file, an invalid root, or a remote Docker engine fails startup. |
| Owner choice | `PUT /api/workspaces/{id}/computer` accepts `host_folder: {root_id, subpath}` or `null`. The existing rule applies: the change is rejected with `computers_active` unless the computer is closed. |
| Resolution | The server resolves the folder on save and again before every create, reset, and resume. The folder must stay under its root, and no component may be a symlink, junction, or other reparse point. |
| Exclusivity | No two workspaces may select the same folder, or one folder nested inside another. This is checked in the same transaction as the save. |
| Mount | One bind mount of the resolved folder at `/workspace`, read-write. All other hardening in CMP-004 is unchanged: uid 1000, all capabilities dropped, `no-new-privileges`, resource limits, no Docker socket. |
| Identity | The container carries a label with the folder digest. Reattach, reconcile, and resume refuse a container whose mount does not match the recorded folder. |
| Lifecycle | Close and reset remove the container but keep the host files. Hibernate and resume do not touch the folder. Nothing copies files between the container and the host. |
| Deletion | Deleting the workspace never deletes host files. The impact preview lists the folder as kept, and deletion releases its exclusivity reservation. |
| Files API | Path confinement, descriptor-relative no-follow opens, rejection of symlinks and special files, and protected-name rules all stay as they are. |

## Configuration

```json
{
  "roots": [
    {"id": "projects", "label": "Shared projects", "path": "C:\\work\\agent-projects"}
  ]
}
```

Startup rejects a root when any of the following is true:

- Its path is relative, missing, or not a directory, or its real path differs from the configured path (it is a link or junction).
- It is a filesystem or drive root, or a user's home directory itself.
- It contains, or sits inside, the control data directory, blob store, backups, or the Docker socket.
- Its `id` is duplicated or is not of the form `[a-z0-9-]{1,32}`.
- Roots are configured and `DOCKER_HOST` points at a remote engine (`tcp://` or `ssh://`). Bind sources are resolved on the daemon's machine, so only a local unix socket or named pipe qualifies.

A subpath must be relative. It may not contain `..`, a drive letter, a NUL
character, or an absolute prefix. Missing directories under the root are created
at save time, and each existing component is checked with `lstat` before
creation. On Windows, folders are compared after case-folding.

## H1 — Kernel mount support

- `DockerSessionManager.note_mount(session_id, source)`, which follows the
  `note_workspace` pattern. `_start` adds the bind mount and the
  `agentbot.host_folder` digest label only when a source was noted.
- Reattach in `_start`, `existing`, `resume`, and `reconcile` compares the
  label with the noted digest. On a mismatch it raises `SandboxError` and does not
  reuse the container.
- After start, an exec runs `test -w /workspace` as `agent`. If it fails, the
  container is removed and the error says how to grant uid 1000 write access
  (relevant for Linux hosts).
- The kernel only checks that the source is an absolute directory. Root policy
  stays in the product package, so the kernel stays independent of backend config.

## H2 — Config, persistence, and settings

- A new `agentbot_control/host_folders/` package holds config loading, path
  resolution, and the overlap check. It is built once in `compose_runtime`.
- Migration `023_host_folders.sql` adds `host_root_id`, `host_subpath`, and
  `host_resolved_key` to `workspace_computer_settings`. A partial unique index on
  `host_resolved_key` backs the equality check; the nesting check runs in the
  same transaction.
- `UpdateComputer` gains `host_folder`. It is rejected when the mode is not
  `shared` or the provider is not `docker`. Changing it bumps the settings
  revision and is covered by the existing receipt.
- `SharedLifecycle` resolves the folder again before `create`, `reset`, and
  `resume`. If the folder is gone, became a link, or its root was removed from
  config, the operation fails with `host_folder_unavailable` before any container
  is created. Startup reconcile marks a computer `failed` if its folder no longer
  resolves.
- `GET /api/workspaces/{id}/computer` adds `host_folder` (`root_id`, `label`,
  `subpath`) for every role. Only the owner also sees `host_roots`
  (`id`, `label`). Absolute host paths are never returned to the browser. The
  HTTP schemas and generated types are regenerated.

## H3 — Frontend and documentation

- `SharedComputerSettings.tsx` gets a host folder section: a root select, a
  subfolder field, and a clear action. It is disabled while the computer is open.
- The computer and Files panels show "Stored on host: <label>/<subpath>". The
  close and reset confirmations say that host files remain.
- The workspace deletion preview lists the kept host folder.
- Documentation updates:
  - [023](023-shared-workspace-computer.md) and a new runtime guide `032`.
  - ADR-0020, which records the trust decision below.
  - [021](021-foundation-operations.md): operator setup, Linux ownership, Docker Desktop file sharing.
  - The requirements: amend CMP-002, CMP-004, and CMP-025, and add requirements for configuration, resolution, exclusivity, and lifecycle.
  - `.env.example`.

## H4 — Validation

- Unit tests for resolution and config:
  - Path traversal, absolute and drive-letter subpaths, symlinks and junctions at the root and inside the subpath, and case-folded overlap.
  - Nested and equal selections across workspaces.
  - Missing roots, remote `DOCKER_HOST`, and forbidden roots.
- Settings and lifecycle tests:
  - The `computers_active` rule, receipts, revision conflicts, and non-shared or non-Docker rejection.
  - `host_folder_unavailable` before container creation, and reconcile marking a computer `failed`.
  - Deletion releasing the reservation.
- Real-Docker tests:
  - A host write is visible in the container, and a container write is visible on the host.
  - Close and reset keep the host files.
  - A host-created symlink is rejected by the Files API, and a mismatched mount label is refused on reattach.
  - Run on Windows with Docker Desktop. Linux ownership needs hosted CI or a Linux host.
- Browser test for the settings section at desktop and mobile widths.
- Measure the bash approval context check on a 2,000-file folder under Docker
  Desktop. Report the result; a slow check gets a follow-up proposal, not a
  silent change.
- Gates: `ruff`, size check, pytest, `make check`, `make check-docker`, `make docs-check`.

## Trust and limits (ADR-0020)

- Bots can read and change every file in the folder. Bash is not bound by
  protected-name rules, so a `.env` or key placed there can reach the model
  provider. Operators should point roots at dedicated folders, not at a home or
  credentials directory.
- Bot output on the host is untrusted. Scripts, git hooks, editor task files,
  and symlinks written by a bot can affect host tools that open the folder.
  Symlinks resolve inside the container, so they cannot expose host files to
  the bot. They can still mislead host tools that follow them.
- No operation rolls back host changes. Use version control or backups.
- An edit on the host between an approval and its dispatch changes the revision,
  so the action is refused with "action context changed". Folders over 2,000
  entries or 64 MiB have no workspace revision, so persistent shell rules do not
  apply to them (the existing fallback).
- Docker Desktop does not forward host inotify events. The watcher's two-second
  rescan picks up host edits, bounded at 10,000 entries.
- Out of scope: per-bot and Azure mounts, read-only mode, multiple mounts,
  SELinux relabel options, and choosing host paths from the browser.
