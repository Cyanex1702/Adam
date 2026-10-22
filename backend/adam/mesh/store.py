import hashlib
import json
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from adam.core.migrations import migrate
from adam.mesh.contracts import Claim, MeshError
from adam.mesh.crypto import export, fingerprint, verify
from adam.resilience.archive import scoped
from adam.security.request import check_authority
from adam.security.vault import DPAPI, Sealer

MIGRATIONS = (
    (
        1,
        (
            "CREATE TABLE metadata(key TEXT PRIMARY KEY,value BLOB NOT NULL)",
            "CREATE TABLE tickets(digest TEXT PRIMARY KEY,expires REAL NOT NULL)",
            "CREATE TABLE devices(id TEXT PRIMARY KEY,label TEXT NOT NULL,pub TEXT NOT NULL,"
            "fingerprint TEXT UNIQUE NOT NULL,status TEXT NOT NULL,"
            "search INTEGER NOT NULL DEFAULT 0,voice INTEGER NOT NULL DEFAULT 0,"
            "seen REAL NOT NULL DEFAULT 0)",
            "CREATE TABLE shares(device TEXT NOT NULL,session TEXT NOT NULL,"
            "PRIMARY KEY(device,session))",
            "CREATE TABLE primary_device(session TEXT PRIMARY KEY,device TEXT NOT NULL,"
            "revision INTEGER NOT NULL DEFAULT 1)",
            "CREATE TABLE requests(device TEXT NOT NULL,id TEXT NOT NULL,digest TEXT NOT NULL,"
            "status TEXT NOT NULL,response TEXT,PRIMARY KEY(device,id))",
        ),
    ),
)


