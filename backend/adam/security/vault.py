"""Privileged backend interface. No HTTP/model interface reveals raw values."""

import base64
import json
import os
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal, Protocol

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from adam.core.migrations import migrate
from adam.core.privacy import contains_secret, register_secret
from adam.security.policy import Principal

VAULT_MIGRATIONS = (
    (
        1,
        (
            "CREATE TABLE vault_config (id INTEGER PRIMARY KEY CHECK(id=1), "
            "backend TEXT NOT NULL, salt BLOB NOT NULL, verifier BLOB NOT NULL)",
            "CREATE TABLE secrets (handle TEXT PRIMARY KEY, "
            "purpose TEXT NOT NULL, cipher BLOB NOT NULL)",
        ),
    ),
)
Backend = Literal["auto", "dpapi", "fernet"]


class VaultError(ValueError):
    def __init__(self, code: str = "VAULT.UNAVAILABLE") -> None:
        self.code = code
        super().__init__(code)


class Sealer(Protocol):
    def seal(self, data: bytes) -> bytes: ...
    def open(self, data: bytes) -> bytes: ...


class DPAPI:
    """Current-user scope, never CRYPTPROTECT_LOCAL_MACHINE; disallow Windows UI."""

    def seal(self, data: bytes) -> bytes:
        import win32crypt  # type: ignore[import-untyped]

        return bytes(
            win32crypt.CryptProtectData(data, "ADAM vault", b"adam-vault-v1", None, None, 1)
        )

    def open(self, data: bytes) -> bytes:
        import win32crypt

        return bytes(win32crypt.CryptUnprotectData(data, b"adam-vault-v1", None, None, 1)[1])


class PasswordSealer:
    def __init__(self, password: str, salt: bytes) -> None:
        # RFC 9106 memory-constrained parameters: 64 MiB, three passes, four lanes.
        key = Argon2id(salt=salt, length=32, iterations=3, lanes=4, memory_cost=65536).derive(
            password.encode("utf-8")
        )
        self.fernet = Fernet(base64.urlsafe_b64encode(key))

    def seal(self, data: bytes) -> bytes:
        return self.fernet.encrypt(data)

    def open(self, data: bytes) -> bytes:
        return self.fernet.decrypt(data)


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def __repr__(self) -> str:
        return "SecretValue([REDACTED])"

    def __str__(self) -> str:
        return "[REDACTED]"

    def reveal(self) -> str:
        return self._value

    def clear(self) -> None:
        self._value = ""


