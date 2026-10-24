import io
import os
import re
import secrets
import sqlite3
import stat
import zipfile
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from pydantic import ValidationError

from adam import APP_VERSION
from adam.core.config import Settings
from adam.core.contracts import Contract, new_id, utc_now
from adam.core.migrations import MIGRATIONS
from adam.core.privacy import register_secret
from adam.identity.service import IdentityPack, IdentityService
from adam.resilience.contracts import BackupError, Entry, Generation, Manifest, Receipt
from adam.security.request import check_authority

MAGIC = b"ADAMBK01"
MAX_BYTES = 256 * 1024 * 1024
DB_PATHS = ["runtime.sqlite3", "actions.sqlite3", "tasks.sqlite3", "security/auth.sqlite3"]
IDENTITY_FILES = ["identity", "personality", "communication", "epistemics"]
NAME = re.compile(r"^(daily|weekly|monthly|milestone)-(\d{8}T\d{12}Z)-([a-f0-9-]{36})\.adambak$")


def digest(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)


def check_schema(
    db: sqlite3.Connection,
    migrations: tuple[tuple[int, tuple[str, ...]], ...],
    applied: dict[int, str],
) -> None:
    """Compare with the recorded prefix, without migrating the original database."""
    with closing(sqlite3.connect(":memory:")) as expected:
        for version, statements in migrations:
            if version not in applied:
                break
            for statement in statements:
                expected.execute(statement)
        tables = expected.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        for (table,) in tables:
            # Names come exclusively from the application's static migration SQL.
            quoted = '"' + table.replace('"', '""') + '"'
            if (
                db.execute(f"PRAGMA table_info({quoted})").fetchall()
                != expected.execute(f"PRAGMA table_info({quoted})").fetchall()
            ):
                raise BackupError("STORAGE.SCHEMA_MISMATCH")


def check_db(db: sqlite3.Connection, name: str) -> int:
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise BackupError("STORAGE.INTEGRITY_FAILED")
    if db.execute("PRAGMA foreign_key_check").fetchone():
        raise BackupError("STORAGE.FOREIGN_KEY_FAILED")
    if name == "runtime.sqlite3":
        from adam.core.migrations import MIGRATIONS as migrations
    elif name == "security/auth.sqlite3":
        from adam.security.auth import AUTH_MIGRATIONS as migrations
    elif name == "security/vault.sqlite3":
        from adam.security.vault import VAULT_MIGRATIONS as migrations
    else:
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise BackupError("STORAGE.UNSUPPORTED_SCHEMA")
        table = "actions" if name == "actions.sqlite3" else "tasks"
        from adam.tasks.service import Task
        from adam.tools.service import Action

        contract: type[Contract] = Action if table == "actions" else Task
        try:
            for (raw,) in db.execute(f"SELECT record FROM {table}"):
                contract.model_validate_json(raw)
        except ValueError:
            raise BackupError("STORAGE.RECORD_INVALID") from None
        return 1
    applied = dict(db.execute("SELECT version, checksum FROM schema_migrations"))
    expected = {version: digest("\n".join(sql).encode()) for version, sql in migrations}
    # Known complete prefixes remain readable so startup/restore can migrate older profiles.
    versions = [version for version, _ in migrations]
    if not applied or applied != {v: expected[v] for v in versions[: len(applied)]}:
        raise BackupError("STORAGE.UNSUPPORTED_SCHEMA")
    check_schema(db, migrations, applied)
    if name == "runtime.sqlite3":
        from adam.core.working import WorkingState
        from adam.knowledge.contracts import SourceRecord
        from adam.memory.consolidation import Candidate
        from adam.memory.service import MemoryRecord

        try:
            contracts: list[tuple[int, str, type[Contract]]] = [
                (4, "memories", MemoryRecord),
                (6, "knowledge_sources", SourceRecord),
                (5, "memory_candidates", Candidate),
            ]
            for introduced, table, contract in contracts:
                if introduced not in applied:
                    continue
                for (raw,) in db.execute(f"SELECT record FROM {table}"):
                    contract.model_validate_json(raw)
            if 7 in applied:
                from adam.intelligence.service import Goal, Link
                from adam.training.service import Example

                personal_contracts: list[tuple[str, type[Link] | type[Goal]]] = [
                    ("personal_links", Link),
                    ("personal_goals", Goal),
                ]
                for table, personal_contract in personal_contracts:
                    for identifier, memory_id, raw in db.execute(
                        f"SELECT id,memory_id,record FROM {table}"
                    ):
                        record = personal_contract.model_validate_json(raw)
                        if record.id != identifier or (
                            isinstance(record, Link) and record.memory_id != memory_id
                        ):
                            raise ValueError("Mismatched personal record")
                for identifier, raw in db.execute("SELECT id,record FROM training_examples"):
                    if Example.model_validate_json(raw).id != identifier:
                        raise ValueError("Mismatched training record")
            if 3 in applied:
                for (raw,) in db.execute("SELECT working_state FROM sessions"):
                    WorkingState.model_validate_json(raw)
        except ValueError:
            raise BackupError("STORAGE.RECORD_INVALID") from None
    return int(max(applied))


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    if not name or len(name) > 500 or path.is_absolute() or "\\" in name:
        return False
    if str(path) != name or any(part in {".", ".."} for part in path.parts):
        return False
    for part in path.parts:
        if (
            re.search(r'[\x00-\x1f<>:"|?*]', part)
            or part.endswith((" ", "."))
            or part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *[f"COM{i}" for i in range(1, 10)],
                *[f"LPT{i}" for i in range(1, 10)],
            }
        ):
            return False
    return (
        name in [*DB_PATHS, "security/vault.sqlite3", "config/settings.json"]
        or name in [f"identity/{item}.yaml" for item in IDENTITY_FILES]
        or bool(re.fullmatch(r"knowledge/blobs/[a-f0-9]{64}\.bin", name))
        or name.startswith("tool-sandbox/")
    )


