import os
import sqlite3

import pytest
from agentbot_control.app import ensure_secret, load_dotenv
from agentbot_control.store import Catalog
from control_support import RecordingAdapter as RecordingAdapter
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _key as _key
from control_support import _register as _register
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_register_login_logout_and_closed_registration(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        assert client.get("/api/me").json()["username"] == "ada"
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/me").status_code == 401
        logged_in = client.post("/api/login", json={"username": "ada", "password": "password1"})
        assert logged_in.status_code == 200
        assert client.get("/api/me").status_code == 200

    closed, _, _, _ = _app(tmp_path / "closed", allow_register=False)
    with TestClient(closed) as client:
        response = client.post("/api/register", json={"username": "bea", "password": "password1"})
        assert response.status_code == 403


def test_owner_cannot_see_another_users_bot(tmp_path) -> None:
    app, sandboxes, sessions, _ = _app(tmp_path)
    with TestClient(app) as alice, TestClient(app) as bob:
        _register(alice, "ada")
        created = _create_bot(alice)
        assert created.status_code == 201
        bot_id = created.json()["id"]
        patched = alice.patch(f"/api/bots/{bot_id}", json={"name": "Editor"})
        assert patched.status_code == 200
        assert patched.json()["name"] == "Editor"
        assert patched.json()["instructions"] == "be brief"

        _register(bob, "bea")
        assert bob.get(f"/api/bots/{bot_id}").status_code == 404
        assert bob.patch(f"/api/bots/{bot_id}", json={"name": "Stolen"}).status_code == 404
        assert bob.delete(f"/api/bots/{bot_id}").status_code == 404
        assert bob.get("/api/bots").json() == []
        with bob.websocket_connect("/ws") as socket:
            socket.send_json({"action": "start", "bot_id": bot_id, "prompt": "hi"})
            assert socket.receive_json()["payload"] == "Bot not found."

        assert alice.delete(f"/api/bots/{bot_id}").status_code == 200
        assert sandboxes.created == 0  # Catalog deletion does not create a computer.
        assert sandboxes.closed == []
        assert not (sessions._directory / f"{bot_id}.json").exists()


def test_default_prompt_is_optional_owned_and_persisted(tmp_path) -> None:
    app, sandboxes, _, _ = _app(tmp_path)
    prompt = "Summarize today's updates.\nList the next steps."
    with TestClient(app) as alice, TestClient(app) as bob:
        _register(alice)
        bot = _create_bot(alice).json()
        assert bot["default_prompt"] == ""
        path = f"/api/bots/{bot['id']}"
        saved = alice.patch(path, json={"default_prompt": f"  {prompt}\n"})
        assert saved.status_code == 200
        assert saved.json()["default_prompt"] == prompt
        assert saved.json()["instructions"] == "be brief"
        assert alice.patch(path, json={"name": "Editor"}).json()["default_prompt"] == prompt
        assert alice.get(path).json()["messages"] == []
        other = _create_bot(alice, default_prompt="Other task").json()
        assert other["default_prompt"] == "Other task"
        _register(bob, "bea")
        assert bob.patch(path, json={"default_prompt": "Changed"}).status_code == 404
        assert bob.get(path).status_code == 404
        for blank in ("", " \t\n "):
            assert alice.patch(path, json={"default_prompt": blank}).json()["default_prompt"] == ""
        assert alice.patch(path, json={"default_prompt": prompt}).status_code == 200
        cookies = dict(alice.cookies)
    restored, _, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        client.cookies.update(cookies)
        assert client.get(path).json()["default_prompt"] == prompt
        assert {bot["id"]: bot["default_prompt"] for bot in client.get("/api/bots").json()} == {
            bot["id"]: prompt,
            other["id"]: "Other task",
        }
    assert sandboxes.created == 0


@pytest.mark.parametrize(
    "invalid",
    [None, 42, {}, ["task"], "x" * 8001],
    ids=["null", "number", "object", "list", "too_long"],
)
def test_default_prompt_rejects_invalid_values(tmp_path, invalid) -> None:
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, default_prompt="Keep this").json()
        path = f"/api/bots/{bot['id']}"
        assert client.patch(path, json={"default_prompt": invalid}).status_code == 400
        assert client.get(path).json()["default_prompt"] == "Keep this"
        assert _create_bot(client, default_prompt=invalid).status_code == 400


