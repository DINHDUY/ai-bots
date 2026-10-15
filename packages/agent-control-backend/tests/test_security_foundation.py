"""Authentication admission and encryption changes preserve recoverability."""

import asyncio
import base64
import hashlib
import json
import sqlite3
import threading

import pytest
from agentbot_control.authentication import Authentication, AuthenticationLimited
from agentbot_control.repositories.auth_limits import reserve
from agentbot_control.repositories.vault import SEALED_COLUMNS, rotate_batch
from agentbot_control.schemas import Conflict
from agentbot_control.store import Catalog, CatalogError
from agentbot_control.vault import KeyUnavailable, Vault
from control_support import _app as _app
from control_support import _register as _register
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


def test_login_backoff_is_bounded_and_has_retry_after(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        now = [1000.0]
        app.state.authentication.clock = lambda: now[0]
        for _ in range(5):
            assert (
                client.post(
                    "/api/login", json={"username": "unknown", "password": "wrong"}
                ).status_code
                == 401
            )
        blocked = client.post("/api/login", json={"username": "unknown", "password": "wrong"})
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
        now[0] += 61
        assert (
            client.post("/api/login", json={"username": "unknown", "password": "wrong"}).status_code
            == 401
        )


def test_source_window_is_not_reset_by_an_account_success():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE auth_limits (key TEXT PRIMARY KEY, attempts INTEGER, expires REAL)")
    assert reserve(db, [("source", 1, 60)], 10) == 0
    assert reserve(db, [("source", 1, 60)], 11) == 60
    assert reserve(db, [("source", 1, 60)], 71) == 0


def test_versioned_and_legacy_encryption_and_unknown_key(tmp_path):
    old = "previous-signing-secret"
    legacy = (
        Fernet(base64.urlsafe_b64encode(hashlib.sha256(old.encode()).digest()))
        .encrypt(b"credential")
        .decode()
    )
    vault = Vault(old)
    assert vault.unseal(legacy) == b"credential"
    previous = vault.seal(b"action-arguments")
    ring = tmp_path / "keys.json"
    ring.write_text(json.dumps({"active": "new", "keys": {"new": Fernet.generate_key().decode()}}))
    rotated = Vault(keyring=ring, legacy_secrets=(old,))
    assert rotated.unseal(previous) == b"action-arguments"
    assert rotated.unseal(legacy) == b"credential"
    assert rotated.unseal(rotated.seal(b"connector")) == b"connector"
    with pytest.raises(KeyUnavailable):
        Vault("unrelated").unseal(rotated.seal(b"data"))
    with pytest.raises(KeyUnavailable):
        rotated.unseal("v7:unknown:value")


def test_rotation_is_resumable_for_all_sealed_columns(tmp_path):
    old = "old-key"
    ring = tmp_path / "keys.json"
    ring.write_text(json.dumps({"active": "new", "keys": {"new": Fernet.generate_key().decode()}}))
    vault = Vault(keyring=ring, legacy_secrets=(old,))
    db = sqlite3.connect(":memory:")
    for table, column in SEALED_COLUMNS:
        db.execute(f'CREATE TABLE "{table}" ("{column}" TEXT)')
        before = Vault(old).seal((table + ":data").encode())
        db.execute(f'INSERT INTO "{table}" VALUES (?)', (before,))
        assert rotate_batch(db, vault, table, column, 0, dry_run=True)[2] == 1
        assert db.execute(f'SELECT "{column}" FROM "{table}"').fetchone()[0] == before
        assert rotate_batch(db, vault, table, column, 0)[2] == 1
        # Restarting at the beginning validates but does not rotate a current row again.
        assert rotate_batch(db, vault, table, column, 0)[2] == 0
        after = db.execute(f'SELECT "{column}" FROM "{table}"').fetchone()[0]
        assert vault.is_current(after) and vault.unseal(after) == (table + ":data").encode()


def test_scheduling_depends_on_codes_not_display_wording():
    assert Conflict("Completely different wording", code="human_control").waiting
    assert not Conflict("already running paused companion API key").waiting


def test_registration_limit_ignores_untrusted_forwarded_header(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        for i in range(6):
            response = client.post(
                "/api/register",
                json={"username": f"user{i}", "password": "test-password"},
                headers={"X-Forwarded-For": f"192.0.2.{i}"},
            )
            assert response.status_code == (200 if i < 5 else 429)


async def test_expensive_authentication_is_bounded_and_cancellation_drains(tmp_path):
    catalog = Catalog(tmp_path / "auth.sqlite", "test-only-secret")
    auth = Authentication(catalog)
    release = threading.Event()

    def blocked_login(username, password):
        assert release.wait(4)
        raise CatalogError("Invalid username or password.")

    catalog.login = blocked_login
    jobs = [
        asyncio.create_task(auth.execute("login", f"user{i}", "bad", "source")) for i in range(4)
    ]
    try:
        while auth._active < 4:
            await asyncio.sleep(0.001)
        with pytest.raises(AuthenticationLimited):
            await auth.execute("login", "fifth", "bad", "source")
        jobs[0].cancel()
        await asyncio.sleep(0)
        assert auth._active == 4 and not jobs[0].done()
        release.set()
        results = await asyncio.gather(*jobs, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert all(isinstance(result, CatalogError) for result in results[1:])
        assert auth._active == 0
    finally:
        release.set()
        await asyncio.gather(*jobs, return_exceptions=True)
        auth.close()
        catalog.close()
