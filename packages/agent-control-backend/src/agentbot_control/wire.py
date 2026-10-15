"""Side-effect-free public v2 replay envelopes (domain payloads evolve additively)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal[2]
    event_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    bot_id: str = Field(min_length=1)
    session_id: str | None
    run_id: str | None
    action_id: str | None = None
    workspace_id: str | None = None
    generation: int | None = Field(default=None, ge=0)
    occurred_at: str
    type: str = Field(min_length=1)
    data: dict[str, JsonValue]


class Message(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: str
    role: Literal["user", "assistant"]
    content: str
    seq: int
    ordinal: int
    occurred_at: str | None


class SnapshotData(BaseModel):
    # Additional fields are version-2 capability extensions, not authorization.
    model_config = ConfigDict(extra="allow", strict=True)
    schema_version: Literal[2]
    bot_id: str = Field(min_length=1)
    snapshot_seq: int = Field(ge=0)
    computer: dict[str, JsonValue] | None
    run: dict[str, JsonValue] | None
    messages: list[Message]
    messages_before: int | None
    events: list[EventEnvelope]
    pending_approvals: list[dict[str, JsonValue]]
    observations_truncated: bool


class SnapshotFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["snapshot"]
    data: SnapshotData


class ReadyFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["ready"]
    seq: int = Field(ge=0)


WireFrame = EventEnvelope | Annotated[SnapshotFrame | ReadyFrame, Field(discriminator="type")]


def export(path: Path) -> None:
    schema = TypeAdapter(WireFrame).json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "WireFrame"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys

    export(Path(sys.argv[1]))
