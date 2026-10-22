"""Real frozen generation validation, failed migration and rollback in synthetic profiles."""

import argparse
import asyncio
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from adam import APP_VERSION
from adam.core.config import Settings
from adam.core.runtime import ChatRequest, Runtime
from adam.distribution.portable import DistributionError, Portable
from adam.distribution.releases import Releases, probe, sha
from adam.evals.suite import ProbeProvider
from adam.security.auth import AuthManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = []

    def check(name, value):
        assert value, name
        checks.append(name)
        print("QA passed:", name, flush=True)

    with tempfile.TemporaryDirectory(prefix="adam-distribution-qa-") as temporary:
        home = Path(temporary) / "profile"
        settings = Settings(data_dir=home)
        runtime = Runtime(settings, ProbeProvider())
        asyncio.run(
            runtime.chat(ChatRequest(text="/remember preference editor = PortableSyntheticEditor"))
        )
        runtime.retrieval.close()
        password = "synthetic-distribution-owner-892734"
        auth = AuthManager(home)
        auth.initialize(password)
        token = auth.issue("owner", password)
        auth.elevate(token, password)
        manager = Releases(settings)
        initial = sha(home / "runtime.sqlite3")
        stage = manager.stage(args.package, sha(args.package), "stable")
        check(
            "package staged without activation",
            manager.state()["active"] is None and stage["status"] == "STAGED_UNEXECUTED",
        )
        approval = manager.authorize(stage["id"], auth._hash(token))
        result = manager.apply(approval["ticket"], approval["token"], args.baseline)
        check("real candidate smoke and migration pass", result["status"] == "ACTIVATED")
        active = manager.state()["active"]
        app, data = manager.entry(active)
        check(
            "profile cloned rather than overwritten",
            data != home and sha(home / "runtime.sqlite3") == initial,
        )
        with closing(sqlite3.connect(data / "runtime.sqlite3")) as db:
            check(
                "owner memory survived update",
                "PortableSyntheticEditor"
                in db.execute("SELECT record FROM memories").fetchone()[0],
            )
        snapshot = manager.root / "snapshots" / result["snapshot"]
        check(
            "encrypted pre-update snapshot",
            snapshot.is_file() and b"PortableSyntheticEditor" not in snapshot.read_bytes(),
        )
        check("local snapshot key sealed", snapshot.with_suffix(".key").is_file())
        newer = AuthManager(data)
        newtoken = newer.issue("owner", password)
        newer.elevate(newtoken, password)
        manager.settings = Settings.model_validate_json(
            (data / "config/restored-settings.json").read_bytes()
        )
        again = manager.stage(args.package, sha(args.package), "stable")
        bad = manager.authorize(again["id"], newer._hash(newtoken))
        before = json.dumps(manager.state(), sort_keys=True)

        def corrupt_clone(app, clone, release):
            with closing(sqlite3.connect(clone / "runtime.sqlite3")) as db, db:
                db.execute("UPDATE schema_migrations SET checksum='synthetic-failed-migration'")
            probe(app, clone, release)

        manager.checker = corrupt_clone
        try:
            manager.apply(bad["ticket"], bad["token"], args.baseline)
            raise AssertionError("failed migration was accepted")
        except DistributionError as exc:
            check("real failed migration rejected", exc.code == "UPDATE.HEALTH_FAILED")
        check(
            "failed update retains exact active pointer",
            before == json.dumps(manager.state(), sort_keys=True),
        )
        check(
            "failed update leaves current memory intact", sha(home / "runtime.sqlite3") == initial
        )
        check(
            "automatic rollback receipt",
            json.loads((manager.root / "last-result.json").read_bytes())["status"] == "ROLLED_BACK",
        )
        manager.checker = probe
        previous = manager.state()["previous"]
        rollback = manager.authorize(previous["id"], newer._hash(newtoken), "rollback")
        manager.apply(rollback["ticket"], rollback["token"], args.baseline)
        check("explicit rollback candidate smoke passes", manager.state()["active"] == previous)
        check("rollback restores original data folder", manager.entry(previous)[1] == home)
        portable = Path(temporary) / "export.adamportable"
        Portable().create(Settings(data_dir=home), password, portable)
        fresh = Path(temporary) / "fresh-device"
        restored = Portable().restore(portable, password, fresh)
        check(
            "portable fresh restore without models",
            restored["status"] == "VERIFIED" and not (fresh / "models").exists(),
        )
        check("device re-pair and model selection declared", len(restored["device_repair"]) >= 4)
        probe(args.baseline, fresh, APP_VERSION)
        check("restored frozen service boots without original model", True)
        with closing(sqlite3.connect(fresh / "runtime.sqlite3")) as db:
            check(
                "portable owner history preserved",
                "PortableSyntheticEditor"
                in db.execute("SELECT record FROM memories").fetchone()[0],
            )
        restored_auth = AuthManager(fresh)
        check(
            "portable owner can log in",
            restored_auth.resolve(restored_auth.issue("owner", password)).mode == "owner",
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "passed": True,
                "checks": checks,
                "limits": (
                    "Disposable local profiles; no clean VM, different physical hardware, "
                    "real model quality or human acceptance."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