def test_chat_round_trip_passes_instructions(tmp_path) -> None:
    app, _, _, adapter = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        _register(client)
        created = _create_bot(client)
        bot_id = created.json()["id"]
        with client.websocket_connect("/ws") as socket:
            socket.send_json(
                {"action": "start", "framework": "microsoft", "bot_id": bot_id, "prompt": "hi"}
            )
            assert socket.receive_json()["payload"] == "Start a turn with bot_id and prompt."
            socket.send_json({"action": "start", "bot_id": bot_id, "prompt": "hi"})
            assert socket.receive_json()["event"] == "session"
            approval = socket.receive_json()
            assert approval["event"] == "approval_required"
            socket.send_json(
                {"action": "approve", "approval_id": approval["approval_id"], "decision": "approve"}
            )
            assert socket.receive_json()["payload"] == "yes"
            assert socket.receive_json()["event"] == "done"
        assert adapter.instructions == "be brief"
        assert adapter.model is not None
        assert adapter.model.api_key == "sk-test-key-1234"
        assert adapter.model.model == "gpt-4.1"
        detail = client.get(f"/api/bots/{bot_id}").json()
        assert [item["content"] for item in detail["messages"]] == ["hi", "yes"]


def test_ensure_secret_fills_blank_dotenv(tmp_path, monkeypatch) -> None:
    example = tmp_path / ".env.example"
    example.write_text("AGENTBOT_SECRET=\nALLOW_REGISTER=1\n", encoding="utf-8")
    env_path = tmp_path / ".env"
    ensure_secret(env_path, example)
    monkeypatch.delenv("AGENTBOT_SECRET", raising=False)
    monkeypatch.delenv("ALLOW_REGISTER", raising=False)
    load_dotenv(env_path)
    secret = os.environ["AGENTBOT_SECRET"]
    monkeypatch.setenv("AGENTBOT_SECRET", secret)
    monkeypatch.setenv("ALLOW_REGISTER", os.environ["ALLOW_REGISTER"])
    assert len(secret) >= 32
    assert os.environ["ALLOW_REGISTER"] == "1"
    ensure_secret(env_path, example)
    assert (
        env_path.read_text(encoding="utf-8").split("AGENTBOT_SECRET=", 1)[1].splitlines()[0]
        == secret
    )


