"""command_receipts."""

from agentbot_control.common import fingerprint, packed


def find(db, bot_id, request_id):
    return db.execute(
        "SELECT * FROM command_receipts WHERE bot_id=? AND request_id=?",
        (bot_id, request_id),
    ).fetchone()


def save(db, bot_id, request_id, body, response):
    db.execute(
        "INSERT INTO command_receipts VALUES (?,?,?,?)",
        (bot_id, request_id, fingerprint(body), packed(response)),
    )


def replace_response(db, bot_id, request_id, response_json):
    db.execute(
        "UPDATE command_receipts SET response=? WHERE bot_id=? AND request_id=?",
        (response_json, bot_id, request_id),
    )
