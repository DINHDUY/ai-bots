"""runs, actions, and run plans."""


def active(db, bot_id):
    return db.execute(
        "SELECT * FROM runs WHERE bot_id=? AND status IN ('preparing','running','awaiting_approval','stopping')",
        (bot_id,),
    ).fetchone()


def get(db, run_id):
    return db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()


def bot_id_for(db, run_id):
    return db.execute("SELECT bot_id FROM runs WHERE id=?", (run_id,)).fetchone()
