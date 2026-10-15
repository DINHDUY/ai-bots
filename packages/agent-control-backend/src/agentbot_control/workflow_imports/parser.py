"""Bounded YAML metadata extraction with exact Markdown body preservation."""

import json
import re

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from agentbot_control.workflow_imports.schemas import (
    LIMITS,
    ImportDraft,
    ImportIssue,
    ImportPreview,
    PreviewFile,
    SourceFile,
)


def issue(field: str, code: str, message: str) -> ImportIssue:
    return ImportIssue(field=field, code=code, message=message)


def _mapping(text: str) -> dict[str, object]:
    depth = 0
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            raise ValueError("YAML aliases and anchors are unsupported.")
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if depth > 16:
                raise ValueError("Frontmatter nesting exceeds 16 levels.")
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    node = yaml.compose(text, Loader=yaml.SafeLoader)
    if node is None:
        return {}
    if not isinstance(node, MappingNode):
        raise ValueError("Frontmatter must be a YAML mapping.")
    _check_node(node)
    result = yaml.safe_load(text)
    if not isinstance(result, dict) or not all(isinstance(key, str) for key in result):
        raise ValueError("Frontmatter keys must be text.")
    return result


def _check_node(node: Node) -> None:
    if node.tag not in {
        "tag:yaml.org,2002:" + name
        for name in ("map", "seq", "str", "bool", "null", "int", "float", "timestamp")
    }:
        raise ValueError("Unsupported YAML tag.")
    if isinstance(node, MappingNode):
        seen = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                raise ValueError("Frontmatter keys must be text.")
            if key.value in seen:
                raise ValueError("Duplicate frontmatter key.")
            seen.add(key.value)
            _check_node(value)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _check_node(value)


def _extract(content: str) -> tuple[str, dict[str, object]]:
    text = content.removeprefix("\ufeff")
    lines = text.splitlines(keepends=True)
    first = lines[0].rstrip("\r\n") if lines else ""
    if first == "+++" or first == "{" or first.startswith('{"'):
        raise ValueError("Only YAML frontmatter is supported; convert this header first.")
    if first != "---":
        return text, {}
    for end, line in enumerate(lines[1:], 1):
        if line.rstrip("\r\n") in {"---", "..."}:
            metadata = "".join(lines[1:end])
            if len(metadata.encode("utf-8")) > LIMITS["frontmatter_bytes"]:
                raise ValueError("Frontmatter exceeds 16 KiB.")
            return "".join(lines[end + 1 :]), _mapping(metadata)
    raise ValueError("Frontmatter has no closing --- or ... line.")


def parse_file(source: SourceFile, draft: ImportDraft) -> PreviewFile:
    fallback = re.sub(r"(?i)(\.agent)?\.md$", "", source.filename)
    result = PreviewFile(
        file_id=source.file_id,
        filename=source.filename,
        name=fallback,
        purpose="",
        instructions="",
        runtime=(source.overrides.runtime or draft.defaults).model_copy(deep=True),
    )
    if not source.filename.lower().endswith(".md") or any(
        char in source.filename for char in ("/", "\\", "\x00", ":")
    ):
        result.errors.append(issue("filename", "filename", "Select a Markdown basename (.md)."))
    try:
        size = len(source.content.encode("utf-8"))
        if size > LIMITS["file_bytes"]:
            raise ValueError(f"Source is {size} bytes; limit is 65536.")
        if "\x00" in source.content:
            raise ValueError("Source contains NUL; select a UTF-8 text file.")
        body, metadata = _extract(source.content)
        result.instructions = body
        for key, field in (("name", "name"), ("description", "purpose")):
            override = getattr(source.overrides, field)
            if override is not None:
                setattr(result, field, override.strip())
            elif key in metadata:
                value = metadata[key]
                if isinstance(value, str):
                    setattr(result, field, value.strip())
                else:
                    result.errors.append(issue(field, "metadata_type", f"Enter a text {field}."))
        unknown = sorted(key for key in metadata if key not in {"name", "description"})
        if unknown:
            result.warnings.append("Metadata has no configuration effect: " + ", ".join(unknown))
        if not body.strip():
            result.errors.append(issue("instructions", "empty_body", "Instructions are empty."))
        if len(body) > LIMITS["instructions"]:
            result.errors.append(
                issue(
                    "instructions",
                    "instructions_size",
                    f"Body is {len(body)} characters; limit is {LIMITS['instructions']}. "
                    "No text was truncated.",
                )
            )
    except (UnicodeError, ValueError, yaml.YAMLError) as exc:
        # YAML exceptions can contain source excerpts. Never return or log them.
        message = "Invalid YAML frontmatter." if isinstance(exc, yaml.YAMLError) else str(exc)
        if isinstance(exc, UnicodeError):
            message = "Source must be valid UTF-8 text."
        result.errors.append(issue("content", "source_invalid", message))
    if source.overrides.name is not None:
        result.name = source.overrides.name.strip()
    if source.overrides.purpose is not None:
        result.purpose = source.overrides.purpose.strip()
    if not result.name.strip() or len(result.name) > 80:
        result.errors.append(issue("name", "name_size", "Name must be 1-80 characters."))
    if len(result.purpose) > 400 or len(result.purpose.encode("utf-8", errors="replace")) > 1600:
        result.errors.append(
            issue(
                "purpose",
                "purpose_size",
                "Public purpose must be at most 400 characters / 1600 bytes.",
            )
        )
    return result


def parse(draft: ImportDraft) -> ImportPreview:
    result = ImportPreview(workspace_name=draft.workspace_name.strip(), files=[])
    if not 1 <= len(result.workspace_name) <= 100:
        result.errors.append(
            issue("workspace_name", "name_size", "Workspace name must be 1-100 characters.")
        )
    total = sum(len(source.content.encode("utf-8", errors="replace")) for source in draft.files)
    if total > LIMITS["source_bytes"]:
        result.errors.append(
            issue("files", "source_size", f"Sources total {total} bytes; limit is 524288.")
        )
    ids = [source.file_id for source in draft.files]
    if len(set(ids)) != len(ids):
        result.errors.append(
            issue("files", "duplicate_id", "Each file must have a distinct file ID.")
        )
    result.files = [parse_file(source, draft) for source in draft.files]
    names = [file.name.casefold() for file in result.files]
    for file in result.files:
        if names.count(file.name.casefold()) > 1:
            file.errors.append(
                issue("name", "duplicate_name", "Choose distinct bot names for these files.")
            )
    # Escaping in transport can increase size beyond the sum of source bytes.
    if (
        len(json.dumps(draft.model_dump(), ensure_ascii=False).encode("utf-8", errors="replace"))
        > LIMITS["request_bytes"]
    ):
        result.errors.append(issue("files", "request_size", "Encoded request exceeds 1 MiB."))
    return result
