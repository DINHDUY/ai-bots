"""Remove an idle shared-mode bot without invoking per-bot computer retirement."""

import sqlite3

from agentbot_control.channels import Channels
from agentbot_control.schemas import Conflict
from agentbot_control.shared_computers.resolution import open_computer, uses_shared
from agentbot_control.store import Bot, Catalog


def remove_idle_bot(db: sqlite3.Connection, bot: Bot, catalog: Catalog, channels: Channels) -> bool:
    workspace = uses_shared(db, bot.id)
    if not workspace:
        return False
    if open_computer(db, workspace["workspace_id"]) or channels.store._active(db, bot.id):
        raise Conflict(
            "Close the shared workspace computer and finish this bot's active task before deleting it.",
            code="computer_busy",
        )
    channels.retire(db, bot.id, final=True)
    catalog.delete_bot(bot.owner_id, bot.id, _db=db)
    return True
