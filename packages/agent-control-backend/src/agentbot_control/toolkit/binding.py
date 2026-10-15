from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
from agentbot.interfaces import ActionResult

from agentbot_control.event_store import packed
from agentbot_control.schemas import Conflict
from agentbot_control.toolkit import ConnectorCall

if TYPE_CHECKING:
    from agentbot_control.toolkit import Toolkit


def bind_tools(self: Toolkit, bid, streamer, context):
    with self.store.transaction() as db:
        connections = [
            dict(r)
            for r in db.execute(
                "SELECT c.id,c.repository FROM connections c JOIN installations i ON i.resource_id=c.id AND i.bot_id=c.bot_id AND i.kind='connector' WHERE c.bot_id=? AND c.status!='revoked'",
                (bid,),
            )
        ]
    access = streamer.context.tool_access
    selected_connections = {
        b["configuration"].get("resource_id") for b in access.candidates("github_issues")
    }
    connections = [row for row in connections if row["id"] in selected_connections]
    skills = access.candidates("replay_skill")
    streamer.context.connector_tools = []
    if skills:
        with self.store.transaction() as db:
            details = [
                dict(row)
                for b in skills
                for row in db.execute(
                    "SELECT id,name,description,parameters FROM skill_versions WHERE id=?",
                    (b["configuration"]["resource_id"],),
                )
            ]
        context.append({"role": "user", "content": "Selected taught tasks: " + packed(details)})

        async def replay(skill_id, parameters_json="{}"):
            access.require("replay_skill", {"skill_id": skill_id})
            parameters = json.loads(parameters_json)
            if not isinstance(parameters, dict):
                raise ValueError("Task parameters must be an object")
            run = self.store.run(bid, streamer.rid)
            program = self.program(run["user_id"], bid, skill_id, parameters)
            async for frame in program(streamer.context.sandbox_guard, streamer):
                if frame.get("event") == "approval_required":
                    continue
                if frame.get("type") == "SCREENSHOT_CAPTURE":
                    self.store.record_capture(
                        bid, streamer.rid, frame.get("payload", ""), frame.get("capture")
                    )
                elif frame.get("type") != "RESULT":
                    self.store.record_frame(bid, streamer.rid, frame, streamer.secrets)
            return "Taught task completed."

        streamer.context.skill_execute = replay
        streamer.context.connector_tools.append(
            {
                "name": "replay_skill",
                "description": "Replay a selected taught task version with its named string parameters.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string"},
                        "parameters_json": {"type": "string"},
                    },
                    "required": ["skill_id"],
                    "additionalProperties": False,
                },
            }
        )
    if not connections:
        return
    context.append(
        {
            "role": "user",
            "content": "Installed backend GitHub connections: " + packed(connections),
        }
    )

    def prepare(connection_id, operation, title="", text=""):
        access.require("github_issues", {"connection_id": connection_id})
        command = ConnectorCall(
            request_id="adapter_connector",
            operation=operation,
            title=title,
            text=text,
        )
        row = self.connection(bid, connection_id)
        return {
            "connection_id": row["id"],
            "connection_version": row["version"],
            "repository": row["repository"],
            "operation": command.operation,
            "title": command.title,
            "text": command.text,
        }

    async def execute(arguments):
        try:
            result = await self.checked_github(
                bid,
                arguments["connection_id"],
                arguments["operation"],
                arguments,
                arguments["connection_version"],
            )
            return ActionResult(True, packed(result))
        except (Conflict, httpx.HTTPError) as exc:
            return ActionResult(False, str(exc))

    streamer.context.connector_prepare = prepare
    streamer.context.connector_execute = execute
    streamer.context.connector_tools += [
        {
            "name": "github_issues",
            "description": "List or create issues through an installed, scoped backend connection. Normal approval is required.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "connection_id": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": ["list_issues", "create_issue"],
                    },
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["connection_id", "operation"],
                "additionalProperties": False,
            },
        }
    ]
