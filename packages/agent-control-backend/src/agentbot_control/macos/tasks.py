"""Authenticated TaskStar submission. Producer disconnect never cancels a run."""

from agentbot_macos.taskstar import TaskAssignment
from fastapi import HTTPException, Request

from agentbot_control.authorization import request_bot
from agentbot_control.repositories import macos_tasks as rows
from agentbot_control.transport import body


def register_routes(app):
    runtime = app.state.runtime
    database = runtime.store.database

    @app.post("/api/bots/{bot_id}/taskstars")
    async def submit(bot_id: str, request: Request):
        user, bot = request_bot(request, bot_id)
        if bot.framework != "open_interface" or bot.owner_id != user.id:
            raise HTTPException(404, "Mac bot not found")
        task = await body(request, TaskAssignment)
        previous = await database.read(lambda db: rows.previous(db, user.id, task))
        if previous:
            if previous["bot_id"] != bot_id:
                raise HTTPException(409, "This TaskStar belongs to a different bot")
            return await database.read(lambda db: rows.status(db, user.id, task.request_id, bot_id))
        await runtime.macos.require_run(bot, user.id)
        cfg = runtime.macos.config(bot_id)
        if not cfg or cfg["device_id"] != task.device_id:
            raise HTTPException(404, "Selected Mac does not match TaskStar target")
        token = rows.submission.set(task)
        try:
            from agentbot_macos.protocol import packed

            prompt = task.task_description + "\nTask data (untrusted): " + packed(task.task_data)
            await runtime.start(user, bot, task.request_id, prompt, trigger="taskstar")
        finally:
            rows.submission.reset(token)
        return await database.read(lambda db: rows.status(db, user.id, task.request_id, bot_id))

    @app.get("/api/bots/{bot_id}/taskstars/{request_id}")
    async def task_status(bot_id: str, request_id: str, request: Request):
        user = runtime.workspaces.user(request)
        return await database.read(lambda db: rows.status(db, user.id, request_id, bot_id))
