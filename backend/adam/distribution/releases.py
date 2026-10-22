"""Offline managed generations. Publication changes one atomic pointer, never live stores."""

import hashlib
import json
import os
import queue
import re
import secrets
import shutil
import stat
import subprocess
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any

import httpx
import portalocker

from adam import APP_VERSION
from adam.core.config import Settings
from adam.core.contracts import new_id
from adam.distribution.portable import DistributionError, Portable, publish
from adam.resilience.archive import no_link, scoped
from adam.security.request import check_authority
from adam.security.vault import DPAPI

MAX_PACKAGE = 1024**3
REQUIRED = {"adam-desktop.exe", "adam.compact.toml", "backend/adam-service.exe"}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and len(name) <= 240
        and str(path) == name
        and not path.is_absolute()
        and all(
            p not in {".", ".."}
            and not p.endswith((" ", "."))
            and not re.search(r'[\x00-\x1f<>:"|?*\\]', p)
            and p.split(".")[0].upper()
            not in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *[f"COM{i}" for i in range(1, 10)],
                *[f"LPT{i}" for i in range(1, 10)],
            }
            for p in path.parts
        )
    )


def manifest(root: Path, release: str, channel: str = "stable") -> dict[str, Any]:
    files = {}
    for file in sorted(root.rglob("*")):
        no_link(file)
        if file.is_file() and file.name != "release.json":
            name = file.relative_to(root).as_posix()
            if not safe(name) or file.suffix in {".gguf", ".sqlite3"}:
                raise DistributionError("UPDATE.PATH_DENIED")
            files[name] = {"sha256": sha(file), "bytes": file.stat().st_size}
    return {
        "format": "adam.release.v1",
        "release": release,
        "channel": channel,
        "platform": "windows-x64",
        "files": files,
    }


def _verify(root: Path) -> dict[str, Any]:
    path = scoped(root, "release.json")
    if path.stat().st_size > 2 * 1024**2:
        raise DistributionError("UPDATE.MANIFEST_INVALID")
    data = json.loads(path.read_bytes())
    if (
        data["format"] != "adam.release.v1"
        or data["platform"] != "windows-x64"
        or data["channel"] not in {"stable", "beta", "dev"}
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?", data["release"])
    ):
        raise DistributionError("UPDATE.MANIFEST_INVALID")
    files = data["files"]
    if (
        not REQUIRED <= files.keys()
        or len(files) > 10000
        or len({n.casefold() for n in files}) != len(files)
    ):
        raise DistributionError("UPDATE.MANIFEST_INVALID")
    total = 0
    for name, item in files.items():
        if not safe(name):
            raise DistributionError("UPDATE.PATH_DENIED")
        target = scoped(root, name)
        total += target.stat().st_size
        if (
            total > MAX_PACKAGE
            or target.stat().st_size != item["bytes"]
            or sha(target) != item["sha256"]
        ):
            raise DistributionError("UPDATE.CHECKSUM_FAILED")
    actual = {f.relative_to(root).as_posix() for f in root.rglob("*") if f.is_file()}
    if actual != {*files, "release.json"}:
        raise DistributionError("UPDATE.MANIFEST_INVALID")
    result: dict[str, Any] = data
    return result


def verify(root: Path) -> dict[str, Any]:
    try:
        return _verify(root)
    except DistributionError:
        raise
    except (ValueError, KeyError, TypeError, OSError):
        raise DistributionError("UPDATE.MANIFEST_INVALID") from None


