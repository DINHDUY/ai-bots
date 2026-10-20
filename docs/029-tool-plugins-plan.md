# Operator-installed tool plugins

Status: implemented (P1-P3). Usage, trust limits, and recovery are in the
[runtime guide](030-tool-plugins.md). Local validation is in the
[implementation ledger](003-agent-control-implementation-status.md).

This plan adds two ways for an operator to make a tool appear in Agent/Bot
settings without editing the maintained catalog by hand:

- a CLI manifest that runs a fixed argument list inside the bot's computer
- an installed Python package, named in an allowlist, that contributes tool specs and factories

Both show up through the existing tool picker. Selecting one is the same
`tool_selection` write the maintained tools already use.

## Decisions

| Concern | Behavior |
| --- | --- |
| Catalog | One `ToolCatalog` built at the composition root from maintained specs, CLI manifests, and allowlisted entry points. Request handlers read that object. |
| Schemas | Each `ToolSpec` owns its input schema. Native bundles keep the SDK schema. CLI manifests and plugins supply an object schema. |
| Dispatch | Microsoft already calls selected factories. Anthropic dispatches selected factories through the same approval action path. UFO does not call plugin factories. |
| CLI tools | A TOML file declares the tool id, parameter schema, and argv template. The model never supplies a shell string. Values are quoted and the command runs with `sandbox.run_command`. |
| Python plugins | `agentbot.tools` entry points load only when the distribution, exact version, and `RECORD` hash are in the operator allowlist. `library_id` must start with `plugin.<distribution>.` |
| Install | Deployment installs the package or writes the manifest, then restarts the control process. The product UI does not run `pip`, fetch a URL, or accept uploaded code. |
| Pinning | Run snapshots keep the manifest digest. CLI digest covers the manifest bytes and the wrapper. Plugin digest covers the package `RECORD` and its Python sources. A changed or missing implementation becomes unavailable instead of running different code. |
| Secrets | Plugin configuration still accepts only a resource id. Credentials are not manifest fields or model arguments. |
| Trust | CLI commands run in the computer sandbox and still require action approval. An allowlisted Python plugin runs inside the control process and is operator-trusted code. |

[012](012-agent-control-tool-libraries-plan.md) deferred remote MCP servers and
third-party uploads. Those stay out of scope. This plan is the operator-owned
install path that document allowed as a later extension.

## P1 — Catalog and adapter dispatch

- Move input schemas onto `ToolSpec` and delete the hard-coded schema table.
- Add `ToolCatalog` (specs plus factories) in the kernel. The product package
  builds the composed catalog once in `compose_runtime`.
- `ToolLibraries`, bot creation, workflow import, and channel capability labels
  read that catalog.
- Anthropic advertises selected factory tools and runs them under `ToolAccess`,
  yielding approval frames while the action waits.

Maintained connector, skill, messaging, and native computer bundles keep their
current handlers.

## P2 — CLI manifests

`AGENTBOT_TOOL_MANIFESTS` is a directory of `*.toml` files. Empty or unset means
no CLI tools. A missing directory fails startup.

Each file becomes one tool in the library `plugin.cli` / "CLI tools", for
Microsoft and Anthropic, on a computer that provides `run_command`. Paired
Windows computers stay incompatible because these tools require a computer and
are not the Windows desktop bundle. The sandbox command timeout is the execution
limit; the manifest timeout is recorded guidance, not a second kill switch.

Rejected at load: shell metacharacters in static arguments, unknown
placeholders, reserved tool names (`bash`, the editor, computer actions, and
peer-messaging operations), and ids that collide with the catalog.

## P3 — Allowlisted packages

`AGENTBOT_TOOL_ALLOWLIST` is a JSON file:

```json
{
  "plugins": [
    {"distribution": "example-tools", "version": "1.2.0", "record_sha256": "<sha256 of RECORD>"}
  ]
}
```

Unset means no entry-point plugins. A path that is missing, a listed package
that is not installed, a version or `RECORD` mismatch, or more than one
`agentbot.tools` entry point for that distribution fails startup. Installed
entry points that are not listed are ignored.

The entry point returns `{"specs": (...), "factories": {...}}`. Specs may name
only `microsoft` and `anthropic`. Factories receive `ToolExecutionContext` and
must send side effects through `context.action` so approval and audit still
apply. The loader cannot prove they do; that is part of the operator trust
decision in [ADR-0019](adr/0019-operator-installed-tool-plugins.md).

## Acceptance

- A CLI manifest and an allowlisted package each appear in `GET /api/tool-libraries` and in the tool picker, and can be saved on a bot.
- Running a CLI tool quotes argument values, requests approval, and executes one sandbox command.
- Anthropic dispatches a selected factory tool.
- A manifest edit changes the digest. A missing spec is "Unavailable library version".
- An allowlist hash mismatch, a bad library prefix, and a shell metacharacter in a static argument fail closed.
- An entry point that is installed but not allowlisted does not appear.

UFO plugin dispatch, plugin credentials, UI installation, and remote MCP servers
are not part of this delivery.
