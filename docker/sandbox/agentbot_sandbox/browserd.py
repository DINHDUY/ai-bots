#!/usr/bin/env python3
"""Persistent Playwright page for the sandbox browser tools."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

SOCKET = "/tmp/agentbot-browser.sock"


def origin(url):
    parts = urlsplit(url)
    port = parts.port
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (
        f":{port}" if port and port != (443 if parts.scheme == "https" else 80) else ""
    )


async def main() -> None:
    from playwright.async_api import async_playwright

    if os.path.exists(SOCKET):
        os.remove(SOCKET)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page(
            viewport={"width": 1024, "height": 768}, service_workers="block"
        )
        await page.goto("about:blank")
        allowed_origin = None
        # Playwright routing skips subsequent HTTP redirect hops. Intercept
        # document requests in Chromium as well, before each hop is sent.
        navigation = await page.context.new_cdp_session(page)

        async def check_hop(event):
            if allowed_origin and origin(event["request"]["url"]) != allowed_origin:
                await navigation.send(
                    "Fetch.failRequest",
                    {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
                )
            else:
                await navigation.send(
                    "Fetch.continueRequest", {"requestId": event["requestId"]}
                )

        navigation.on("Fetch.requestPaused", check_hop)
        await navigation.send(
            "Fetch.enable",
            {
                "patterns": [
                    {
                        "urlPattern": "*",
                        "resourceType": "Document",
                        "requestStage": "Request",
                    }
                ]
            },
        )

        async def confine_navigation(route):
            request = route.request
            if allowed_origin and request.is_navigation_request():
                if request.frame.page != page or origin(request.url) != allowed_origin:
                    await route.abort("blockedbyclient")
                    return
            await route.continue_()

        await page.context.route("**/*", confine_navigation)

        lock = asyncio.Lock()
        keys, buttons = set(), set()

        async def dispatch(request):
            nonlocal allowed_origin
            command = request.get("cmd")
            if command == "health":
                return {
                    "ok": browser.is_connected() and not page.is_closed(),
                    "viewport": page.viewport_size,
                }
            if command in {"open", "click"}:
                allowed_origin = request.get("origin")
            if command == "open":
                await page.goto(
                    request["url"], wait_until="domcontentloaded", timeout=30_000
                )
            elif command == "click":
                await page.click(request["selector"], timeout=10_000)
            elif command == "input":
                event = request["input"]
                kind = event["kind"]
                if kind in {"move", "down", "up"}:
                    x, y = event["x"], event["y"]
                    viewport = page.viewport_size
                    if (
                        not 0 <= x < viewport["width"]
                        or not 0 <= y < viewport["height"]
                    ):
                        raise ValueError("Pointer outside viewport")
                    await page.mouse.move(x, y)
                    if kind == "down":
                        await page.mouse.down(button=event.get("button", "left"))
                        buttons.add(event.get("button", "left"))
                    elif kind == "up":
                        await page.mouse.up(button=event.get("button", "left"))
                        buttons.discard(event.get("button", "left"))
                elif kind in {"key_down", "key_up"}:
                    key = event["key"]
                    if not isinstance(key, str) or len(key) > 40:
                        raise ValueError("Invalid key")
                    if kind == "key_down":
                        await page.keyboard.down(key)
                        keys.add(key)
                    else:
                        await page.keyboard.up(key)
                        keys.discard(key)
                elif kind == "text":
                    if (
                        not isinstance(event.get("text"), str)
                        or len(event["text"]) > 1000
                    ):
                        raise ValueError("Text input exceeds limit")
                    await page.keyboard.insert_text(event["text"])
                elif kind == "wheel":
                    await page.mouse.wheel(
                        max(-2000, min(2000, event["dx"])),
                        max(-2000, min(2000, event["dy"])),
                    )
                elif kind == "release":
                    for key in list(keys):
                        await page.keyboard.up(key)
                    for button in list(buttons):
                        await page.mouse.up(button=button)
                    keys.clear()
                    buttons.clear()
                else:
                    raise ValueError("Unsupported input")
            elif command != "capture":
                raise ValueError(f"Unknown browser command '{command}'.")
            image = await page.screenshot(type="png")
            return {
                "ok": True,
                "image_b64": base64.b64encode(image).decode("ascii"),
                "capture": {
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "url": page.url,
                    "title": (await page.title())[:512],
                },
            }

        async def handle(reader, writer):
            try:
                raw = await asyncio.wait_for(reader.readline(), 5)
                if len(raw) > 32768:
                    raise ValueError("Browser request too large")
                async with lock:
                    response = await dispatch(json.loads(raw.decode()))
            except Exception as exc:
                response = {"ok": False, "error": str(exc)}
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(handle, path=SOCKET)
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
