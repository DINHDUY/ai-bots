"""Commit visibility, cancellation, and catch-up must not depend on a polling timer."""

import asyncio
import threading

import pytest
from agentbot_control.db import Database, DatabaseBusy


async def test_notifications_follow_commit_and_rollback_stays_silent(tmp_path):
    database = Database(tmp_path / "catalog.sqlite")
    try:
        with database.notifications.subscribe("bot") as changed:
            def rollback(connection):
                database.changed("bot")
                raise ValueError("rollback")
            with pytest.raises(ValueError):
                await database.run(rollback)
            await asyncio.sleep(0)
            assert not changed.is_set()
            await database.run(lambda connection: database.changed("bot"))
            await asyncio.wait_for(changed.wait(), 1)
            # Hundreds of writes coalesce; subscribers retain a single signal.
            for _ in range(100):
                await database.run(lambda connection: database.changed("bot"))
            assert changed.is_set()
    finally:
        database.close()


async def test_read_transaction_and_worker_do_not_block_event_loop(tmp_path):
    database = Database(tmp_path / "catalog.sqlite")
    entered, release = threading.Event(), threading.Event()
    statements = []
    database.connection.set_trace_callback(statements.append)
    try:
        main_thread = threading.get_ident()
        def read(connection):
            entered.set()
            assert release.wait(3)
            return threading.get_ident(), connection.execute("SELECT 1").fetchone()[0]
        task = asyncio.create_task(database.read(read))
        while not entered.is_set():
            await asyncio.sleep(0)
        # This cannot execute if a synchronous transaction is holding the loop.
        release.set()
        worker_thread, value = await task
        assert value == 1 and worker_thread != main_thread
        assert "BEGIN" in statements and "BEGIN IMMEDIATE" not in statements
    finally:
        release.set()
        database.close()


async def test_cancelled_waiter_settles_committed_operation(tmp_path):
    database = Database(tmp_path / "catalog.sqlite")
    entered, release = threading.Event(), threading.Event()
    try:
        def write(connection):
            entered.set()
            assert release.wait(3)
            connection.execute("INSERT INTO runtime_settings VALUES ('cancel-test','committed')")
        task = asyncio.create_task(database.run(write))
        while not entered.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await database.read(lambda db: db.execute("SELECT value FROM runtime_settings WHERE key='cancel-test'").fetchone()[0]) == "committed"
        assert database.pending == 0
    finally:
        release.set()
        database.close()


async def test_bounded_admission_rejects_before_submitting(tmp_path):
    database = Database(tmp_path / "catalog.sqlite")
    try:
        for _ in range(128):
            assert database._capacity.acquire(blocking=False)
        with pytest.raises(DatabaseBusy):
            await database.read(lambda db: None)
        assert database.pending == 0
    finally:
        database.close()
