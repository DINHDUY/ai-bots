"""Import HTTP contracts, independent of the running application."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PARSER_VERSION = "1"
LIMITS = {
    "files": 50,
    "file_bytes": 65536,
    "source_bytes": 524288,
    "request_bytes": 1048576,
    "frontmatter_bytes": 16384,
    "instructions": 16000,
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImportTool(StrictModel):
    library_id: str = Field(max_length=128)
    tool_id: str = Field(max_length=128)
    version: str = Field(max_length=40)
    configuration: dict[str, str] = Field(default_factory=dict, max_length=1)


class RuntimeChoice(StrictModel):
    framework: str = Field(default="microsoft", max_length=40)
    credential_id: str = Field(default="", max_length=128)
    model: str = Field(default="", max_length=128)
    tool_selection: list[ImportTool] | None = Field(default=None, max_length=64)


class AgentOverrides(StrictModel):
    name: str | None = Field(default=None, max_length=1000)
    purpose: str | None = Field(default=None, max_length=2000)
    runtime: RuntimeChoice | None = None


class SourceFile(StrictModel):
    file_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=1048576)
    overrides: AgentOverrides = Field(default_factory=AgentOverrides)


class ImportDraft(StrictModel):
    workspace_name: str = Field(max_length=1000)
    defaults: RuntimeChoice = Field(default_factory=RuntimeChoice)
    files: list[SourceFile] = Field(min_length=1, max_length=50)


class ImportCommand(ImportDraft):
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImportIssue(StrictModel):
    field: str
    code: str
    message: str


class PreviewFile(StrictModel):
    file_id: str
    filename: str
    name: str
    purpose: str
    instructions: str
    runtime: RuntimeChoice
    errors: list[ImportIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportPreview(StrictModel):
    workspace_name: str
    files: list[PreviewFile]
    errors: list[ImportIssue] = Field(default_factory=list)
    valid: bool = False
    parser_version: str = PARSER_VERSION
    preview_digest: str = ""


class ImportedBot(StrictModel):
    file_id: str
    filename: str
    bot_id: str
    name: str
    source_hash: str
    body_hash: str


class ImportResult(StrictModel):
    request_id: str
    workspace_id: str
    workspace_name: str
    bots: list[ImportedBot]
    computer_mode: Literal["shared"] = "shared"
    computer_provider: Literal["docker"] = "docker"
    collaboration_enabled: Literal[True] = True


class ImportContracts(StrictModel):
    """Root for generating all frontend request/response types."""

    draft: ImportDraft
    command: ImportCommand
    preview: ImportPreview
    result: ImportResult
