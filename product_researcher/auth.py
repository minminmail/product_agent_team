"""Minimal email + password auth for the dashboard.

SQLite-backed (no external deps): users with salted PBKDF2 password hashes, and
server-side sessions referenced by an opaque token (stored in an httpOnly
cookie). Intended for a self-hosted/local dashboard — see the security notes in
the README before exposing it publicly.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time

_DB_PATH: str | None = None
_PBKDF2_ITER = 200_000
_SESSION_TTL = 60 * 60 * 24 * 14  # 14 days
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


def init_db(path: str) -> None:
    """Create the users/sessions/tokens tables if needed. Call once at startup."""
    global _DB_PATH
    _DB_PATH = path
    con = _conn()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            email      TEXT PRIMARY KEY,
            pw_hash    TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions(
            token      TEXT PRIMARY KEY,
            email      TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tokens(
            token      TEXT PRIMARY KEY,
            email      TEXT NOT NULL,
            kind       TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );
        """
    )
    # Migration: add the verification flag to existing user tables.
    try:
        con.execute("ALTER TABLE users ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    if not _DB_PATH:
        raise RuntimeError("auth.init_db() must be called first")
    return sqlite3.connect(_DB_PATH)


def _hash_pw(password: str, salt: bytes) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    return salt.hex() + "$" + dk.hex()


def _verify_pw(password: str, stored: str) -> bool:
    try:
        salt_hex, _ = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(_hash_pw(password, salt), stored)


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def create_user(email: str, password: str) -> tuple[bool, str | None]:
    """Create an account. Returns (ok, error_message)."""
    email = (email or "").strip().lower()
    if not valid_email(email):
        return False, "Please enter a valid email address."
    if len(password or "") < MIN_PASSWORD:
        return False, f"Password must be at least {MIN_PASSWORD} characters."
    con = _conn()
    try:
        if con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return False, "An account with this email already exists."
        salt = secrets.token_bytes(16)
        con.execute(
            "INSERT INTO users(email, pw_hash, created_at) VALUES(?,?,?)",
            (email, _hash_pw(password, salt), int(time.time())),
        )
        con.commit()
        return True, None
    finally:
        con.close()


def set_password(email: str, password: str) -> tuple[bool, str | None]:
    """Replace a user's password (used by the reset flow)."""
    email = (email or "").strip().lower()
    if len(password or "") < MIN_PASSWORD:
        return False, f"Password must be at least {MIN_PASSWORD} characters."
    con = _conn()
    try:
        if not con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return False, "Account not found."
        salt = secrets.token_bytes(16)
        con.execute("UPDATE users SET pw_hash=? WHERE email=?",
                    (_hash_pw(password, salt), email))
        con.commit()
        return True, None
    finally:
        con.close()


def user_exists(email: str) -> bool:
    email = (email or "").strip().lower()
    con = _conn()
    try:
        return bool(con.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone())
    finally:
        con.close()


def verify_user(email: str, password: str) -> bool:
    email = (email or "").strip().lower()
    con = _conn()
    try:
        row = con.execute("SELECT pw_hash FROM users WHERE email=?", (email,)).fetchone()
    finally:
        con.close()
    return bool(row) and _verify_pw(password, row[0])


def create_session(email: str) -> str:
    email = (email or "").strip().lower()
    token = secrets.token_urlsafe(32)
    con = _conn()
    con.execute(
        "INSERT INTO sessions(token, email, expires_at) VALUES(?,?,?)",
        (token, email, int(time.time()) + _SESSION_TTL),
    )
    con.commit()
    con.close()
    return token


def session_email(token: str | None) -> str | None:
    """Return the email for a valid (unexpired) session token, else None."""
    if not token:
        return None
    con = _conn()
    try:
        row = con.execute(
            "SELECT email, expires_at FROM sessions WHERE token=?", (token,)
        ).fetchone()
    finally:
        con.close()
    if not row:
        return None
    email, expires_at = row
    if expires_at < time.time():
        delete_session(token)
        return None
    return email


def delete_session(token: str | None) -> None:
    if not token:
        return
    con = _conn()
    con.execute("DELETE FROM sessions WHERE token=?", (token,))
    con.commit()
    con.close()


# --- email verification (and other one-time tokens) --------------------------

VERIFY_TTL = 60 * 60 * 24  # 24 hours
RESET_TTL = 60 * 60        # 1 hour


def create_token(email: str, kind: str, ttl: int = VERIFY_TTL) -> str:
    """Create a one-time token (e.g. kind='verify') tied to an email."""
    email = (email or "").strip().lower()
    token = secrets.token_urlsafe(32)
    con = _conn()
    con.execute(
        "INSERT INTO tokens(token, email, kind, expires_at) VALUES(?,?,?,?)",
        (token, email, kind, int(time.time()) + ttl),
    )
    con.commit()
    con.close()
    return token


def consume_token(token: str | None, kind: str) -> str | None:
    """Validate + delete a one-time token. Returns its email, or None."""
    if not token:
        return None
    con = _conn()
    try:
        row = con.execute(
            "SELECT email, expires_at FROM tokens WHERE token=? AND kind=?",
            (token, kind),
        ).fetchone()
        if row:
            con.execute("DELETE FROM tokens WHERE token=?", (token,))
            con.commit()
    finally:
        con.close()
    if not row:
        return None
    email, expires_at = row
    return email if expires_at >= time.time() else None


def mark_verified(email: str) -> None:
    email = (email or "").strip().lower()
    con = _conn()
    con.execute("UPDATE users SET verified=1 WHERE email=?", (email,))
    con.commit()
    con.close()


def is_verified(email: str) -> bool:
    email = (email or "").strip().lower()
    con = _conn()
    try:
        row = con.execute("SELECT verified FROM users WHERE email=?", (email,)).fetchone()
    finally:
        con.close()
    return bool(row and row[0])
