# Agent Control tool libraries

Tool libraries are available in **New bot → Tools** and **Bot settings → Tools**. Search or expand a library and select individual tools or a native framework bundle. Checkboxes update the draft; **Add bot** or **Save** commits it. Closing the dialog discards unsaved selections.

New bots start with no tools selected. **Computer basics** adds the compatible general tools. Microsoft and Anthropic can answer messages with an empty selection; UFO requires its Windows desktop bundle to run. Changing frameworks leaves incompatible selections visible so you can remove them before saving.

Task-specific examples are not built-in application tools. The ETL demo lives only in [docs/usecases](usecases/azure-blob-etl-playbook.md); it has no frontend preset or backend catalog entry.

## Libraries and bindings

| Library | Framework | Selection |
| --- | --- | --- |
| Terminal | Microsoft, Anthropic | Run command |
| Workspace files | Microsoft | Write file, Patch file |
| Workspace files | Anthropic | Native text editor bundle |
| Browser | Microsoft | Open page, Click element |
| Linux desktop | Anthropic | Native computer-use bundle |
| Windows desktop | UFO | Companion observation and control bundle |
| GitHub issues | Microsoft, Anthropic | Canonical issue tool with selected repository connections |
| Taught tasks | Microsoft, Anthropic | Canonical replay tool with selected immutable skill versions |

Create connections and taught tasks in Toolkit, then select their references in Settings. Multiple references use one model tool name. A resource without setup, a disconnected repository, or a missing library version remains visible but is omitted from usable model tools. Connection tokens stay in encrypted backend storage. Removing a tool binding retains the saved connection/skill; explicitly uninstalling a connector through Toolkit revokes its local credential.

Tool selection controls model entry points. General shell or desktop control remains broad: deselecting a specialized workflow does not prevent a selected shell from performing comparable work. Existing action approvals, Autopilot, workspace scope, checked mutations, and Windows local consent still apply. Manual uploads and computer controls remain separate.

## Configuration and execution

`GET /api/tool-libraries?framework=microsoft` returns the maintained catalog, compatibility, configuration schemas, and manifest digests. `GET /api/bots/{id}/tools` returns the saved selection, binding readiness, resource choices, and whether the caller can edit.

Creation accepts `tool_selection`. Settings accept the same list plus `expected_tools_revision`:

```json
{
  "tool_selection": [
    {
      "library_id": "sandbox.terminal",
      "version": "1.0.0",
      "tool_id": "run_terminal_command",
      "configuration": {}
    }
  ],
  "expected_tools_revision": 1
}
```

Metadata and tools commit in one SQLite transaction. An omitted selection on PATCH preserves it; `[]` removes all tools. Conflicts return HTTP 409 without saving metadata or tools. The frontend retains the draft and offers **Reload saved tools**. Only the bot owner can change bindings. Authenticated `bot.tools.updated` events invalidate open settings queries; snapshots retain the latest revision after event pruning.

Each admitted run pins binding IDs, binding revisions, exact versions, and implementation digests. Model schemas expose only usable pinned tools. Dispatch validates the binding again in the transaction that claims the action. Additions are available on the next task. Removal cancels dependent pending approvals and prevents undispatched actions; an executing action settles and reports its result. Removing and re-adding creates a new binding, so an older run cannot regain access. Composite actions retain the parent binding. Routine, group, connector, and skill execution follows the same rules.

## Migration and deployment

Restart the updated backend and rebuild/refresh the frontend. Migration `015_tool_libraries.sql` adds bot configuration, bindings, run snapshots, and action provenance. Startup seeds existing bots once with their legacy framework tools and installed connection/skill references. Instructions and messages never install tools, including the former ETL marker. A previously saved demo binding is unavailable and can be removed in Tools; saved user instructions are not rewritten.

Older API clients that omit the creation field receive the generic framework profile; no specialized workflow is inferred. Missing versions are retained as unavailable until the owner removes or replaces them. Startup does not replay interrupted actions. Keep a database backup when deploying; an older backend does not enforce these selections and is not a compatible rollback target.

The catalog loads repository-maintained code from `agentbot/tools/registry.py`; selecting a library does not install packages. New libraries need a stable version, capabilities, operation declarations, schemas/guidance, framework binding, and dispatch tests. Remote package uploads and MCP discovery are outside this release.

Validation uses temporary databases, deterministic model/SDK clients, and simulated computers, plus browser tests at desktop and mobile widths. No live Azure deployment or external message is needed to validate tool selection.

Verified on 2026-10-09: 244 backend/core tests, 51 frontend tests, and four browser checks (390 px and 1600 px) passed. Production frontend build, Ruff checks, and diff whitespace checks passed.