class Vault:
    def __init__(self, root: Path, backend: Backend = "auto", enabled: bool = True) -> None:
        self.path = root / "security" / "vault.sqlite3"
        self.backend = ("dpapi" if os.name == "nt" else "fernet") if backend == "auto" else backend
        self.enabled = enabled
        self.sealer: Sealer | None = None
        self.consumers: dict[str, Callable[[SecretValue], None]] = {}
        self.lock = threading.RLock()
        if enabled:
            migrate(self.path, VAULT_MIGRATIONS)
            with self.connect() as db:
                row = db.execute("SELECT * FROM vault_config").fetchone()
            if row:
                self.backend = row["backend"]
                if self.backend == "dpapi":
                    try:
                        sealer = DPAPI()
                        if sealer.open(row["verifier"]) != b"adam-vault-v1":
                            raise VaultError()
                        self.sealer = sealer
                        self._register_values()
                    except Exception:
                        self.sealer = None

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if not self.enabled:
            raise VaultError("VAULT.DISABLED")
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def authorize(principal: Principal) -> None:
        if not (
            principal.mode == "owner"
            and principal.person_id == "owner"
            and principal.authenticated
            and principal.trusted_device
            and principal.elevated
        ):
            raise VaultError("VAULT.ELEVATION_REQUIRED")

    def available(self) -> Sealer:
        if not self.enabled:
            raise VaultError("VAULT.DISABLED")
        if self.sealer is None:
            raise VaultError("VAULT.LOCKED")
        return self.sealer

    def status(self, principal: Principal) -> dict[str, object]:
        self.authorize(principal)
        return {
            "backend": self.backend,
            "enabled": self.enabled,
            "unlocked": self.sealer is not None,
        }

    def unlock(self, principal: Principal, password: str = "") -> None:
        self.authorize(principal)
        with self.lock:
            try:
                with self.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute("SELECT * FROM vault_config").fetchone()
                    backend = row["backend"] if row else self.backend
                    salt = row["salt"] if row else secrets.token_bytes(16)
                    if backend == "fernet" and not 12 <= len(password) <= 1024:
                        raise VaultError("VAULT.PASSPHRASE_LENGTH")
                    sealer: Sealer = (
                        PasswordSealer(password, salt) if backend == "fernet" else DPAPI()
                    )
                    if row:
                        if sealer.open(row["verifier"]) != b"adam-vault-v1":
                            raise VaultError()
                    else:
                        db.execute(
                            "INSERT INTO vault_config VALUES (1,?,?,?)",
                            (backend, salt, sealer.seal(b"adam-vault-v1")),
                        )
                self.sealer = sealer
                self._register_values()
                if backend == "fernet":
                    register_secret(password)
            except VaultError:
                self.sealer = None
                raise
            except Exception:
                self.sealer = None
                raise VaultError() from None

    def lock_vault(self, principal: Principal) -> None:
        self.authorize(principal)
        with self.lock:
            self.sealer = None

    def _decode(self, handle: str, purpose: str, cipher: bytes) -> str:
        payload = json.loads(self.available().open(cipher))
        if payload["handle"] != handle or payload["purpose"] != purpose:
            raise VaultError()
        value = payload["value"]
        if not isinstance(value, str):
            raise VaultError()
        return value

    def _register_values(self) -> None:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM secrets").fetchall()
        for row in rows:
            register_secret(self._decode(row["handle"], row["purpose"], row["cipher"]))

    def put(self, principal: Principal, purpose: str, value: str) -> str:
        self.authorize(principal)
        if (
            not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", purpose)
            or not 8 <= len(value) <= 8192
            or value in purpose
            or contains_secret(purpose)
        ):
            raise VaultError("VAULT.INVALID_INPUT")
        with self.lock:
            try:
                handle = "secret://" + secrets.token_hex(16)
                payload = json.dumps(
                    {"handle": handle, "purpose": purpose, "value": value}
                ).encode()
                cipher = self.available().seal(payload)
                with self.connect() as db:
                    db.execute("INSERT INTO secrets VALUES (?,?,?)", (handle, purpose, cipher))
                register_secret(value)
                return handle
            except VaultError:
                raise
            except Exception:
                raise VaultError() from None

    def list_handles(self, principal: Principal) -> list[dict[str, str]]:
        self.authorize(principal)
        self.available()
        with self.connect() as db:
            return [
                {"handle": row[0], "purpose": row[1], "sensitivity": "NEVER_LOG"}
                for row in db.execute("SELECT handle,purpose FROM secrets")
            ]

    def delete(self, principal: Principal, handle: str) -> bool:
        self.authorize(principal)
        self.available()
        with self.lock, self.connect() as db:
            return db.execute("DELETE FROM secrets WHERE handle=?", (handle,)).rowcount == 1

    def register_consumer(self, purpose: str, consumer: Callable[[SecretValue], None]) -> None:
        """Trusted backend registration only, never a request/model-selected callable."""
        self.consumers[purpose] = consumer

    def consume(self, principal: Principal, handle: str, purpose: str) -> dict[str, object]:
        self.authorize(principal)
        with self.lock:
            value: SecretValue | None = None
            try:
                self.available()
                consumer = self.consumers.get(purpose)
                if consumer is None:
                    raise VaultError("VAULT.CONSUMER_DENIED")
                with self.connect() as db:
                    row = db.execute("SELECT * FROM secrets WHERE handle=?", (handle,)).fetchone()
                if not row or row["purpose"] != purpose:
                    raise VaultError("VAULT.SCOPE_DENIED")
                value = SecretValue(self._decode(handle, purpose, row["cipher"]))
                consumer(value)  # Callback return is deliberately discarded.
                return {"handle": handle, "purpose": purpose, "consumed": True}
            except VaultError:
                raise
            except Exception:
                raise VaultError() from None
            finally:
                if value is not None:
                    value.clear()
