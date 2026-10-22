"""Encrypted portable data, independent of installed models and vector indexes."""

import io
import json
import os
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from adam.core.config import Settings
from adam.resilience.archive import (
    MAX_BYTES,
    BackupService,
    decrypt,
    digest,
    encode,
    encrypt,
    no_link,
    scoped,
)
from adam.resilience.contracts import BackupError
from adam.resilience.restore import RestoreService
from adam.security.request import check_authority


class DistributionError(BackupError):
    pass


LOCAL_FILES = {
    "config/model-catalog.json",
    "mesh/network.json",
    "mesh/tls/ca.crt",
    "mesh/tls/cert.pem",
    "mesh/tls/key.pem",
    "mesh/tls/password.dpapi",
}
EXTRAS = {"operations/jobs.sqlite3", "voice/speakers.sqlite3", "mesh/registry.sqlite3"}


def publish(path: Path, data: bytes) -> None:
    no_link(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    no_link(temporary)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        check_authority()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Portable:
    def create(
        self, settings: Settings, password: str, target: Path, local: bool = False
    ) -> dict[str, Any]:
        if not 12 <= len(password) <= 1024:
            raise DistributionError("BACKUP.PASSPHRASE_LENGTH")
        vault = local and (settings.data_dir / "security/vault.sqlite3").is_file()
        manifest, files = BackupService(settings).snapshot(vault, "milestone")
        entries = {"core.adambak": encrypt(encode(manifest, files), password)}
        for name in sorted(EXTRAS if local else {"operations/jobs.sqlite3"}):
            source = scoped(settings.data_dir, name)
            if not source.is_file():
                continue
            with (
                closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db,
                closing(sqlite3.connect(":memory:")) as copy,
            ):
                db.backup(copy)
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DistributionError("STORAGE.INTEGRITY_FAILED")
                raw = copy.serialize()
                entries[name] = raw[:18] + b"\x01\x01" + raw[20:]
        if local:
            for name in LOCAL_FILES:
                source = scoped(settings.data_dir, name)
                if source.is_file():
                    if source.stat().st_size > 2 * 1024**2:
                        raise DistributionError("BACKUP.SIZE_LIMIT")
                    entries[name] = source.read_bytes()
        if sum(map(len, entries.values())) > MAX_BYTES:
            raise DistributionError("BACKUP.SIZE_LIMIT")
        metadata = {
            "format": 1,
            "local": local,
            "files": {k: digest(v) for k, v in entries.items()},
            "device_repair": []
            if local
            else [
                "re-pair phones",
                "re-enroll speakers",
                "re-enter vault secrets",
                "choose model",
                "rebuild indexes",
            ],
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", json.dumps(metadata))
            for name, raw in entries.items():
                archive.writestr(name, raw)
        if len(output.getvalue()) > MAX_BYTES:
            raise DistributionError("BACKUP.SIZE_LIMIT")
        publish(target, encrypt(output.getvalue(), password))
        self.read(target, password)
        return {
            "status": "VERIFIED",
            "file": target.name,
            "sha256": digest(target.read_bytes()),
            "device_repair": metadata["device_repair"],
        }

    @staticmethod
    def read(path: Path, password: str) -> tuple[dict[str, Any], dict[str, bytes]]:
        no_link(path)
        if not path.is_file() or path.stat().st_size > MAX_BYTES + 100:
            raise DistributionError("BACKUP.SIZE_LIMIT")
        try:
            raw = decrypt(path.read_bytes(), password)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                names = [i.filename for i in infos]
                if (
                    len(names) != len(set(names))
                    or not set(names) <= {"manifest.json", "core.adambak", *EXTRAS, *LOCAL_FILES}
                    or sum(i.file_size for i in infos) > MAX_BYTES
                    or any(i.compress_type != zipfile.ZIP_STORED for i in infos)
                ):
                    raise DistributionError("BACKUP.MANIFEST_INVALID")
                meta = json.loads(archive.read("manifest.json"))
                if (
                    meta["format"] != 1
                    or set(names) != {"manifest.json", *meta["files"]}
                    or "core.adambak" not in names
                ):
                    raise DistributionError("BACKUP.MANIFEST_INVALID")
                files = {n: archive.read(n) for n in meta["files"]}
                if any(digest(v) != meta["files"][k] for k, v in files.items()):
                    raise DistributionError("BACKUP.CHECKSUM_FAILED")
                return meta, files
        except (ValueError, KeyError, TypeError, zipfile.BadZipFile, OSError):
            raise DistributionError("BACKUP.MANIFEST_INVALID") from None

    def restore(self, archive: Path, password: str, target: Path) -> dict[str, Any]:
        meta, files = self.read(archive, password)
        no_link(target)
        if target.exists():
            raise DistributionError("RESTORE.FRESH_TARGET_REQUIRED")
        target.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".adam-portable-", dir=target.parent) as temporary:
            root = Path(temporary)
            core = root / "core.adambak"
            core.write_bytes(files["core.adambak"])
            stage = root / "profile"
            RestoreService().restore(
                core,
                password,
                stage,
                restore_vault=meta["local"]
                and "security/vault.sqlite3" in BackupService.read(core, password)[1],
            )
            for name, raw in files.items():
                if name == "core.adambak":
                    continue
                if name not in EXTRAS | LOCAL_FILES or (
                    not meta["local"] and name != "operations/jobs.sqlite3"
                ):
                    raise DistributionError("BACKUP.PATH_DENIED")
                if name in EXTRAS:
                    with closing(sqlite3.connect(":memory:")) as db:
                        db.deserialize(raw)
                        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise DistributionError("STORAGE.INTEGRITY_FAILED")
                path = scoped(stage, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            # RestoreService staged its paths; rebind once more to the final publication path.
            RestoreService.rebind_sources(stage, target.resolve())
            config_path = stage / "config/restored-settings.json"
            config = Settings.model_validate_json(config_path.read_bytes())
            config.data_dir, config.identity_dir = target.resolve(), target.resolve() / "identity"
            config.knowledge.allowed_roots = [target.resolve() / "knowledge/restored-sources"]
            config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
            if not meta["local"]:
                operations = stage / "operations/jobs.sqlite3"
                if operations.exists():
                    from adam.operations.service import Preferences

                    with closing(sqlite3.connect(operations)) as db, db:
                        prefs = Preferences.model_validate_json(
                            db.execute("SELECT value FROM settings").fetchone()[0]
                        )
                        prefs.enabled, prefs.proactive = False, False
                        db.execute(
                            "UPDATE settings SET value=? WHERE id=1", (prefs.model_dump_json(),)
                        )
                config.features.voice = False
                config.features.speaker_id = False
                config.features.mobile_mesh = False
                config_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
                (stage / "config/device-repair.json").write_text(
                    json.dumps(meta["device_repair"]), encoding="utf-8"
                )
            check_authority()
            stage.rename(target)
        return {
            "status": "VERIFIED",
            "target": str(target),
            "device_repair": meta["device_repair"],
            "model_required": True,
            "indexes": "REBUILD_REQUIRED",
        }
