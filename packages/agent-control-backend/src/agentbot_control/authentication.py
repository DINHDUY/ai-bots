"""Authentication admission and bounded password work outside the database worker."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from agentbot_control.repositories import auth_limits


class AuthenticationLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__("Too many authentication attempts. Try again later.")


class Authentication:
    def __init__(self, catalog, *, clock=time.time):
        self.catalog, self.clock = catalog, clock
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="control-auth")
        self._active = 0

    async def execute(self, operation: str, username: str, password: str, source: str):
        if self._active >= 4:
            raise AuthenticationLimited(1)
        account = auth_limits.key("account", username.strip())
        limits = [(auth_limits.key("register", source), 5, 3600)] if operation == "register" else [
            (account, 5, 60), (auth_limits.key("login", source), 100, 900),
        ]
        retry = await self.catalog.db.run(lambda db: auth_limits.reserve(db, limits, self.clock()))
        if retry or self._active >= 4:
            raise AuthenticationLimited(retry or 1)
        self._active += 1
        fn = self.catalog.register if operation == "register" else self.catalog.login
        future = asyncio.get_running_loop().run_in_executor(self._executor, fn, username, password)
        try:
            try:
                result = await asyncio.shield(future)
            except asyncio.CancelledError:
                # Retain admission until the CPU job ends even if the peer disconnects.
                while not future.done():
                    try:
                        await asyncio.shield(future)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not future.cancelled():
                    future.exception()
                raise
            if operation == "login":
                await self.catalog.db.run(lambda db: auth_limits.clear_account(db, account))
            return result
        finally:
            self._active -= 1

    def close(self) -> None:
        self._executor.shutdown(wait=True)
