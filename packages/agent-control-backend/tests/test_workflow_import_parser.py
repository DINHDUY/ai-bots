"""Exact body extraction and bounded untrusted metadata."""

import pytest
from agentbot_control.workflow_imports.parser import parse
from agentbot_control.workflow_imports.schemas import ImportDraft
from pydantic import ValidationError


def preview(content, **overrides):
    return parse(
        ImportDraft.model_validate(
            {
                "workspace_name": "Workflow",
                "files": [
                    {
                        "file_id": "one",
                        "filename": "research.agent.md",
                        "content": content,
                        "overrides": overrides,
                    }
                ],
            }
        )
    ).files[0]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("closing", ["---", "..."])
@pytest.mark.parametrize("bom", ["", "\ufeff"])
def test_preserve_exact_body(newline, closing, bom):
    body = newline + "# Research 世界" + newline + "  indented  " + newline + "---" + newline
    content = (
        bom
        + newline.join(
            ["---", "name: Analyst", "description: Find evidence", "tools: [unknown]", closing, ""]
        )
        + body
    )
    parsed = preview(content)
    assert not parsed.errors
    assert parsed.name == "Analyst"
    assert parsed.purpose == "Find evidence"
    assert parsed.instructions == body
    assert parsed.warnings == ["Metadata has no configuration effect: tools"]


@pytest.mark.parametrize(
    "body",
    [" \nbody \n", "# Agent\n---\nbody", "```yaml\n---\nname: X\n---\n```\n", "---\n---\nbody"],
)
def test_plain_markdown_and_empty_metadata(body):
    result = preview(body)
    assert not result.errors
    assert result.instructions == ("body" if body.startswith("---") else body)
    assert result.name == "research"


@pytest.mark.parametrize(
    "content",
    [
        "---\nname: Never closed",
        "---\nname: [bad\n---\nbody",
        "---\nname: one\nname: two\n---\nbody",
        "---\nname: !!python/object:danger {}\n---\nbody",
        "---\nname: &a hi\ndescription: *a\n---\nbody",
        "---\n- one\n---\nbody",
        "---\nname: " + "[" * 17 + "x" + "]" * 17 + "\n---\nbody",
        "---\nmetadata: " + "x" * 16384 + "\n---\nbody",
        "+++\nname='unsupported'\n+++\nbody",
        '{"name":"unsupported"}\nbody',
        "body\x00",
    ],
)
def test_invalid_sources_are_errors_without_leaking_yaml_excerpts(content):
    result = preview(content)
    assert result.errors
    assert all("danger" not in item.message for item in result.errors)


def test_invalid_unicode_is_rejected_at_the_input_boundary():
    with pytest.raises(ValidationError, match="valid string"):
        preview("\ud800")


@pytest.mark.parametrize("character", ["x", "\U0001f9d1"])
def test_size_boundaries_and_no_truncation(character):
    body = "\r\n" + character * 15996 + "\r\n"
    assert not preview(body).errors
    large = preview(body + " ")
    assert large.instructions == body + " "
    assert large.errors[0].code == "instructions_size"
    assert large.errors[0].message == (
        "Body is 16001 characters; limit is 16000. No text was truncated."
    )
    assert preview("x" * 65536).errors
    assert preview("🧑" * 20000).errors[0].code == "source_invalid"
    assert preview(" \r\n").errors[0].code == "empty_body"


def test_invalid_suggestions_can_be_corrected_without_modifying_body():
    content = "---\nname: 42\ndescription: [private]\n---\nbody\n"
    assert len(preview(content).errors) == 2
    result = preview(content, name="Analyst", purpose="Check facts")
    assert not result.errors
    assert result.instructions == "body\n"


def test_batch_ids_names_and_filename_validation():
    draft = ImportDraft.model_validate(
        {
            "workspace_name": " ",
            "files": [
                {
                    "file_id": "same",
                    "filename": "../one.md",
                    "content": "body",
                    "overrides": {"name": "Same"},
                },
                {
                    "file_id": "same",
                    "filename": "one.md",
                    "content": "body",
                    "overrides": {"name": "same"},
                },
            ],
        }
    )
    result = parse(draft)
    assert {error.code for error in result.errors} == {"name_size", "duplicate_id"}
    assert {error.code for error in result.files[0].errors} == {"filename", "duplicate_name"}


def test_total_size_limit():
    draft = ImportDraft.model_validate(
        {
            "workspace_name": "Flow",
            "files": [
                {"file_id": f"file{index}", "filename": f"agent{index}.md", "content": "x" * 60000}
                for index in range(9)
            ],
        }
    )
    assert any(error.code == "source_size" for error in parse(draft).errors)
