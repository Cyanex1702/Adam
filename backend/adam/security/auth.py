import hashlib
import hmac
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from adam.core.migrations import migrate
from adam.core.privacy import register_secret
from adam.security.policy import Mode, Principal

AUTH_MIGRATIONS = (
    (
        1,
        (
            "CREATE TABLE credential (id INTEGER PRIMARY KEY CHECK(id=1), "
            "salt BLOB NOT NULL, digest BLOB NOT NULL)",
            "CREATE TABLE tokens (digest TEXT PRIMARY KEY, mode TEXT NOT NULL, "
            "profile_id TEXT NOT NULL, expires REAL NOT NULL, "
            "elevated_until REAL NOT NULL DEFAULT 0)",
            "CREATE TABLE throttle (id INTEGER PRIMARY KEY CHECK(id=1), "
            "failures INTEGER NOT NULL, blocked_until REAL NOT NULL, "
            "window_start REAL NOT NULL, anonymous_count INTEGER NOT NULL)",
            "INSERT INTO throttle VALUES (1,0,0,0,0)",
        ),
    ),
)


class AuthError(ValueError):
    def __init__(self, code: str = "AUTH.DENIED") -> None:
        self.code = code
        super().__init__(code)


def password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024
    )


class AuthManager:
    """Initialize from the trusted console or private native desktop setup bridge.

    The ordinary HTTP API never exposes credential initialization.
    """

    def __init__(self, root: Path) -> None:
        self.path = root / "security" / "auth.sqlite3"
        migrate(self.path, AUTH_MIGRATIONS)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def configured(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM credential").fetchone() is not None

    def initialize(self, password: str) -> None:
        if not 12 <= len(password) <= 1024:
            raise AuthError("AUTH.PASSPHRASE_LENGTH")
        salt = secrets.token_bytes(32)
        digest = password_digest(password, salt)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM credential").fetchone():
                raise AuthError("AUTH.ALREADY_CONFIGURED")
            db.execute("INSERT INTO credential VALUES (1,?,?)", (salt, digest))
        register_secret(password)

    def verify(self, password: str) -> None:
        if not 1 <= len(password) <= 1024:
            raise AuthError()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = db.execute("SELECT * FROM throttle WHERE id=1").fetchone()
            if state["blocked_until"] > time.time():
                raise AuthError("AUTH.RATE_LIMITED")
            row = db.execute("SELECT * FROM credential WHERE id=1").fetchone()
            if not row:
                raise AuthError("AUTH.NOT_CONFIGURED")
            valid = hmac.compare_digest(row["digest"], password_digest(password, row["salt"]))
            failures = 0 if valid else state["failures"] + 1
            db.execute(
                "UPDATE throttle SET failures=?,blocked_until=? WHERE id=1",
                (failures, time.time() + 60 if failures >= 5 else 0),
            )
        if not valid:
            raise AuthError()
        register_secret(password)

    def issue(self, mode: Mode, password: str | None = None) -> str:
        if mode == "owner":
            self.verify(password or "")
        now = time.time()
        token = "adam_session_" + secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM tokens WHERE expires<?", (now,))
            if mode != "owner":
                row = db.execute("SELECT * FROM throttle WHERE id=1").fetchone()
                count = row["anonymous_count"] if now - row["window_start"] < 60 else 0
                if (
                    count >= 10
                    or db.execute("SELECT COUNT(*) FROM tokens WHERE mode<>'owner'").fetchone()[0]
                    >= 50
                ):
                    raise AuthError("AUTH.RATE_LIMITED")
                db.execute(
                    "UPDATE throttle SET anonymous_count=?,window_start=? WHERE id=1",
                    (count + 1, row["window_start"] if count else now),
                )
            db.execute(
                "INSERT INTO tokens VALUES (?,?,?,?,0)",
                (self._hash(token), mode, secrets.token_hex(16), now + 1800),
            )
        return token

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def resolve(self, token: str) -> Principal:
        if not token.startswith("adam_session_") or len(token) > 128:
            raise AuthError("AUTH.REQUIRED")
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM tokens WHERE digest=? AND expires>?",
                (self._hash(token), time.time()),
            ).fetchone()
        if not row or row["mode"] not in {"owner", "guest", "demo"}:
            raise AuthError("AUTH.REQUIRED")
        mode: Mode = row["mode"]
        return Principal(
            mode,
            mode,
            mode == "owner",
            mode == "owner",
            mode == "owner" and row["elevated_until"] > time.time(),
            row["profile_id"],
        )

    def elevate(self, token: str, password: str) -> None:
        if self.resolve(token).mode != "owner":
            raise AuthError("AUTH.OWNER_REQUIRED")
        self.verify(password)
        with self.connect() as db:
            db.execute(
                "UPDATE tokens SET elevated_until=? WHERE digest=?",
                (time.time() + 300, self._hash(token)),
            )

    def revoke(self, token: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM tokens WHERE digest=?", (self._hash(token),))