def test_cors_preflight_allows_listed_origin_only(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path, cors_origins=["http://127.0.0.1:5173"])
    headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    with TestClient(app) as client:
        allowed = client.options(
            "/api/bots",
            headers={**headers, "Origin": "http://127.0.0.1:5173"},
        )
        assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        assert allowed.headers["access-control-allow-credentials"] == "true"
        denied = client.options("/api/bots", headers={**headers, "Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in denied.headers


def test_foreign_origin_is_rejected(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path, cors_origins=["http://127.0.0.1:5173"])
    with TestClient(app) as client:
        _register(client)
        response = client.post(
            "/api/bots",
            json={"name": "Writer", "framework": "echo", "instructions": ""},
            headers={"Origin": "http://evil.example"},
        )
        assert response.status_code == 403


def test_non_json_body_is_rejected(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/register",
            content="username=ada&password=password1",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 415


def test_websocket_rejects_foreign_origin(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path, cors_origins=["http://127.0.0.1:5173"])
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}):
                pass


def test_cookie_samesite_none_requires_secure(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COOKIE_SAMESITE", "none")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        _app(tmp_path / "insecure")


def test_cookie_samesite_none_sets_secure_cookie(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COOKIE_SAMESITE", "none")
    monkeypatch.setenv("COOKIE_SECURE", "1")
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/register", json={"username": "ada", "password": "password1"})
        cookie = response.headers["set-cookie"].lower()
        assert "samesite=none" in cookie
        assert "secure" in cookie


def test_wildcard_cors_origin_is_rejected(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        _app(tmp_path, cors_origins=["*"])


def test_credentials_are_encrypted_and_owned(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as alice, TestClient(app) as bob:
        _register(alice, "ada")
        created = _key(
            alice, "azure_foundry", endpoint="https://example.services.ai.azure.com/openai/v1/"
        )
        assert created["key_hint"] == "1234"
        assert created["endpoint"].endswith("/openai/v1")
        listed = alice.get("/api/credentials").json()
        assert listed[0]["id"] == created["id"]
        assert "secret" not in listed[0]
        connection = sqlite3.connect(tmp_path / "control.sqlite")
        secret = connection.execute("SELECT secret FROM credentials").fetchone()[0]
        connection.close()
        assert "sk-test-key-1234" not in secret

        _register(bob, "bea")
        assert bob.get("/api/credentials").json() == []
        assert bob.delete(f"/api/credentials/{created['id']}").status_code == 404
        assert (
            bob.patch(f"/api/credentials/{created['id']}", json={"label": "Stolen"}).status_code
            == 404
        )

        rotated = alice.patch(
            f"/api/credentials/{created['id']}",
            json={"api_key": "rotated-key-9999"},
        )
        assert rotated.status_code == 200
        assert rotated.json()["key_hint"] == "9999"
        assert "rotated-key-9999" not in rotated.text


def test_framework_must_match_provider_and_foundry_url(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        openai = _key(client, "openai")
        mismatch = client.post(
            "/api/bots",
            json={
                "name": "Writer",
                "framework": "anthropic",
                "instructions": "",
                "credential_id": openai["id"],
                "model": "claude-sonnet-5",
            },
        )
        assert mismatch.status_code == 400
        assert "cannot use" in mismatch.json()["detail"]
        bare = client.post(
            "/api/credentials",
            json={
                "provider": "azure_foundry",
                "label": "grok",
                "api_key": "sk-test-key-1234",
                "endpoint": "http://example.com",
            },
        )
        assert bare.status_code == 400
        embedded = client.post(
            "/api/credentials",
            json={
                "provider": "azure_foundry",
                "label": "grok",
                "api_key": "sk-test-key-1234",
                "endpoint": "https://user:pass@example.services.ai.azure.com/openai/v1",
            },
        )
        assert embedded.status_code == 400


def test_in_use_key_and_missing_key(tmp_path) -> None:
    app, _, _, adapter = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        created = _create_bot(client, framework="microsoft", model="grok-4")
        bot_id = created.json()["id"]
        credential_id = created.json()["credential_id"]
        blocked = client.delete(f"/api/credentials/{credential_id}")
        assert blocked.status_code == 409
        connection = sqlite3.connect(tmp_path / "control.sqlite")
        connection.execute("UPDATE bots SET credential_id = NULL WHERE id = ?", (bot_id,))
        connection.commit()
        connection.close()
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"action": "start", "bot_id": bot_id, "prompt": "hi"})
            assert "no API key" in socket.receive_json()["payload"]
        assert adapter.model is None


def test_migrates_bots_created_before_credentials(tmp_path) -> None:
    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE bots (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            name TEXT NOT NULL,
            framework TEXT NOT NULL,
            instructions TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT INTO users VALUES ('u1', 'ada', 'hash', '2026-01-01T00:00:00+00:00')"
    )
    connection.execute(
        "INSERT INTO bots VALUES ('b1', 'u1', 'Writer', 'microsoft', '', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    catalog = Catalog(path, "test-secret")
    bot = catalog.get_bot("u1", "b1")
    assert bot is not None
    assert bot.credential_id is None
    assert bot.model == ""
    assert bot.default_prompt == ""
    updated = catalog.update_bot("u1", "b1", default_prompt="Migrated task")
    assert updated.default_prompt == "Migrated task"
    catalog.close()
    reopened = Catalog(path, "test-secret")
    assert reopened.get_bot("u1", "b1").default_prompt == "Migrated task"
    reopened.close()


def test_websocket_requires_sign_in(tmp_path) -> None:
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["payload"] == "Sign in required."
