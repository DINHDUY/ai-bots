# Adding a tool plugin

Operators can add a tool without changing product source. After a restart, it
appears in **New bot → Tools** and **Bot settings → Tools**. Select it the same
way as a maintained tool. The next task uses it. Removing it cancels that
tool's pending actions.

Two install paths are supported. Neither path installs code from the product
UI, and neither accepts a secret in the tool's configuration.

## CLI manifest

Set `AGENTBOT_TOOL_MANIFESTS` to a directory of `*.toml` files. Each file is one
tool in the **CLI tools** library, for Microsoft and Anthropic bots on a Docker
or Azure computer.

```toml
tool_id = "list_dir"
name = "List directory"
description = "List one workspace directory with ls."
binary = "ls"
timeout_seconds = 30
output_limit = 8000
argv = ["ls", "-la", "{path}"]

[parameters.path]
description = "Workspace directory"
required = true
max_length = 200
```

`argv` is a fixed list. A `{parameter}` token is one whole argument. Static
arguments cannot contain shell syntax. Values are quoted before the command
runs in the bot's computer, and the run waits for the normal action approval.
`timeout_seconds` is guidance for operators: the computer's own command timeout
is what stops the process. `binary` must be the first argument and must already
exist on that computer.

Leave the variable unset for no CLI tools. A path that is not a directory, or
a manifest that breaks these rules, stops the control process from starting.

## Python package

Install the distribution with the deployment's locked install, then name it in
the JSON file at `AGENTBOT_TOOL_ALLOWLIST`:

```json
{
  "plugins": [
    {
      "distribution": "example-tools",
      "version": "1.2.0",
      "record_sha256": "<sha256 of the installed RECORD file>"
    }
  ]
}
```

Print the hash from the environment that will run the control process:

```powershell
python -c "import hashlib, importlib.metadata; d=importlib.metadata.distribution('example-tools'); print(hashlib.sha256(d.read_text('RECORD').encode()).hexdigest())"
```

The package exposes one `agentbot.tools` entry point. It returns specs and
factories:

```python
from agentbot.tools import ToolSpec

SPEC = ToolSpec(
    "plugin.example_tools.echo",
    "Example",
    "echo_text",
    "Echo",
    "Return the supplied text.",
    ("microsoft", "anthropic"),
    ("echo",),
    parameters=("text",),
)

def plugin():
    def factory(context):
        async def echo_text(text: str) -> str:
            """Return the supplied text."""

            async def execute():
                from agentbot.interfaces import ActionResult
                return ActionResult(True, text)

            result = await context.action("echo", {"text": text}, text, execute)
            return result.text

        return echo_text

    return {"specs": (SPEC,), "factories": {"echo_text": factory}}
```

`library_id` must start with `plugin.` plus the distribution name in lowercase,
with hyphens and dots turned into underscores. The loader records the installed
version and `RECORD` hash. A mismatch, a missing package, or a second entry
point for the same distribution stops startup. Entry points that are installed
but not listed are ignored.

The factory runs inside the control process. Send computer side effects through
`context.action` so approval and the run record still apply. Code in an
allowlisted package is trusted with the control process's privileges. UFO bots
cannot select these tools.

## Recovery

Restart after changing a manifest, package, allowlist, or hash. A task that
already started keeps the digest it pinned. If the file or package changed, that
task loses the tool instead of running different code; start a new task after
reviewing Bot settings. A tool that disappeared shows as unavailable and can be
removed from the selection. The saved bot is otherwise unchanged.
