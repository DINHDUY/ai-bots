from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from agentbot.interfaces import ActionResult, SandboxError

from agentbot_control.event_store import packed, sanitized
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.toolkit import Toolkit


def recording(self: Toolkit, lease_id):
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT * FROM recordings WHERE lease_id=? AND state!='stopped'",
            (lease_id,),
        ).fetchone()
    return dict(row) if row else None


def record(self: Toolkit, lease_id, event, meta):
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT * FROM recordings WHERE lease_id=? AND state='recording' AND private=0",
            (lease_id,),
        ).fetchone()
        if not row:
            return
        steps = json.loads(row["steps"])
        if len(steps) >= 100:
            db.execute("UPDATE recordings SET state='paused' WHERE id=?", (row["id"],))
            return
        steps.append(
            {
                "operation": "input",
                "surface": meta["surface_kind"],
                "input": event,
                "width": meta["width"],
                "height": meta["height"],
                "url": meta.get("url"),
                "fragile": True,
            }
        )
        db.execute(
            "UPDATE recordings SET steps=? WHERE id=?",
            (packed(sanitized(steps)), row["id"]),
        )


def checkpoint(self: Toolkit, lease_id, detail):
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT id,steps FROM recordings WHERE lease_id=? AND state='recording' AND private=0",
            (lease_id,),
        ).fetchone()
        if row:
            steps = json.loads(row["steps"])
            if len(steps) < 100:
                steps.append({"operation": "checkpoint", "detail": detail})
            db.execute(
                "UPDATE recordings SET steps=?,state='paused' WHERE id=?",
                (packed(steps), row["id"]),
            )


def skill(self: Toolkit, uid, bid, skill_id):
    self.workspaces.bot(uid, bid, "write")
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT s.* FROM skill_versions s JOIN bot_streams origin ON origin.bot_id=s.bot_id JOIN bot_streams target ON target.workspace_id=origin.workspace_id WHERE target.bot_id=? AND s.id=?",
            (bid, skill_id),
        ).fetchone()
    if not row:
        raise Conflict("Skill version is not installed on this bot.")
    return dict(row)


def program(self: Toolkit, uid, bid, skill_id, parameters):
    skill = self.skill(uid, bid, skill_id)
    schema = json.loads(skill["parameters"])
    if set(parameters) != set(schema) or any(
        not isinstance(v, str) or len(v) > 1000 for v in parameters.values()
    ):
        raise Conflict("Skill parameter names must match its immutable schema.")

    def substitute(value):
        if isinstance(value, str):
            return re.sub(
                r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}",
                lambda m: parameters[m[1]],
                value,
            )
        if isinstance(value, dict):
            return {k: substitute(v) for k, v in value.items()}
        return value

    steps = [substitute(s) for s in json.loads(skill["steps"])]

    async def execute(guard, streamer):
        for index, step in enumerate(steps):
            self.skill(uid, bid, skill_id)
            operation = step.get("operation")
            if operation == "checkpoint":
                raise SandboxError(
                    "Manual checkpoint: " + step.get("text", "Review unsupported step")
                )

            async def action(step=step):
                self.skill(uid, bid, skill_id)
                if step["operation"] == "open_browser":
                    image = await guard.browser_open(step["url"])
                elif step["operation"] == "click_element":
                    image = await guard.browser_click(step["selector"])
                else:
                    image = await guard.capture(step["surface"])
                    meta = image.metadata
                    if (meta["width"], meta["height"]) != (
                        step["width"],
                        step["height"],
                    ) or (step.get("url") and step["url"] != meta.get("url")):
                        return ActionResult(
                            False,
                            "Viewport or page drift. Re-teach or use a selector.",
                        )
                    image = await guard.human_input(step["surface"], step["input"])
                return ActionResult(True, "Skill step completed.", value=image)

            args = {k: v for k, v in step.items() if k != "operation"}
            async for item in streamer.execute_action(
                "skill",
                operation,
                args,
                f"Skill {skill['name']} step {index + 1}: {packed(args)}",
                action,
            ):
                if isinstance(item, ActionResult):
                    if item.value:
                        yield streamer.emit_screenshot("skill", item.value)
                    if not item.ok:
                        raise SandboxError(item.text)
                else:
                    yield item
        yield streamer.emit_log("skill", "RESULT", f"Skill {skill['name']} completed.")

    async def selected_execute(guard, streamer):
        with streamer.context.tool_access.scope("replay_skill", {"skill_id": skill_id}):
            async for frame in execute(guard, streamer):
                yield frame

    return selected_execute