def no_link(path: Path) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise BackupError("BACKUP.LINK_DENIED")


def safe_directory(name: str) -> bool:
    return name == "tool-sandbox" or (safe_name(name) and name.startswith("tool-sandbox/"))


def scoped(root: Path, relative: str) -> Path:
    current = root
    no_link(current)
    for part in PurePosixPath(relative).parts:
        current = current / part
        no_link(current)
    if not current.resolve().is_relative_to(root.resolve()):
        raise BackupError("BACKUP.PATH_DENIED")
    return current


def encode(manifest: Manifest, files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", manifest.model_dump_json())
        for name, data in files.items():
            if not safe_name(name):
                raise BackupError("BACKUP.PATH_DENIED")
            archive.writestr(name, data)
    return stream.getvalue()


def decode(data: bytes) -> tuple[Manifest, dict[str, bytes]]:
    try:
        if len(data) > MAX_BYTES:
            raise BackupError("BACKUP.SIZE_LIMIT")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [item.filename for item in entries]
            if len(names) > 10000 or len(set(names)) != len(names) or "manifest.json" not in names:
                raise BackupError("BACKUP.MANIFEST_INVALID")
            if (
                any(
                    item.compress_type != zipfile.ZIP_STORED
                    or item.is_dir()
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or item.file_size > MAX_BYTES
                    for item in entries
                )
                or sum(item.file_size for item in entries) > MAX_BYTES
            ):
                raise BackupError("BACKUP.SIZE_LIMIT")
            if archive.getinfo("manifest.json").file_size > 2 * 1024 * 1024:
                raise BackupError("BACKUP.MANIFEST_INVALID")
            manifest = Manifest.model_validate_json(archive.read("manifest.json"))
            if any(not safe_directory(name) for name in manifest.directories):
                raise BackupError("BACKUP.PATH_DENIED")
            if set(names) != {"manifest.json", *manifest.files} or any(
                not safe_name(name) for name in manifest.files
            ):
                raise BackupError("BACKUP.PATH_DENIED")
            required = {
                "runtime.sqlite3",
                "config/settings.json",
                *[f"identity/{name}.yaml" for name in IDENTITY_FILES],
            }
            if not required <= manifest.files.keys() or manifest.vault_included != (
                "security/vault.sqlite3" in names
            ):
                raise BackupError("BACKUP.MANIFEST_INVALID")
            files = {name: archive.read(name) for name in manifest.files}
        if any(
            len(files[name]) != entry.size or digest(files[name]) != entry.sha256
            for name, entry in manifest.files.items()
        ):
            raise BackupError("BACKUP.CHECKSUM_FAILED")
        pack = IdentityPack.model_validate(
            {
                name: yaml.safe_load(files[f"identity/{name}.yaml"].decode("utf-8"))
                for name in IDENTITY_FILES
            }
        )
        if digest(pack.model_dump_json().encode()) != manifest.identity_digest:
            raise BackupError("BACKUP.IDENTITY_MISMATCH")
        Settings.model_validate_json(files["config/settings.json"])
        for name in [key for key in files if key in [*DB_PATHS, "security/vault.sqlite3"]]:
            with closing(sqlite3.connect(":memory:")) as db:
                db.deserialize(files[name])
                if check_db(db, name) != manifest.schemas.get(name):
                    raise BackupError("BACKUP.SCHEMA_MISMATCH")
        if manifest.schemas.get("runtime.sqlite3") not in {version for version, _ in MIGRATIONS}:
            raise BackupError("BACKUP.SCHEMA_MISMATCH")
        return manifest, files
    except (
        zipfile.BadZipFile,
        KeyError,
        ValidationError,
        sqlite3.Error,
        ValueError,
        yaml.YAMLError,
    ) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("BACKUP.MANIFEST_INVALID") from None


def key(password: str, salt: bytes) -> bytes:
    if not 12 <= len(password) <= 1024:
        raise BackupError("BACKUP.PASSPHRASE_LENGTH")
    register_secret(password)
    return Argon2id(salt=salt, length=32, iterations=3, lanes=4, memory_cost=65536).derive(
        password.encode()
    )


def encrypt(data: bytes, password: str) -> bytes:
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = MAGIC + salt + nonce
    return header + AESGCM(key(password, salt)).encrypt(nonce, data, header)


def decrypt(data: bytes, password: str) -> bytes:
    if len(data) < 52 or len(data) > MAX_BYTES + 52 or data[:8] != MAGIC:
        raise BackupError("BACKUP.FORMAT_INVALID")
    try:
        return AESGCM(key(password, data[8:24])).decrypt(data[24:36], data[36:], data[:36])
    except InvalidTag:
        raise BackupError("BACKUP.AUTHENTICATION_FAILED") from None


class BackupService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.directory = self.root / "backups"

    def snapshot(
        self, include_vault: bool, generation: Generation
    ) -> tuple[Manifest, dict[str, bytes]]:
        if generation not in {"daily", "weekly", "monthly", "milestone"}:
            raise BackupError("BACKUP.GENERATION_INVALID")
        no_link(self.root)
        if not (self.root / "runtime.sqlite3").is_file():
            raise BackupError("BACKUP.NO_STORE")
        files: dict[str, bytes] = {}
        schemas: dict[str, int] = {}
        directories: list[str] = []
        total = 0

        def add(name: str, data: bytes) -> None:
            nonlocal total
            total += len(data)
            if total > self.settings.backup.max_bytes:
                raise BackupError("BACKUP.SIZE_LIMIT")
            files[name] = data

        try:
            # Match existing executor lock order. Busy task/action work is refused;
            # committed SQLite states are frozen together while the snapshot is copied.
            with ExitStack() as stack:
                for name in ["tasks-lock.sqlite3", "actions-lock.sqlite3"]:
                    path = scoped(self.root, name)
                    if path.exists():
                        no_link(path)
                        lock = stack.enter_context(closing(sqlite3.connect(path, timeout=0.1)))
                        stack.callback(lock.rollback)
                        lock.execute("BEGIN IMMEDIATE")
                db_names = [name for name in DB_PATHS if (self.root / name).exists()]
                if include_vault:
                    if not (self.root / "security/vault.sqlite3").exists():
                        raise BackupError("BACKUP.VAULT_MISSING")
                    db_names.append("security/vault.sqlite3")
                for name in db_names:
                    path = scoped(self.root, name)
                    no_link(path)
                    if path.stat().st_size > self.settings.backup.max_bytes:
                        raise BackupError("BACKUP.SIZE_LIMIT")
                    # mode=rw forbids silently creating a missing critical database.
                    lock = stack.enter_context(
                        closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0.1))
                    )
                    stack.callback(lock.rollback)
                    lock.execute("BEGIN IMMEDIATE")
                for name in db_names:
                    with (
                        closing(readonly(self.root / name)) as source,
                        closing(sqlite3.connect(":memory:")) as copy,
                    ):
                        source.backup(copy)
                        schemas[name] = check_db(copy, name)
                        if name == "security/auth.sqlite3":
                            copy.execute("DELETE FROM tokens")
                            copy.execute(
                                "UPDATE throttle SET failures=0,blocked_until=0,"
                                "window_start=0,anonymous_count=0"
                            )
                            copy.commit()
                        serialized = copy.serialize()
                        # SQLite documents these two header bytes for deserialization
                        # of a complete WAL backup as a portable rollback-mode image.
                        serialized = serialized[:18] + b"\x01\x01" + serialized[20:]
                        add(name, serialized)
                for relative in ["tool-sandbox", "knowledge/blobs"]:
                    folder = scoped(self.root, relative)
                    if not folder.exists():
                        continue
                    for path in sorted(folder.rglob("*")):
                        no_link(path)
                        if path.is_dir() and relative == "tool-sandbox":
                            name = path.relative_to(self.root).as_posix()
                            if not safe_directory(name) or len(directories) >= 10000:
                                raise BackupError("BACKUP.PATH_DENIED")
                            directories.append(name)
                        if not path.is_file():
                            continue
                        name = path.relative_to(self.root).as_posix()
                        if relative == "knowledge/blobs" and not re.fullmatch(
                            r"knowledge/blobs/[a-f0-9]{64}\.bin", name
                        ):
                            continue
                        if not safe_name(name):
                            raise BackupError("BACKUP.PATH_DENIED")
                        before = path.stat()
                        if before.st_size + total > self.settings.backup.max_bytes:
                            raise BackupError("BACKUP.SIZE_LIMIT")
                        data = path.read_bytes()
                        after = path.stat()
                        if (before.st_size, before.st_mtime_ns) != (
                            after.st_size,
                            after.st_mtime_ns,
                        ):
                            raise BackupError("BACKUP.SOURCE_CHANGED")
                        if relative == "knowledge/blobs" and digest(data) != path.stem:
                            raise BackupError("BACKUP.CHECKSUM_FAILED")
                        add(name, data)
                identity = IdentityService(self.settings.identity_dir)
                for name in IDENTITY_FILES:
                    # Serialize the validated active identity, independent of provider/assets.
                    add(
                        f"identity/{name}.yaml",
                        yaml.safe_dump(
                            identity.pack.model_dump()[name], allow_unicode=True
                        ).encode(),
                    )
                add("config/settings.json", self.settings.model_dump_json().encode())
            manifest = Manifest(
                release=APP_VERSION,
                created_at=utc_now().isoformat(),
                generation=generation,
                identity_digest=identity.digest,
                vault_included=include_vault,
                schemas=schemas,
                directories=directories,
                files={
                    name: Entry(sha256=digest(data), size=len(data)) for name, data in files.items()
                },
            )
            return manifest, files
        except sqlite3.OperationalError:
            raise BackupError("BACKUP.STORE_BUSY") from None
        except sqlite3.Error:
            raise BackupError("STORAGE.INTEGRITY_FAILED") from None
        except OSError:
            raise BackupError("BACKUP.IO_FAILED") from None

    def create(
        self, password: str, *, include_vault: bool = False, generation: Generation = "daily"
    ) -> Receipt:
        # Validate the passphrase before touching any destination or taking locks.
        if not 12 <= len(password) <= 1024:
            raise BackupError("BACKUP.PASSPHRASE_LENGTH")
        manifest, files = self.snapshot(include_vault, generation)
        plain = encode(manifest, files)
        if len(plain) > self.settings.backup.max_bytes:
            raise BackupError("BACKUP.SIZE_LIMIT")
        sealed = encrypt(plain, password)
        check_authority()
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        identifier = f"{generation}-{stamp}-{new_id()}.adambak"
        no_link(self.directory)
        temporary = self.directory / (identifier + ".part")
        destination = self.directory / identifier
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with temporary.open("xb") as stream:
                stream.write(sealed)
                stream.flush()
                os.fsync(stream.fileno())
            verified, _ = self.read(temporary, password)
            if verified != manifest:
                raise BackupError("BACKUP.VERIFY_FAILED")
            check_authority()
            os.replace(temporary, destination)
            # Only managed files of this generation are eligible, after verification.
            keep = getattr(self.settings.backup, generation)
            candidates = sorted(
                [
                    path
                    for path in self.directory.iterdir()
                    if NAME.fullmatch(path.name) and path.name.startswith(generation + "-")
                ],
                key=lambda path: path.name,
                reverse=True,
            )
            for old in candidates[keep:]:
                no_link(old)
                old.unlink()
            return Receipt(
                backup_id=identifier,
                generation=generation,
                created_at=manifest.created_at,
                size_bytes=len(sealed),
                vault_included=include_vault,
            )
        except OSError:
            raise BackupError("BACKUP.IO_FAILED") from None
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def read(path: Path, password: str) -> tuple[Manifest, dict[str, bytes]]:
        try:
            no_link(path)
            if not path.is_file() or path.stat().st_size > MAX_BYTES + 52:
                raise BackupError("BACKUP.SIZE_LIMIT")
            return decode(decrypt(path.read_bytes(), password))
        except OSError:
            raise BackupError("BACKUP.IO_FAILED") from None

    def path(self, identifier: str) -> Path:
        if not NAME.fullmatch(identifier):
            raise BackupError("BACKUP.ID_INVALID")
        no_link(self.directory)
        result = self.directory / identifier
        no_link(result)
        return result

    def list(self) -> list[dict[str, object]]:
        no_link(self.directory)
        if not self.directory.exists():
            return []
        return [
            {
                "backup_id": path.name,
                "size_bytes": path.stat().st_size,
                "status": "UNVERIFIED_UNTIL_UNLOCKED",
            }
            for path in sorted(self.directory.iterdir(), reverse=True)
            if NAME.fullmatch(path.name) and not path.is_symlink()
        ]
