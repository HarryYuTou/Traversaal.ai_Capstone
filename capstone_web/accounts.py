"""Local accounts and login sessions in one SQLite file; standard library only."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
from uuid import uuid4

from .jobs import RequestError, now

USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
SESSION_DAYS = 14
# OWASP's current minimum for PBKDF2-HMAC-SHA256; tests pass a smaller value for speed.
ITERATIONS = 600_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


def hash_password(password, iterations=ITERATIONS, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hash_password(password, int(iterations), bytes.fromhex(salt))
    except ValueError:
        return False
    return hmac.compare_digest(actual.split("$")[3], expected)


def token_hash(token):
    # Only a hash is stored, so a copied database file cannot be used to sign in.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_credentials(body):
    if not isinstance(body, dict) or body.keys() != {"username", "password"}:
        raise RequestError("Send a JSON object with username and password.")
    username, password = body["username"], body["password"]
    if not isinstance(username, str) or not USERNAME.fullmatch(username.strip()):
        raise RequestError("Username must be 3–32 letters, numbers, dots, dashes or underscores.")
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise RequestError("Password must contain 8–128 characters.")
    return username.strip(), password


class AccountStore:
    def __init__(self, path, iterations=ITERATIONS):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.iterations = iterations
        # Comparing against this hash for unknown usernames keeps login timing uniform.
        self.dummy_hash = hash_password(secrets.token_hex(16), iterations)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self):
        # A connection per call keeps the threaded HTTP server free of shared SQLite state.
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return closing(connection)

    @staticmethod
    def _public(row):
        return {"id": row["id"], "username": row["username"], "createdAt": row["created_at"]}

    def register(self, username, password):
        user = {"id": uuid4().hex, "username": username,
                "password_hash": hash_password(password, self.iterations), "created_at": now()}
        try:
            with self._connect() as connection, connection:
                connection.execute("INSERT INTO users VALUES (:id, :username, :password_hash, :created_at)", user)
        except sqlite3.IntegrityError:
            raise RequestError("That username is already taken.", "username_taken", 409) from None
        return self._public(user)

    def authenticate(self, username, password):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            verify_password(password, self.dummy_hash)
            return None
        return self._public(row) if verify_password(password, row["password_hash"]) else None

    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        created = datetime.now(timezone.utc)
        with self._connect() as connection, connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (created.isoformat(),))
            connection.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)",
                               (token_hash(token), user_id, created.isoformat(),
                                (created + timedelta(days=SESSION_DAYS)).isoformat()))
        return token

    def session_user(self, token):
        if not token:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.token_hash = ? AND sessions.expires_at > ?", (token_hash(token), now())).fetchone()
        return self._public(row) if row is not None else None

    def end_session(self, token):
        if token:
            with self._connect() as connection, connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
