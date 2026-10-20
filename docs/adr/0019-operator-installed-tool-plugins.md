# ADR-0019: Operator-installed tool plugins

## Status

Accepted

## Context

Tool selection is a maintained catalog. [012](../012-agent-control-tool-libraries-plan.md) said a bot installs a tool by binding a package that is already available, and that remote MCP servers and uploaded packages could be a later extension. Operators still need a way to add a tool without editing product source, and to see it in Agent/Bot settings.

## Decision

The control process builds one tool catalog at startup.

- CLI tools come from TOML manifests in `AGENTBOT_TOOL_MANIFESTS`. They run a fixed, quoted argument list inside the bot's computer and use the normal action approval path.
- Python tools come from `agentbot.tools` entry points named in `AGENTBOT_TOOL_ALLOWLIST`, matched to an exact distribution version and `RECORD` hash. They are imported at startup, not when a bot is edited or a page is opened.

The product UI only selects tools that are already in that catalog. It does not install packages or accept uploaded code. UFO does not call these factories. Allowlisted Python runs in the control process with the process's privileges; operators treat that code as trusted. CLI commands stay in the computer sandbox.

## Consequences

See [029](../029-tool-plugins-plan.md) and [030](../030-tool-plugins.md). A deployment that changes a manifest, package, or allowlist restarts the control process. In-flight runs keep their pinned digest and lose the tool if the implementation changed. Unlisted entry points are ignored. Secrets remain outside plugin configuration.
