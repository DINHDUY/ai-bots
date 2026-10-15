"""Bound request bodies before multipart parsing can spool unbounded files."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class RequestLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = (
            64 * 1024 * 1024 + 131072
            if scope["path"].endswith("/uploads")
            else 1024 * 1024
        )
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        if length > limit:
            return await JSONResponse(
                {"detail": "Request body exceeds limit."}, status_code=413
            )(scope, receive, send)
        received = 0

        async def bounded():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(413, "Request body exceeds limit.")
            return message

        await self.app(scope, bounded, send)
