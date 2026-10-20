"""An explicit registry; catalog inspection never imports user-supplied code."""

import json
from dataclasses import asdict, dataclass
from functools import cached_property
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path


@dataclass(frozen=True)
class ToolSpec:
    library_id: str
    library_name: str
    tool_id: str
    name: str
    description: str
    frameworks: tuple[str, ...]
    operations: tuple[str, ...]
    methods: tuple[str, ...] = ()
    version: str = "1.0.0"
    resource: str | None = None
    bundle: bool = False
    guidance: str = ""
    dependencies: tuple[str, ...] = ()
    approval_protocol: int = 2
    requires_computer: bool = True
    implementation_modules: tuple[str, ...] = ()
    adapter_modules: tuple[str, ...] = ()
    providers: tuple[str, ...] = ("docker", "azure_vm", "azure_ml_compute_instance")
    default_selected: bool = False

    @property
    def key(self):
        return f"{self.library_id}/{self.tool_id}"

    @cached_property
    def digest(self):
        # Include the handler/adapter implementations so a deployment cannot
        # silently execute different code under a pinned run manifest.
        root = Path(__file__).parents[1]
        files = [Path(__file__), root / "tools/context.py"]
        modules = self.adapter_modules or tuple(
            f"agentbot.adapters.{name}" for name in self.frameworks
        )
        for module in (*modules, *self.implementation_modules):
            spec = find_spec(module)
            if spec is None or not spec.origin:
                raise RuntimeError(
                    f"Tool implementation is unavailable: {module}. Install its integration package."
                )
            files.append(Path(spec.origin))
            # A split adapter package must pin its operations, not only its facade.
            for directory in spec.submodule_search_locations or ():
                files.extend(
                    path
                    for path in sorted(Path(directory).rglob("*.py"))
                    if path != Path(spec.origin) and "__pycache__" not in path.parts
                )
        digest = sha256(json.dumps(asdict(self), sort_keys=True).encode())
        for path in files:
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def public(self, framework=None, provider=None):
        compatible = framework is None or framework in self.frameworks
        reason = "" if compatible else "Unavailable for this framework"
        if self.requires_computer and provider and provider not in self.providers:
            compatible, reason = False, "Requires a different computer type"
        return {
            **asdict(self),
            "digest": self.digest,
            "compatible": compatible,
            "reason": reason,
            "provenance": "Repository maintained",
            "selection_kind": "bundle" if self.bundle else "tool",
            "input_schema": input_schema(self.tool_id),
            "output_schema": {
                "type": "string",
                "description": "Bounded result text; captures and action outcomes are emitted separately.",
            },
            "configuration_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"resource_id": {"type": "string", "maxLength": 128}}
                if self.resource
                else {},
            },
        }


def input_schema(name):
    """Function schemas are translated by the SDK; native bundles keep SDK schemas."""
    fields = {
        "run_terminal_command": ("command",),
        "mutate_file": ("path", "content"),
        "patch_file": ("path", "old_text", "new_text"),
        "open_browser": ("url",),
        "browser_click": ("selector",),
        "github_issues": ("connection_id", "operation", "title", "text"),
        "replay_skill": ("skill_id", "parameters_json"),
    }.get(name)
    if fields is None:
        return {
            "type": "object",
            "description": "Uses the pinned native SDK bundle schema",
            "native_bundle": name,
        }
    optional = {"endpoint", "title", "text", "parameters_json"}
    properties = {
        field: {
            "type": "string",
            "maxLength": 64000 if field in {"content", "old_text", "new_text"} else 8000,
        }
        for field in fields
    }
    if name == "github_issues":
        properties["operation"]["enum"] = ["list_issues", "create_issue"]
    return {
        "type": "object",
        "properties": properties,
        "required": [field for field in fields if field not in optional],
        "additionalProperties": False,
    }


SPECS = (
    ToolSpec(
        "sandbox.terminal",
        "Terminal",
        "run_terminal_command",
        "Run command",
        "Run a bounded shell command. Shell commands can access workspace files and the network.",
        ("microsoft", "anthropic"),
        ("bash",),
        ("run_command",),
    ),
    ToolSpec(
        "sandbox.files",
        "Workspace files",
        "mutate_file",
        "Write file",
        "Write a workspace text file.",
        ("microsoft",),
        ("file_write",),
        ("write_workspace_file",),
    ),
    ToolSpec(
        "sandbox.files",
        "Workspace files",
        "patch_file",
        "Patch file",
        "Replace one exact match in a workspace text file.",
        ("microsoft",),
        ("file_edit",),
        ("read_workspace_file", "write_workspace_file"),
    ),
    ToolSpec(
        "sandbox.files",
        "Workspace files",
        "text_editor",
        "Text editor",
        "Read, create, and edit workspace files using the native editor bundle.",
        ("anthropic",),
        ("file_edit",),
        ("read_workspace_file", "write_workspace_file"),
        bundle=True,
    ),
    ToolSpec(
        "sandbox.browser",
        "Browser",
        "open_browser",
        "Open page",
        "Open an HTTP(S) page and observe its screenshot.",
        ("microsoft",),
        ("open_browser",),
        ("browser_open",),
    ),
    ToolSpec(
        "sandbox.browser",
        "Browser",
        "browser_click",
        "Click element",
        "Click a CSS selector on the browser page.",
        ("microsoft",),
        ("browser_click",),
        ("browser_click",),
    ),
    ToolSpec(
        "sandbox.desktop",
        "Linux desktop",
        "computer",
        "Desktop control",
        "Observe and control the sandbox desktop with the native computer-use bundle.",
        ("anthropic",),
        ("computer.*",),
        ("desktop_action",),
        bundle=True,
    ),
)


def make_registry(specs):
    registry = {}
    for spec in specs:
        if spec.key in registry:
            raise ValueError(f"Duplicate tool ID: {spec.key}")
        registry[spec.key] = spec
    for spec in specs:
        if any(dep not in registry for dep in spec.dependencies):
            raise ValueError(f"Unknown dependency for {spec.key}")

    def visit(key, active):
        if key in active:
            raise ValueError("Tool dependency cycle")
        for dep in registry[key].dependencies:
            visit(dep, active | {key})

    for key in registry:
        visit(key, set())
    names = set()
    for spec in specs:
        for framework in spec.frameworks:
            if (framework, spec.tool_id) in names:
                raise ValueError("Conflicting framework tool name")
            names.add((framework, spec.tool_id))
    return registry


REGISTRY = make_registry(SPECS)


def legacy_selection(framework, registry=None):
    return [
        {
            "library_id": s.library_id,
            "tool_id": s.tool_id,
            "version": s.version,
            "configuration": {},
        }
        for s in (registry or REGISTRY).values()
        if framework in s.frameworks
        and (s.default_selected or s.library_id.startswith(("sandbox.", "windows.")))
    ]
