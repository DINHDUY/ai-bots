"""Password hashing and signed session cookies."""

from __future__ import annotations

import hashlib
import hmac
import secrets

COOKIE_NAME = "agentbot_session"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n_text, r_text, p_text, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n_text),
            r=int(r_text),
            p=int(p_text),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def sign_session(session_id: str, secret: str) -> str:
    mac = hmac.new(
        secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{session_id}.{mac}"


def unsign_session(token: str, secret: str) -> str | None:
    session_id, separator, mac = token.rpartition(".")
    if not separator or not session_id or not mac:
        return None
    expected = hmac.new(
        secret.encode("utf-8"), session_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    return session_id