class MeshStore:
    def __init__(self, root: Path, sealer: Sealer | None = None) -> None:
        self.path = scoped(root, "mesh/registry.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migrate(self.path, MIGRATIONS)
        sealer = sealer or DPAPI()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM metadata WHERE key='private_key'").fetchone()
            if row is None:
                key = ec.generate_private_key(ec.SECP256R1())
                raw = key.private_bytes(
                    serialization.Encoding.DER,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                db.execute("INSERT INTO metadata VALUES('private_key',?)", (sealer.seal(raw),))
                db.execute("INSERT INTO metadata VALUES('node_id',?)", (str(uuid4()),))
            else:
                loaded = serialization.load_der_private_key(sealer.open(row[0]), password=None)
                if not isinstance(loaded, ec.EllipticCurvePrivateKey) or not isinstance(
                    loaded.curve, ec.SECP256R1
                ):
                    raise MeshError("MESH.IDENTITY_UNAVAILABLE")
                key = loaded
            self.node_id = str(
                db.execute("SELECT value FROM metadata WHERE key='node_id'").fetchone()[0]
            )
        self.key, self.public_key = key, export(key)

    def device(self, identifier: str, *, pending: bool = False) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM devices WHERE id=?", (identifier,)).fetchone()
        if not row or row["status"] not in ({"APPROVED", "PENDING"} if pending else {"APPROVED"}):
            raise MeshError("MESH.DEVICE_DENIED")
        return dict(row)

    def devices(self) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,label,fingerprint,status,search,voice,seen "
                    "FROM devices ORDER BY rowid"
                )
            ]

    def ticket(self) -> str:
        check_authority()
        code = secrets.token_hex(12)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM tickets")
            db.execute(
                "INSERT INTO tickets VALUES(?,?)",
                (hashlib.sha256(code.encode()).hexdigest(), time.time() + 300),
            )
            check_authority()
        return code

    def claim(self, body: Claim) -> dict[str, str]:
        signed = f"1\n{body.code}\n{body.label}\n{body.public_key}".encode()
        verify(body.public_key, signed, body.signature)
        digest = hashlib.sha256(body.code.encode()).hexdigest()
        identifier = str(uuid4())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            ticket = db.execute("SELECT expires FROM tickets WHERE digest=?", (digest,)).fetchone()
            if not ticket or ticket[0] < time.time():
                raise MeshError("MESH.PAIR_CODE_INVALID")
            if (
                db.execute("SELECT count(*) FROM devices WHERE status!='REVOKED'").fetchone()[0]
                >= 16
            ):
                raise MeshError("MESH.DEVICE_LIMIT")
            # Intentional re-pair requires revoking the old identity and a new key.
            if db.execute(
                "SELECT 1 FROM devices WHERE fingerprint=?", (fingerprint(body.public_key),)
            ).fetchone():
                raise MeshError("MESH.KEY_ALREADY_REGISTERED")
            db.execute("DELETE FROM tickets WHERE digest=?", (digest,))
            db.execute(
                "INSERT INTO devices(id,label,pub,fingerprint,status) VALUES(?,?,?,?,'PENDING')",
                (identifier, body.label, body.public_key, fingerprint(body.public_key)),
            )
        return {
            "device_id": identifier,
            "node_id": self.node_id,
            "public_key": self.public_key,
            "status": "PENDING",
        }

    def approve(self, identifier: str, search: bool, voice: bool) -> None:
        check_authority()
        self.device(identifier, pending=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            changed = db.execute(
                "UPDATE devices SET status='APPROVED',search=?,voice=? "
                "WHERE id=? AND status='PENDING'",
                (search, voice, identifier),
            )
            if changed.rowcount != 1:
                raise MeshError("MESH.DEVICE_DENIED")
            check_authority()

    def revoke(self, identifier: str) -> None:
        check_authority()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE devices SET status='REVOKED' WHERE id=?", (identifier,))
            db.execute("DELETE FROM shares WHERE device=?", (identifier,))
            db.execute(
                "UPDATE primary_device SET device='desktop',revision=revision+1 WHERE device=?",
                (identifier,),
            )
            db.execute("DELETE FROM requests WHERE device=?", (identifier,))
            check_authority()

    def share(self, device: str, session: str) -> None:
        self.device(device)
        check_authority()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM devices WHERE id=? AND status='APPROVED'", (device,)
            ).fetchone():
                raise MeshError("MESH.DEVICE_DENIED")
            db.execute("INSERT OR IGNORE INTO shares VALUES(?,?)", (device, session))
            check_authority()

    def sessions(self, device: str) -> list[str]:
        self.device(device)
        with closing(sqlite3.connect(self.path)) as db:
            return [
                r[0]
                for r in db.execute(
                    "SELECT session FROM shares WHERE device=? LIMIT 100", (device,)
                )
            ]

    def allowed_session(self, device: str, session: str) -> None:
        if session not in self.sessions(device):
            raise MeshError("MESH.SESSION_NOT_SHARED")

    def primary(self, session: str) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT device,revision FROM primary_device WHERE session=?", (session,)
            ).fetchone()
        return {"primary": row[0] if row else "desktop", "revision": row[1] if row else 0}

    def handoff(self, session: str, device: str) -> dict[str, Any]:
        check_authority()
        if device != "desktop":
            self.allowed_session(device, session)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO primary_device VALUES(?,?,1) ON CONFLICT(session) "
                "DO UPDATE SET device=excluded.device,revision=revision+1",
                (session, device),
            )
            check_authority()
        return self.primary(session)

    def reserve(self, device: str, identifier: str, digest: str) -> dict[str, Any] | None:
        self.device(device)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT digest,status,response FROM requests WHERE device=? AND id=?",
                (device, identifier),
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise MeshError("MESH.IDEMPOTENCY_CONFLICT")
                if row[1] != "DONE":
                    raise MeshError("MESH.RESULT_UNCERTAIN")
                return json.loads(row[2])  # type: ignore[no-any-return]
            if (
                db.execute("SELECT count(*) FROM requests WHERE device=?", (device,)).fetchone()[0]
                >= 2000
            ):
                raise MeshError("MESH.REQUEST_LIMIT")
            db.execute(
                "INSERT INTO requests VALUES(?,?,?,'RUNNING',NULL)", (device, identifier, digest)
            )
        return None

    def complete(self, device: str, identifier: str, result: dict[str, Any]) -> None:
        self.device(device)
        check_authority()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "UPDATE requests SET status='DONE',response=? WHERE device=? AND id=?",
                (json.dumps(result), device, identifier),
            )
            db.execute("UPDATE devices SET seen=? WHERE id=?", (time.time(), device))
            check_authority()