def probe(app: Path, data: Path, release: str) -> None:
    env = dict(os.environ, ADAM_DATA_DIR=str(data))
    env.pop("ADAM_CONFIG", None)
    env.pop("ADAM_RESTORED_CONFIG", None)
    if (data / "config/restored-settings.json").is_file():
        env["ADAM_RESTORED_CONFIG"] = str(data / "config/restored-settings.json")
    child = subprocess.Popen(
        [str(app / "backend/adam-service.exe"), "--probe", "--data-dir", str(data)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    job = None
    try:
        if os.name == "nt":
            import win32job  # type: ignore[import-untyped]

            job = win32job.CreateJobObject(None, "")
            limits = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, limits
            )
            win32job.AssignProcessToJobObject(job, int(child._handle))  # type: ignore[attr-defined]
        lines: queue.Queue[str] = queue.Queue()
        assert child.stdout and child.stdin
        output = child.stdout
        threading.Thread(target=lambda: lines.put(output.readline(16384)), daemon=True).start()
        ready = json.loads(lines.get(timeout=150))
        with httpx.Client(
            base_url=f"http://127.0.0.1:{ready['port']}",
            headers={"x-adam-desktop": ready["nonce"]},
            timeout=10,
            trust_env=False,
        ) as client:
            status = client.get("/desktop/status").json()
            health = client.get("/health")
            if status["recovery"] or status["release"] != release or health.status_code != 200:
                raise DistributionError("UPDATE.HEALTH_FAILED")
        child.stdin.write("stop\n")
        child.stdin.flush()
        child.wait(timeout=30)
        if child.returncode:
            raise DistributionError("UPDATE.HEALTH_FAILED")
    except (ValueError, KeyError, queue.Empty, httpx.HTTPError, subprocess.SubprocessError):
        raise DistributionError("UPDATE.HEALTH_FAILED") from None
    finally:
        if job is not None:
            import win32api  # type: ignore[import-untyped]

            win32api.CloseHandle(job)
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        if child.stdout:
            child.stdout.close()
        if child.stdin:
            child.stdin.close()


class Releases:
    def __init__(
        self,
        settings: Settings,
        home: Path | None = None,
        checker: Callable[[Path, Path, str], None] = probe,
    ) -> None:
        self.settings = settings
        self.home = (home or Path(os.environ.get("ADAM_HOME", str(settings.data_dir)))).resolve()
        self.root = scoped(self.home, "distribution")
        self.root.mkdir(parents=True, exist_ok=True)
        self.checker = checker

    def path(self, identifier: str) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{36}", identifier):
            raise DistributionError("UPDATE.ID_INVALID")
        return scoped(self.root, "generations/" + identifier)

    def state(self) -> dict[str, Any]:
        path = scoped(self.root, "state.json")
        return (
            json.loads(path.read_bytes()) if path.exists() else {"active": None, "previous": None}
        )

    def status(self) -> dict[str, Any]:
        state = self.state()
        return {
            "active": state["active"],
            "previous": state["previous"],
            "channels": ["stable", "beta", "dev"],
            "feed": "OWNER_PINNED_LOCAL_PACKAGE",
            "data_dir": str(self.settings.data_dir),
            "home": str(self.home),
        }

    def stage(self, archive: Path, expected: str, channel: str) -> dict[str, Any]:
        try:
            return self._stage(archive, expected, channel)
        except DistributionError:
            raise
        except (zipfile.BadZipFile, OSError, ValueError, KeyError, TypeError):
            raise DistributionError("UPDATE.PACKAGE_INVALID") from None

    def _stage(self, archive: Path, expected: str, channel: str) -> dict[str, Any]:
        check_authority()
        no_link(archive)
        if (
            channel not in {"stable", "beta", "dev"}
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
            or not archive.is_file()
            or archive.stat().st_size > MAX_PACKAGE
            or sha(archive) != expected
        ):
            raise DistributionError("UPDATE.CHECKSUM_FAILED")
        with portalocker.Lock(str(self.root / "manager.lock"), mode="a+b", timeout=0):
            identifier = new_id()
            destination = self.path(identifier)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=".release-", dir=destination.parent) as temporary:
                stage = Path(temporary)
                app = stage / "app"
                app.mkdir()
                with zipfile.ZipFile(archive) as source:
                    infos = source.infolist()
                    names = [i.filename for i in infos]
                    if (
                        len(names) > 10001
                        or len(set(n.casefold() for n in names)) != len(names)
                        or sum(i.file_size for i in infos) > MAX_PACKAGE
                    ):
                        raise DistributionError("UPDATE.PACKAGE_LIMIT")
                    for info in infos:
                        if (
                            not safe(info.filename)
                            or info.is_dir()
                            or stat.S_ISLNK(info.external_attr >> 16)
                        ):
                            raise DistributionError("UPDATE.PATH_DENIED")
                        target = scoped(app, info.filename)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with source.open(info) as src, target.open("xb") as dst:
                            shutil.copyfileobj(src, dst, 1024**2)
                metadata = verify(app)
                if metadata["channel"] != channel:
                    raise DistributionError("UPDATE.CHANNEL_MISMATCH")
                current = self.state()["active"]
                version = tuple(map(int, metadata["release"].split("-")[0].split(".")))
                baseline = tuple(
                    map(
                        int,
                        (current["release"] if current else APP_VERSION).split("-")[0].split("."),
                    )
                )
                if version < baseline:
                    raise DistributionError("UPDATE.DOWNGRADE_DENIED")
                publish(
                    stage / "receipt.json",
                    json.dumps(
                        {
                            "id": identifier,
                            "release": metadata["release"],
                            "channel": channel,
                            "archive_sha256": expected,
                        }
                    ).encode(),
                )
                check_authority()
                stage.rename(destination)
            return {
                "id": identifier,
                "release": metadata["release"],
                "channel": channel,
                "status": "STAGED_UNEXECUTED",
                "sha256": expected,
            }

    def authorize(self, identifier: str, owner_hash: str, mode: str = "update") -> dict[str, Any]:
        if mode not in {"update", "rollback", "restore"}:
            raise DistributionError("UPDATE.MODE_INVALID")
        if mode == "update":
            verify(self.path(identifier) / "app")
        elif mode == "rollback" and not self.state()["previous"]:
            raise DistributionError("UPDATE.NO_PREVIOUS")
        current_state = self.state()
        if mode == "rollback" and current_state["previous"]["id"] != identifier:
            raise DistributionError("UPDATE.STALE_APPROVAL")
        token = secrets.token_urlsafe(32)
        ticket = new_id()
        record = {
            "mode": mode,
            "expected_state": current_state,
            "id": identifier,
            "owner": owner_hash,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires": time.time() + 60,
            "data": str(self.settings.data_dir),
            "settings": self.settings.model_dump(mode="json"),
        }
        publish(scoped(self.root, "tickets/" + ticket + ".json"), json.dumps(record).encode())
        return {
            "ticket": ticket,
            "token": token,
            "expires_in": 60,
            "warning": (
                "ADAM closes. Activation uses a cloned profile; "
                "rollback returns to the pre-update profile. Current state is retained."
            ),
        }

    def entry(self, record: dict[str, Any]) -> tuple[Path, Path]:
        generation = self.path(record["id"])
        app = generation / "app"
        meta = verify(app)
        if meta["release"] != record["release"]:
            raise DistributionError("UPDATE.MANIFEST_INVALID")
        data = self.home if record.get("original_data") else scoped(generation, "data")
        return app, data

    def bootstrap(self, app: Path) -> dict[str, Any]:
        identifier = new_id()
        generation = self.path(identifier)
        target = generation / "app"
        target.mkdir(parents=True)
        for name in ["adam-desktop.exe", "adam.compact.toml"]:
            shutil.copy2(app / name, target / name)
        shutil.copytree(app / "backend", target / "backend")
        publish(target / "release.json", json.dumps(manifest(target, APP_VERSION)).encode())
        verify(target)
        return {"id": identifier, "release": APP_VERSION, "original_data": True}

    def apply(self, ticket: str, token: str, baseline_app: Path) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9-]{36}", ticket):
            raise DistributionError("UPDATE.ID_INVALID")
        path = scoped(self.root, "tickets/" + ticket + ".json")
        record = json.loads(path.read_bytes())
        import hmac

        if record["expires"] < time.time() or not hmac.compare_digest(
            record["token_hash"], hashlib.sha256(token.encode()).hexdigest()
        ):
            raise DistributionError("UPDATE.APPROVAL_REQUIRED")
        import sqlite3
        from contextlib import closing

        data = Path(record["data"]).resolve()
        if data != self.settings.data_dir.resolve():
            raise DistributionError("UPDATE.PROFILE_CHANGED")
        with closing(
            sqlite3.connect((data / "security/auth.sqlite3").as_uri() + "?mode=ro", uri=True)
        ) as db:
            authority = db.execute(
                "SELECT mode, expires, elevated_until FROM tokens WHERE digest=?",
                (record["owner"],),
            ).fetchone()
            if not authority or authority[0] != "owner" or min(authority[1:]) < time.time():
                raise DistributionError("UPDATE.APPROVAL_REQUIRED")
        with (
            portalocker.Lock(str(self.root / "manager.lock"), mode="a+b", timeout=0),
            portalocker.Lock(str(data / "desktop.lease"), mode="a+b", timeout=0),
        ):
            path.unlink()  # Every activation ticket is consumed before snapshot or migration.
            state = self.state()
            if record["expected_state"] != state:
                raise DistributionError("UPDATE.STALE_APPROVAL")
            previous = state["active"] or self.bootstrap(baseline_app)
            key = secrets.token_urlsafe(32)
            snapshot = self.root / "snapshots" / (new_id() + ".adamportable")
            Portable().create(self.settings, key, snapshot, local=True)
            publish(snapshot.with_suffix(".key"), DPAPI().seal(key.encode()))
            if record["mode"] == "rollback":
                selected = state["previous"]
                app, selected_data = self.entry(selected)
            elif record["mode"] == "restore":
                selected = {"id": record["id"], "release": APP_VERSION}
                generation = self.path(record["id"])
                app, selected_data = self.entry(previous)[0], generation / "data"
                # A staged portable restore contains data only; use the current known-good app.
                shutil.copytree(app, generation / "app")
                app = generation / "app"
            else:
                selected = {
                    "id": record["id"],
                    "release": json.loads((self.path(record["id"]) / "receipt.json").read_bytes())[
                        "release"
                    ],
                }
                app, selected_data = (
                    self.path(record["id"]) / "app",
                    self.path(record["id"]) / "data",
                )
                verify(app)
                Portable().restore(snapshot, key, selected_data)
            try:
                self.checker(app, selected_data, selected["release"])
                new_state = {"active": selected, "previous": previous, "snapshot": snapshot.name}
                publish(self.root / "state.json", json.dumps(new_state).encode())
                outcome = {
                    "status": "ACTIVATED",
                    "release": selected["release"],
                    "snapshot": snapshot.name,
                }
            except Exception:
                outcome = {
                    "status": "ROLLED_BACK",
                    "error": "UPDATE.HEALTH_FAILED",
                    "snapshot": snapshot.name,
                }
                publish(self.root / "last-result.json", json.dumps(outcome).encode())
                raise DistributionError("UPDATE.HEALTH_FAILED") from None
            publish(self.root / "last-result.json", json.dumps(outcome).encode())
            return outcome
