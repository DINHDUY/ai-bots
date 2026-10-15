"""One SQLite connection for the control plane."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from agentbot_control.common import stamp
from agentbot_control.notifications import CommitNotifications
from agentbot_control.schemas import Conflict

_WRITE = {"INSERT", "UPDATE", "DELETE", "REPLACE"}
T = TypeVar("T")


class DatabaseBusy(RuntimeError):
    """Admission to the bounded database worker was rejected; retry is safe."""


class CatalogConnection:
    """Lets Catalog keep execute/commit while sharing EventStore's autocommit connection.

    Writes issued before commit() share one IMMEDIATE transaction. Reads do not.
    """

    def __init__(self, database: Database) -> None:
        self.database = database
        self._open = False

    def __enter__(self):
        with self.database.lock:
            if not self._open:
                self.database.connection.execute("BEGIN IMMEDIATE")
                self._open = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self._rollback()
        else:
            self.commit()
        return False

    def execute(self, sql, parameters=()):
        verb = sql.lstrip().split(None, 1)[0].upper()
        with self.database.lock:
            if verb not in _WRITE and not self._open:
                return self.database.connection.execute(sql, parameters)
            try:
                if not self._open:
                    self.database.connection.execute("BEGIN IMMEDIATE")
                    self._open = True
                return self.database.connection.execute(sql, parameters)
            except Exception as exc:
                self._rollback()
                if isinstance(exc, sqlite3.IntegrityError) and str(exc) == "workspace_deleted":
                    raise Conflict("Workspace was deleted.", code="workspace_deleted") from exc
                raise

    def commit(self) -> None:
        with self.database.lock:
            if self._open:
                self.database.connection.execute("COMMIT")
                self._open = False

    def _rollback(self) -> None:
        if self._open:
            self.database.connection.execute("ROLLBACK")
            self._open = False


class Database:
    def __init__(self, path: Path, *, migrate: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.notifications = CommitNotifications()
        self._transaction_state = threading.local()
        self._capacity = threading.BoundedSemaphore(128)
        self.pending = 0
        self.jobs_completed = 0
        self.queue_seconds = 0.0
        self.work_seconds = 0.0
        self._closed = False
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="control-db")
        if migrate:
            self.migrate()

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)
        self.connection.close()

    @contextmanager
    def transaction(self, *, write=True):
        changed = set()
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            self._transaction_state.changed = changed
            try:
                yield self.connection
                self.connection.execute("COMMIT")
            except BaseException as exc:
                self.connection.execute("ROLLBACK")
                changed.clear()
                if isinstance(exc, sqlite3.IntegrityError) and str(exc) == "workspace_deleted":
                    raise Conflict("Workspace was deleted.", code="workspace_deleted") from exc
                raise
            finally:
                self._transaction_state.changed = None
        if changed:
            self.notifications.publish(changed)

    def changed(self, bot_id: str) -> None:
        changed = getattr(self._transaction_state, "changed", None)
        if changed is None:
            raise RuntimeError("Events must be appended inside a transaction")
        changed.add(bot_id)

    async def offload(self, fn: Callable[[], T]) -> T:
        """Bound worker admission and settle started work before cancelling its waiter."""
        if self._closed or not self._capacity.acquire(blocking=False):
            raise DatabaseBusy("Database work queue is full or shutting down")
        self.pending += 1
        context = copy_context()
        queued = perf_counter()

        def work() -> T:
            started = perf_counter()
            self.queue_seconds += started - queued
            try:
                return context.run(fn)
            finally:
                self.jobs_completed += 1
                self.work_seconds += perf_counter() - started
                self.pending -= 1
                self._capacity.release()

        try:
            future = asyncio.get_running_loop().run_in_executor(self._executor, work)
        except BaseException:
            self.pending -= 1
            self._capacity.release()
            raise
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Executor cancellation cannot establish a rollback. Preserve cancellation
            # only after the operation has an observable final outcome.
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

    async def run(self, fn):
        """Run fn(connection) inside one transaction on the single database worker."""

        def work():
            with self.transaction() as db:
                return fn(db)

        return await self.offload(work)

    async def read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        def work() -> T:
            with self.transaction(write=False) as db:
                return fn(db)

        return await self.offload(work)

    def migrate(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for migration in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
            rebuild = migration.name in {
                "008_workspaces.sql",
                "016_workspace_channels.sql",
                "019_shared_workspace_computer.sql",
            }
            if (
                rebuild
                and self.connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (migration.name,)
                ).fetchone()
            ):
                continue
            if rebuild:
                self.connection.execute("PRAGMA foreign_keys=OFF")
            with self.transaction() as db:
                if db.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (migration.name,)
                ).fetchone():
                    if rebuild:
                        self.connection.execute("PRAGMA foreign_keys=ON")
                    continue
                statement = ""
                if migration.name == "022_workspace_deletion_repair.sql":
                    from agentbot_control.repositories.schema_upgrades import (
                        workspace_writer_columns,
                    )

                    workspace_writer_columns(db)
                for fragment in migration.read_text(encoding="utf-8-sig").split(";"):
                    statement += fragment + ";"
                    if sqlite3.complete_statement(statement):
                        db.execute(statement)
                        statement = ""
                db.execute(
                    "INSERT INTO schema_migrations VALUES (?,?)",
                    (migration.name, stamp()),
                )
                if rebuild and db.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("Workspace migration failed foreign-key validation")
            if rebuild:
                self.connection.execute("PRAGMA foreign_keys=ON")
        self._upgrade_bots()

    def _upgrade_bots(self) -> None:
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(bots)")}
        if "credential_id" not in columns:
            self.connection.execute(
                "ALTER TABLE bots ADD COLUMN credential_id TEXT REFERENCES credentials(id)"
            )
        if "model" not in columns:
            self.connection.execute("ALTER TABLE bots ADD COLUMN model TEXT NOT NULL DEFAULT ''")
        if "default_prompt" not in columns:
            self.connection.execute(
                "ALTER TABLE bots ADD COLUMN default_prompt TEXT NOT NULL DEFAULT ''"
            )
