"""External computers retain a scoped recovery path after workspace removal."""

from agentbot_control.common import stamp
from cloud_support import RID, FakeAzure, profile
from control_support import _app, _register
from fastapi.testclient import TestClient
from test_workspace_deletion_recovery import workspace_bot
from workspace_delete_support import deleted


def test_deleted_workspace_inventory_is_owner_recoverable(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    service = app.state.runtime.cloud
    with TestClient(app) as owner, TestClient(app) as other:
        uid = _register(owner)["id"]
        _register(other, "bea")
        wid, bid = workspace_bot(owner)
        p = profile().model_copy(update={"workspace_id": wid})
        service.profiles = {p.id: p}
        fake = FakeAzure()
        service.driver = lambda binding: fake
        with service.store.transaction() as db:
            db.execute(
                "INSERT INTO compute_profiles VALUES (?,?,?,?,1,?,1)",
                (p.id, wid, p.provider, p.name, p.model_dump_json()),
            )
            db.execute(
                "INSERT INTO computer_provider_bindings(id,bot_id,owner_id,provider,profile_id,profile_snapshot,resource_id,ownership,active,storage_ref,cleanup_state,created_at,updated_at) VALUES ('binding',?,?,?,?,?,?,'attached',0,'storage','retained_stopped',?,?)",
                (bid, uid, p.provider, p.id, p.model_dump_json(), RID, stamp(), stamp()),
            )
            # Older inactive inventory can be associated only through its profile.
            db.execute(
                "INSERT INTO computer_provider_bindings(id,owner_id,provider,profile_id,profile_snapshot,resource_id,ownership,active,storage_ref,cleanup_state,created_at,updated_at) VALUES ('profile-binding',?,?,?, ?,?,'attached',0,'storage','retained_stopped',?,?)",
                (uid, p.provider, p.id, p.model_dump_json(), RID + "-old", stamp(), stamp()),
            )
        _, result = deleted(owner, wid)
        assert result["retained"][0]["resource_id"] == RID
        response = owner.get(f"/api/workspaces/{wid}/compute-inventory")
        assert response.status_code == 200, response.text
        assert response.json()["computers"][0]["id"] == "binding"
        assert {r["id"] for r in response.json()["computers"]} == {"binding", "profile-binding"}
        assert other.get(f"/api/workspaces/{wid}/compute-inventory").status_code == 404
        reconciled = owner.post(
            f"/api/workspaces/{wid}/compute-inventory/binding/reconcile",
            json={"request_id": "inventory_check_01"},
        )
        assert reconciled.status_code == 200, reconciled.text
        assert fake.calls == []
        assert owner.get(f"/api/workspaces/{wid}/members").status_code == 404
        from agentbot_control.compute_profiles import load_profiles

        source = tmp_path / "profiles.json"
        source.write_text("[" + p.model_dump_json() + "]", encoding="utf-8")
        monkeypatch.setenv("CONTROL_COMPUTE_PROFILES", str(source))
        load_profiles(service.store)
        with service.store.transaction() as db:
            assert (
                db.execute("SELECT enabled FROM compute_profiles WHERE id=?", (p.id,)).fetchone()[0]
                == 0
            )
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
