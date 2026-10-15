import json

import pytest
from agentbot_control.app import create_app
from agentbot_control.backup import create, restore
from agentbot_control.process_lock import ProcessLock
from agentbot_control.store import Catalog


def test_offline_snapshot_restores_keys_sessions_blobs_and_stays_fenced(tmp_path, monkeypatch):
    database = tmp_path / "live.sqlite"
    catalog = Catalog(database, "test-only-signing-secret")
    user, token = catalog.register("backup-user", "test-only-password")
    credential = catalog.create_credential(user.id, "openai", "key", "test-only-api-key")
    blobs = database.with_suffix(".blobs")
    (blobs / "artifacts").mkdir(parents=True)
    (blobs / "artifacts" / "blob-id").write_bytes(b"retained artifact")
    snapshot = tmp_path / "snapshot"
    lock = ProcessLock(database.with_suffix(".runtime.lock"))
    lock.acquire()
    try:
        with pytest.raises(RuntimeError):
            create(database, snapshot)
        assert not snapshot.exists()
    finally:
        lock.release()
    assert create(database, snapshot)["files"] == 2
    catalog.close()
    restored = restore(snapshot, tmp_path / "restored")
    copied = Catalog(restored, "test-only-signing-secret")
    try:
        assert copied.user_from_token(token) == user
        assert copied.list_credentials(user.id) == [credential]
        with copied.db.transaction(write=False) as db:
            sealed = db.execute("SELECT secret FROM credentials").fetchone()[0]
            assert copied.unseal(sealed) == b"test-only-api-key"
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (restored.with_suffix(".blobs") / "artifacts/blob-id").read_bytes() == b"retained artifact"
        def forbidden_kernel(**kwargs):
            pytest.fail("A fenced restore must not construct provider or session integrations")
        monkeypatch.setattr("agentbot_control.app.build_kernel", forbidden_kernel)
        with pytest.raises(RuntimeError, match="Verification restore is fenced"):
            create_app(control_db=restored, secret="test-only-signing-secret")
    finally:
        copied.close()
    assert json.loads((snapshot / "manifest.json").read_text())["keys_included"] is False


def test_incomplete_or_modified_backup_is_rejected_before_destination_creation(tmp_path):
    catalog = Catalog(tmp_path / "live.sqlite", "test-only-signing-secret")
    catalog.close()
    snapshot = tmp_path / "snapshot"
    create(tmp_path / "live.sqlite", snapshot)
    with (snapshot / "control.sqlite").open("ab") as output:
        output.write(b"corrupt")
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="integrity"):
        restore(snapshot, destination)
    assert not destination.exists()
