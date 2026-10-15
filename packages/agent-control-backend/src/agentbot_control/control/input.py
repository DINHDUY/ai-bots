from __future__ import annotations

import asyncio
import base64
import json
import math
import time
from typing import TYPE_CHECKING

from agentbot_control.event_store import packed, stamp
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.control import Control


async def input(self: Control, bot_id, sid, user, token, message):
    lease_id = str(message.get("lease_id", ""))
    async with self.locks.setdefault(lease_id, asyncio.Lock()):
        lease = self.check(
            bot_id,
            sid,
            user,
            token,
            lease_id,
            message.get("client_id"),
            message.get("fence"),
        )
        if (
            message.get("generation") != lease["generation"]
            or message.get("surface_id") != lease["surface_id"]
            or message.get("viewport_revision") != lease["viewport_revision"]
        ):
            raise Conflict("Input surface or generation changed.")
        seq = message.get("sequence")
        if not isinstance(seq, int) or seq < 1:
            raise Conflict("Invalid input sequence.")
        if seq <= lease["last_sequence"]:
            return {"status": "duplicate", "sequence": seq}
        if seq != lease["last_sequence"] + 1:
            raise Conflict("Input sequence gap; reconnect control.")
        event = message.get("input", {})
        if not isinstance(event, dict):
            raise Conflict("Invalid input object.")
        if event.get("kind") != "release":
            rows = self.computer_history(bot_id, lease["surface"])
            capture = rows[0] if rows else None
            if (
                not capture
                or capture["capture_id"] != message.get("capture_id")
                or capture["session_id"] != sid
            ):
                raise Conflict("Input requires the latest capture.")
            meta = capture["capture"]
            if (
                meta.get("viewport_revision") != lease["viewport_revision"]
                or meta.get("transform")
                or meta["surface_id"] != lease["surface_id"]
            ):
                raise Conflict("Viewport changed or capture is view-only.")
        event = message.get("input", {})
        if not isinstance(event, dict):
            raise Conflict("Invalid input object.")
        kind = event.get("kind")
        if (
            kind not in {"move", "down", "up", "key_down", "key_up", "wheel", "release"}
            or len(packed(event)) > 1024
        ):
            raise Conflict("Unsupported input.")
        for key in ("x", "y", "dx", "dy"):
            if key in event and (
                not isinstance(event[key], (float, int)) or not math.isfinite(event[key])
            ):
                raise Conflict("Invalid input coordinate.")
        if kind in {"move", "down", "up"} and not (
            0 <= event.get("x", -1) < meta["width"] and 0 <= event.get("y", -1) < meta["height"]
        ):
            raise Conflict("Input is outside the capture.")
        if kind in {"key_down", "key_up"} and (
            not isinstance(event.get("key"), str) or len(event["key"]) > 40
        ):
            raise Conflict("Invalid key.")
        if time.monotonic() - self.last_input.get(lease_id, 0) < 0.01:
            raise Conflict("Input rate limit exceeded.")
        self.last_input[lease_id] = time.monotonic()
        held = json.loads(lease["held"])
        keys = set(held.get("keys", []))
        if kind == "key_down":
            keys.add(event["key"])
        if kind == "key_up":
            keys.discard(event["key"])
        if kind == "release":
            event["keys"] = list(keys)
            keys.clear()
        with self.store.transaction() as db:
            db.execute(
                "UPDATE control_leases SET last_sequence=?,held=? WHERE id=?",
                (seq, packed({"keys": list(keys)}), lease_id),
            )
        _, sandbox = await self.computer_existing(bot_id, sid)
        async with self.action_locks.setdefault(sid, asyncio.Lock()):
            self.check(
                bot_id,
                sid,
                user,
                token,
                lease_id,
                message.get("client_id"),
                message.get("fence"),
            )
            if kind != "release":
                current = self.computer_history(bot_id, lease["surface"], session_id=sid)
                if not current or current[0]["capture_id"] != message.get("capture_id"):
                    raise Conflict("Capture expired or changed; request a fresh screenshot.")
            image = await sandbox.human_input(lease["surface"], event)
            recording = self.toolkit.recording(lease_id)
            if not recording or not recording["private"]:
                self.store.record_capture(
                    bot_id, None, base64.b64encode(image).decode(), image.metadata
                )
                self.toolkit.record(lease_id, event, image.metadata)
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE computer_sessions SET updated_at=? WHERE id=?",
                    (stamp(), sid),
                )
                self.store._event(
                    db,
                    bot_id,
                    "control.input",
                    {
                        "actor": user.id,
                        "kind": kind,
                        "surface": lease["surface"],
                        "sequence": seq,
                    },
                )
        return {"status": "applied", "sequence": seq}
