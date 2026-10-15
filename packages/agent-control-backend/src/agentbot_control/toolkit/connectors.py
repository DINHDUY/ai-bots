from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx
from agentbot.interfaces import ActionResult, SandboxError

from agentbot_control.event_store import packed, stamp
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.toolkit import Toolkit


def connection(self: Toolkit, bid, cid):
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT c.* FROM connections c JOIN installations i ON i.bot_id=c.bot_id AND i.resource_id=c.id AND i.kind='connector' WHERE c.id=? AND c.bot_id=? AND c.status!='revoked'",
            (cid, bid),
        ).fetchone()
    if not row or not row["secret"]:
        raise Conflict("Connection revoked or uninstalled.")
    return dict(row)


async def checked_github(self: Toolkit, bid, cid, operation, arguments, expected=None):
    try:
        return await self.github(bid, cid, operation, arguments, expected)
    except (httpx.HTTPError, ValueError):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE connections SET status='unavailable',checked_at=? WHERE id=? AND status!='revoked'",
                (stamp(), cid),
            )
        raise Conflict("GitHub connection unavailable or returned an invalid response.") from None


async def github(self: Toolkit, bid, cid, operation, arguments, expected=None):
    async with self.connection_locks.setdefault(cid, asyncio.Lock()):
        connection = self.connection(bid, cid)
        if expected and expected != connection["version"]:
            raise Conflict("Connection rotated after approval. Request a fresh action.")
        token = self.catalog.unseal(connection["secret"]).decode()
        path = f"/repos/{connection['repository']}"
        method, payload = "GET", None
        if operation == "list_issues":
            path += "/issues?per_page=30"
        elif operation == "create_issue":
            if not arguments.get("title"):
                raise Conflict("Issue title required.")
            method, path = "POST", path + "/issues"
            payload = {
                "title": arguments["title"],
                "body": arguments.get("text", ""),
            }
        elif operation != "health":
            raise Conflict("Unsupported connector tool.")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            async with client.stream(
                method,
                "https://api.github.com" + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=payload,
            ) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        raise Conflict("Connector response exceeds 1 MiB.")
                status = (
                    "connected"
                    if 200 <= response.status_code < 300
                    else "needs_auth"
                    if response.status_code in {401, 403}
                    else "unavailable"
                )
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE connections SET status=?,checked_at=? WHERE id=?",
                        (status, stamp(), cid),
                    )
                if status != "connected":
                    raise Conflict(
                        f"GitHub request failed (HTTP {response.status_code}); connection {status}."
                    )
                data = json.loads(raw)
        # Return only documented fields. Provider tokens never reach sandbox or public records.
        if operation == "health":
            return {
                "status": "connected",
                "repository": connection["repository"],
                "permissions": data.get("permissions", {}),
            }

        def issue(item):
            return {k: item.get(k) for k in ("number", "title", "state", "html_url")}

        return [issue(item) for item in data[:30]] if isinstance(data, list) else issue(data)


def connector_program(self: Toolkit, bid, cid, command):
    connection = self.connection(bid, cid)
    arguments = {
        "connection_id": cid,
        "connection_version": connection["version"],
        "repository": connection["repository"],
        "operation": command.operation,
        "title": command.title,
        "text": command.text,
    }

    async def execute(guard, streamer):
        async def action():
            result = await self.checked_github(
                bid, cid, command.operation, arguments, connection["version"]
            )
            return ActionResult(True, packed(result))

        async for item in streamer.execute_action(
            "github", "connector.github", arguments, packed(arguments), action
        ):
            if isinstance(item, ActionResult):
                if not item.ok:
                    raise SandboxError(item.text)
                yield streamer.emit_log("github", "RESULT", item.text)
            else:
                yield item

    return execute
