# Import an agent Markdown workflow

Choose **Workspace settings → Import workflow** to create a new workspace from a
set of local agent Markdown files. Each selected file becomes one bot. Its body,
after removing leading YAML frontmatter, becomes that bot's instructions.

The workspace starts in **shared Docker computer** mode with automatic
collaboration enabled. Every imported bot joins the existing **Bot channel** and
has its messaging tools selected. Importing does not start a model task or create
a running computer.

## Import and review

1. Enter a workspace name and select or drop the `.md` files. `.agent.md` filenames
   are also supported. Replace or remove files with encoding/size errors.
2. Select the common framework, an existing API key, and a model. Microsoft and
   Anthropic are supported. Open **Computer tools** to change the standard tool
   selection; messaging remains enabled. External connections and taught tasks
   can be configured after import.
3. Choose **Preview agents**. Review names, public purposes, exact instruction
   bodies, warnings, and runtime settings. Names default to YAML `name`, then the
   filename stem. Public purposes default to YAML `description` and are visible
   to workspace members. Private instructions are not copied into the directory.
4. Correct duplicate names or invalid settings. Each bot can override the common
   runtime. Preview again after any file or setting changes.
5. Choose **Import workflow**. All bots, the workspace, shared-computer settings,
   and channel membership are saved together. An invalid file cannot leave a
   partially imported workspace.
6. Open **Bot channel** to give a bot a task. Communication-only exchanges can run
   immediately with valid model credentials. For computer work, choose **Set up
   shared computer** and create the workspace computer through its existing controls.

All bots have the importing user's ownership. Computer actions retain their
normal approvals and human-control rules. Autopilot is not enabled by import.
Shared runs use the same files, browser tabs, desktop, and processes; individual
computer actions are serialized. See the
[shared-computer guide](023-shared-workspace-computer.md) and
[channel runtime](015-agent-control-workspace-channel-runtime.md).

Ordinary workspace creation retains per-bot computers and disabled collaboration.
Bots created manually later retain the existing explicit channel-enrollment flow.
Changing an imported workspace's computer mode uses existing workspace settings.
Close its shared computer and finish a bot's active task before deleting that bot.

## Supported files and limits

Files must contain valid UTF-8. An optional initial BOM is removed. A first line
of `---` opens YAML frontmatter, closed by a line of `---` or `...`. The importer
removes the delimiters, metadata, and closing delimiter's line terminator. All
remaining characters are retained, including blank lines, indentation, trailing
spaces, and LF/CRLF line endings. Without frontmatter, the whole decoded file is
the instruction body. Later horizontal rules and fenced YAML stay in the body.

Only string `name` and `description` values suggest settings. Other frontmatter
fields, including tool/model names, hooks, permissions, and credentials, have no
configuration effect and are excluded from instructions. The review displays their
field names without their values. Empty metadata is allowed. Malformed YAML,
duplicate keys, aliases/anchors, unsupported tags, and excessive nesting are errors.
Recognizable TOML/JSON headers require conversion to YAML before import.

| Limit | Maximum |
| --- | --- |
| Files | 50; at least one required |
| Source file | 64 KiB UTF-8 |
| Total source content | 512 KiB UTF-8 |
| Encoded API request | 1 MiB, including JSON escaping and settings |
| Frontmatter | 16 KiB, nesting depth 16 |
| Instruction body | 16,000 characters, including whitespace; nonempty |
| Workspace name | 100 characters |
| Bot name | 80 characters; distinct within the import, ignoring case |
| Public purpose | 400 characters / 1,600 UTF-8 bytes |

Oversized files and instructions are rejected, never truncated. Identical sources
still create separate bots once their names are distinct. Filenames are labels,
not server paths. Referenced files, links, executable hooks, and external tool
packages are not fetched or installed. The importer does not infer a task graph,
lead agent, group, routine, or initial prompt. Agent references in the body remain
unchanged; runtime directory tools provide the current bot IDs and purposes.

## API and recovery

Migration `020_workflow_imports.sql` adds durable owner-scoped receipts. The
authenticated capability response advertises `workflow_imports` and
`workflow_import_limits`. Import requires workspace features, channels, and tool
libraries to be enabled; disabling a prerequisite prevents new imports.

The endpoints are:

- `POST /api/workflow-imports/preview`: validate a draft without persisting it.
- `POST /api/workflow-imports`: commit the reviewed draft using a request ID and
  preview digest; return the workspace ID and source-to-bot mapping.
- `GET /api/workflow-imports/{request_id}`: retrieve the importing user's committed
  result. Another owner receives 404.

Example preview draft:

```json
{
  "workspace_name": "Writing team",
  "defaults": {
    "framework": "microsoft",
    "credential_id": "saved-credential-id",
    "model": "gpt-4.1"
  },
  "files": [
    {
      "file_id": "writer-source",
      "filename": "writer.agent.md",
      "content": "---\nname: Writer\ndescription: Draft reports\n---\n# Writer\nAsk a peer to verify facts.\n"
    }
  ]
}
```

Preview returns per-file errors/warnings, resolved runtime/tool selections, exact
instruction bodies, and a digest. For commit, send the same draft with a unique
`request_id` and that `preview_digest`. IDs contain 8-128 letters, digits, `_`, or
`-`. Overrides are supplied in each file's `overrides` object: `name`, `purpose`,
and an optional complete `runtime` choice. Omitted `tool_selection` uses standard
computer tools; an explicit empty list selects messaging only.

Credentials, tool compatibility, and manifest digests are rechecked at commit.
Changed sources/settings or tool manifests require a fresh preview. No file content,
metadata, credential secret, or additional instruction copy is stored in receipts;
they contain IDs, filenames, hashes, and the creation result. Directory/configuration
events and the receipt commit atomically with the workspace and bots.

If a response is lost, use **Check import result** or **Retry same import**. The
browser retains the original command in memory and only its request ID in tab
session storage. After reload, check the receipt before reconstructing the original
files/settings to retry with that ID. An absent receipt does not prove an in-flight
operation rolled back. Do not automatically retry with a new ID.

An identical committed retry returns the original result, including after restart,
parser upgrade, or bot/credential deletion. Different arguments using a committed
ID return 409. Receipts describe creation, not current resource existence. Failed
transactions have no receipt or partial workspace. Browser cancellation waits for
started database work to settle; it is not treated as proof of rollback. A later
workspace-selection preference failure does not undo or repeat a successful import.

The [implementation plan](024-markdown-workflow-import-plan.md) records scope and
acceptance scenarios; the [implementation ledger](003-agent-control-implementation-status.md)
records validation evidence. The API and frontend contracts are generated from
`workflow_imports/schemas.py`; `scripts/check_wire.py` checks for drift.
