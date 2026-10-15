"""Owner authorization shared by v2 HTTP and long-lived subscriptions."""

from fastapi import HTTPException

from agentbot_control.auth import COOKIE_NAME


def owned(catalog, token: str | None, bot_id: str, operation="read"):
    user = catalog.user_from_token(token)
    if user is None:
        raise HTTPException(401, "Sign in required.")
    bot = catalog.authorized_bot(user.id, bot_id, operation)
    if bot is None:
        raise HTTPException(404, "Bot not found.")
    return user, bot


def request_bot(request, bot_id):
    operation = "read" if request.method == "GET" else "write"
    if "approval-policies" in request.url.path or (
        request.method != "GET" and request.url.path.endswith("/autopilot")
    ):
        operation = "owner"
    return owned(
        request.app.state.catalog, request.cookies.get(COOKIE_NAME), bot_id, operation
    )
