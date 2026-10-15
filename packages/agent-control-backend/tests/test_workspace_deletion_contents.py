"""Populated dependency graphs and storage targets are removed together."""

from agentbot_control.common import stamp
from control_support import _app, _register
from fastapi.testclient import TestClient
from workflow_import_support import draft, imported
from workspace_delete_support import cleaned, deleted
from workspace_services_support import png


def insert(db, table, **values):
    db.execute(
        f"INSERT INTO {table}({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
        tuple(values.values()),
    )


def test_populated_workspace_content_and_capture_cleanup(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        uid = _register(client)["id"]
        source = imported(client, draft(client, count=1))
        wid, bid = source["workspace_id"], source["bots"][0]["bot_id"]
        runtime = app.state.runtime
        runtime.accepting = False  # Keep queued synthetic automation unclaimed.
        now = stamp()
        runtime.store.captures.store_image(bid, None, png(), {"surface_kind": "browser"})
        blob = runtime.files.blobs.reserve(bid, "closed", "note.txt", "revision", 7, "text/plain")
        blob_path = runtime.files.blobs.directory / blob
        blob_path.write_bytes(b"private")
        with runtime.store.transaction() as db:
            insert(
                db,
                "computer_sessions",
                id="closed",
                bot_id=bid,
                generation=1,
                status="closed",
                created_at=now,
                updated_at=now,
            )
            insert(
                db,
                "runs",
                id="run",
                bot_id=bid,
                user_id=uid,
                status="completed",
                prompt="private",
                config="{}",
                trigger="user",
                created_at=now,
                updated_at=now,
                session_id="closed",
            )
            insert(
                db,
                "actions",
                id="action",
                run_id="run",
                name="bash",
                argument_digest="digest",
                status="completed",
            )
            insert(
                db,
                "approvals",
                id="approval",
                bot_id=bid,
                run_id="run",
                action_id="action",
                action="bash",
                detail="private",
                status="approved",
                expires_at=now,
                created_at=now,
            )
            insert(db, "messages", id="message", bot_id=bid, seq=1, role="user", content="private")
            insert(
                db,
                "control_leases",
                id="lease",
                bot_id=bid,
                session_id="closed",
                generation=1,
                user_id=uid,
                login_digest="digest",
                client_id="client",
                surface="browser",
                surface_id="surface",
                viewport_revision="rev",
                fence=1,
                expires_at=now,
                status="released",
            )
            insert(
                db,
                "recordings",
                id="recording",
                bot_id=bid,
                user_id=uid,
                lease_id="lease",
                state="stopped",
                steps="[]",
                created_at=now,
            )
            insert(
                db,
                "skill_versions",
                id="skill",
                bot_id=bid,
                name="skill",
                description="private",
                parameters="{}",
                steps="[]",
                created_at=now,
            )
            insert(
                db,
                "connections",
                id="connection",
                bot_id=bid,
                owner_id=uid,
                provider="sample",
                repository="repo",
                secret="synthetic-secret",
                version=1,
                status="ready",
            )
            insert(db, "installations", bot_id=bid, kind="skill", resource_id="skill")
            insert(db, "groups", id="group", workspace_id=wid, name="Group")
            insert(db, "group_members", group_id="group", bot_id=bid)
            insert(
                db,
                "group_messages",
                id="group-message",
                group_id="group",
                actor_id=uid,
                bot_id=bid,
                content="private",
                created_at=now,
            )
            insert(
                db,
                "routines",
                id="routine",
                workspace_id=wid,
                principal_id=uid,
                version=1,
                enabled=0,
            )
            insert(
                db,
                "routine_versions",
                routine_id="routine",
                version=1,
                definition="{}",
                created_at=now,
            )
            insert(
                db,
                "routine_jobs",
                id="job",
                routine_id="routine",
                version=1,
                occurrence="one",
                state="queued",
                data="{}",
                bot_id=bid,
                created_at=now,
                updated_at=now,
            )
            insert(
                db,
                "webhook_deliveries",
                routine_id="routine",
                delivery_id="webhook",
                digest="digest",
                created_at=now,
            )
            insert(
                db,
                "channel_threads",
                id="thread",
                workspace_id=wid,
                principal_id=uid,
                deadline=now,
                created_at=now,
            )
            insert(
                db,
                "channel_messages",
                id="channel-message",
                workspace_id=wid,
                thread_id="thread",
                seq=1,
                sender_name="Writer",
                principal_id=uid,
                kind="request",
                body="private",
                request_key="key",
                digest="digest",
                created_at=now,
            )
            insert(
                db,
                "channel_deliveries",
                id="delivery",
                thread_id="thread",
                message_id="channel-message",
                target_bot_id=bid,
                target_enrollment="enrollment",
                state="queued",
                depth=0,
                created_at=now,
            )
            insert(db, "channel_dispatch_checks", delivery_id="delivery", last_checked=now)
            insert(
                db,
                "channel_continuations",
                id="continuation",
                thread_id="thread",
                bot_id=bid,
                enrollment_id="enrollment",
                source_run_id="run",
                requests="[]",
                summary="private",
                wait_mode="all",
                run_mode="communication",
                state="waiting",
                created_at=now,
            )
            insert(db, "channel_run_context", run_id="run", thread_id="thread", depth=0)
            insert(
                db, "channel_automation_roots", kind="routine", origin_id="job", thread_id="thread"
            )
            insert(
                db,
                "channel_artifact_grants",
                id="grant",
                message_id="channel-message",
                workspace_id=wid,
                blob_id=blob,
                revision="revision",
                published_by=bid,
            )
            insert(
                db,
                "uploads",
                id="upload",
                bot_id=bid,
                user_id=uid,
                session_id="closed",
                generation=1,
                blob_id=blob,
                path="note.txt",
                revision="revision",
                created_at=now,
            )
            insert(
                db,
                "share_grants",
                id="share",
                bot_id=bid,
                recipient_id=uid,
                surfaces="[]",
                artifacts="[]",
                expires_at=now,
            )
            insert(
                db,
                "lifecycle_operations",
                id="operation",
                bot_id=bid,
                request_id="old-close",
                fingerprint="digest",
                session_id="closed",
                operation="close",
                status="completed",
                result="{}",
                created_at=now,
            )
            db.execute(
                "INSERT INTO search_index VALUES ('message',?,'message','Title','private')", (bid,)
            )
        _, result = deleted(client, wid)
        assert result["counts"]["messages"] == result["counts"]["channel_messages"] == 1
        assert result["counts"]["captures"] == result["counts"]["uploads"] == 1
        cleaned(client)
        assert not blob_path.exists()
        with runtime.store.transaction() as db:
            for table in (
                "bots",
                "runs",
                "actions",
                "approvals",
                "messages",
                "control_leases",
                "recordings",
                "skill_versions",
                "connections",
                "installations",
                "groups",
                "group_members",
                "group_messages",
                "routines",
                "routine_versions",
                "routine_jobs",
                "webhook_deliveries",
                "channel_threads",
                "channel_messages",
                "channel_deliveries",
                "channel_dispatch_checks",
                "channel_continuations",
                "channel_run_context",
                "channel_automation_roots",
                "channel_artifact_grants",
                "uploads",
                "share_grants",
                "capture_records",
                "capture_storage",
                "file_blobs",
                "search_index",
            ):
                assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
            assert (
                db.execute("SELECT COUNT(*) FROM workspace_deleted_operations").fetchone()[0] == 1
            )
            assert db.execute("SELECT COUNT(*) FROM workflow_import_receipts").fetchone()[0] == 1
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
