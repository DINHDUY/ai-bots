"""Owned immutable blobs; bytes are never served as application-origin HTML."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentbot_control.event_store import identifier, stamp
from agentbot_control.schemas import Conflict


class BlobStore:
    def __init__(self, store):
        self.store = store
        self.directory = store.blobs / "artifacts"
        self.directory.mkdir(parents=True, exist_ok=True)

    def reserve(self, bot_id, session_id, path, revision, size, mime):
        if size > 64 * 1024 * 1024:
            raise Conflict("File exceeds 64 MiB.")
        blob_id = identifier("blob")
        with self.store.transaction() as db:
            used = db.execute(
                "SELECT COALESCE(SUM(f.size),0) FROM file_blobs f JOIN bot_streams b ON b.bot_id=f.bot_id WHERE b.workspace_id=(SELECT workspace_id FROM bot_streams WHERE bot_id=?)",
                (bot_id,),
            ).fetchone()[0]
            captures = db.execute(
                "SELECT COALESCE(SUM(size),0) FROM capture_storage WHERE state!='removed' AND workspace_id=(SELECT workspace_id FROM bot_streams WHERE bot_id=?)",
                (bot_id,),
            ).fetchone()[0]
            if used + captures + size > self.store.blob_limit:
                raise Conflict("Workspace blob quota exceeded.")
            db.execute(
                "INSERT INTO file_blobs VALUES (?,?,?,?,?,?,?,?)",
                (blob_id, bot_id, session_id, path, revision, size, mime, stamp()),
            )
        return blob_id

    def get(self, bot_id, blob_id):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM file_blobs WHERE id=? AND bot_id=?", (blob_id, bot_id)
            ).fetchone()
        path = self.directory / blob_id
        return (dict(row), path) if row and path.is_file() else None

    def discard(self, blob_id):
        # Only server-generated IDs are accepted by internal callers.
        (self.directory / blob_id).unlink(missing_ok=True)
        with self.store.transaction() as db:
            db.execute("DELETE FROM file_blobs WHERE id=?", (blob_id,))

    def prune(self):
        cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        with self.store.transaction() as db:
            expired = [
                r[0] for r in db.execute("SELECT id FROM file_blobs WHERE created_at<?", (cutoff,))
            ]
            for blob_id in expired:
                db.execute("DELETE FROM uploads WHERE blob_id=?", (blob_id,))
                db.execute("DELETE FROM file_blobs WHERE id=?", (blob_id,))
                db.execute(
                    "DELETE FROM search_index WHERE resource_id=? AND kind='file'",
                    (blob_id,),
                )
        for blob_id in expired:
            (self.directory / blob_id).unlink(missing_ok=True)

    def recover(self):
        # Startup runs under the deployment process lock; no active transfers exist.
        with self.store.transaction() as db:
            rows = db.execute("SELECT id FROM file_blobs").fetchall()
            for row in rows:
                if not (self.directory / row[0]).is_file():
                    db.execute("DELETE FROM uploads WHERE blob_id=?", (row[0],))
                    db.execute("DELETE FROM file_blobs WHERE id=?", (row[0],))
            retained = {r[0] for r in db.execute("SELECT id FROM file_blobs")}
            retained.update(
                r[0]
                for r in db.execute(
                    "SELECT resource_id FROM workspace_cleanup_items WHERE kind='artifact' AND state!='complete'"
                )
            )
        for path in self.directory.iterdir():
            if path.is_file() and path.name not in retained:
                path.unlink()
        with self.store.transaction() as db:
            # Process-lock startup has no surviving writers; staging was reclaimed above.
            db.execute("DELETE FROM workspace_file_writers")

    def adopt(self, source: Path, bot_id, session, path, revision, size, mime):
        blob_id = self.reserve(bot_id, session, path, revision, size, mime)
        source.replace(self.directory / blob_id)
        return blob_id
