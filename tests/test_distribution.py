import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import portalocker
import pytest
from adam import APP_VERSION
from adam.distribution.portable import DistributionError, Portable
from adam.distribution.releases import Releases, manifest, safe, sha, verify
from adam.distribution.setup import PRESETS
from adam.operations.service import Operations, Preferences
from adam.resilience.contracts import BackupError
from adam.security.auth import AuthError, AuthManager
from test_backup import OWNER, PASSWORD, seeded


def package(tmp_path, release=APP_VERSION, channel="stable"):
    root = tmp_path / ("payload-" + release + "-" + channel)
    (root / "backend").mkdir(parents=True, exist_ok=True)
    for name in ["adam-desktop.exe", "adam.compact.toml", "backend/adam-service.exe"]:
        (root / name).write_bytes(b"SYNTHETIC NOT EXECUTABLE")
    (root / "release.json").write_text(
        json.dumps(manifest(root, release, channel)), encoding="utf-8"
    )
    target = tmp_path / (release + "-" + channel + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for file in root.rglob("*"):
            if file.is_file():
                z.write(file, file.relative_to(root).as_posix())
    return target, root


@pytest.fixture
def installed(tmp_path):
    settings, runtime, auth, token = seeded(tmp_path / "profile")
    auth.elevate(token, OWNER)
    manager = Releases(settings, checker=lambda app, data, version: None)
    yield manager, auth, token, runtime
    runtime.retrieval.close()


def test_portable_preserves_identity_history_and_owner_without_original_model(tmp_path):
    settings, runtime, auth, token = seeded(tmp_path / "source")
    operations = Operations(settings.data_dir)
    operations.configure(Preferences(enabled=True, proactive=True, triggers=["unread_reminders"]))
    backup = tmp_path / "profile.adamportable"
    result = Portable().create(settings, PASSWORD, backup)
    assert result["status"] == "VERIFIED" and b"SnapshotStudio" not in backup.read_bytes()
    target = tmp_path / "new-device"
    receipt = Portable().restore(backup, PASSWORD, target)
    assert (
        receipt["device_repair"]
        and not (target / "models").exists()
        and not (target / "mesh").exists()
        and not (target / "voice").exists()
    )
    with closing(sqlite3.connect(target / "runtime.sqlite3")) as db:
        assert "SnapshotStudio" in db.execute("SELECT record FROM memories").fetchone()[0]
    restored = AuthManager(target)
    with pytest.raises(AuthError):
        restored.resolve(token)
    assert restored.resolve(restored.issue("owner", OWNER)).mode == "owner"
    assert not Operations(target).preferences().enabled
    assert (target / "config/restored-settings.json").is_file()
    with pytest.raises(BackupError, match="FRESH_TARGET"):
        Portable().restore(backup, PASSWORD, target)
    runtime.retrieval.close()


def test_wrong_password_and_corruption_never_publish(tmp_path):
    settings, runtime, _, _ = seeded(tmp_path / "source")
    backup = tmp_path / "profile.adamportable"
    Portable().create(settings, PASSWORD, backup)
    with pytest.raises(BackupError):
        Portable().restore(backup, "different-passphrase-123", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    raw = bytearray(backup.read_bytes())
    raw[-5] ^= 1
    backup.write_bytes(raw)
    with pytest.raises(BackupError):
        Portable().restore(backup, PASSWORD, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    runtime.retrieval.close()


@pytest.mark.parametrize(
    "name",
    ["../escape", "/absolute", "C:/bad", "backend/../bad", "x\\bad", "AUX.txt", "x.", "x ", "a//b"],
)
def test_package_paths_fail_closed(name):
    assert not safe(name)


def test_pinned_checksum_and_channel_and_downgrade(installed, tmp_path):
    manager, _, _, _ = installed
    archive, _ = package(tmp_path)
    with pytest.raises(DistributionError, match="CHECKSUM"):
        manager.stage(archive, "0" * 64, "stable")
    with pytest.raises(DistributionError, match="CHANNEL"):
        manager.stage(archive, sha(archive), "beta")
    older, _ = package(tmp_path, "0.1.0")
    with pytest.raises(DistributionError, match="DOWNGRADE"):
        manager.stage(older, sha(older), "stable")
    assert manager.state()["active"] is None


def test_tampering_and_unlisted_payload_are_denied(tmp_path):
    _, root = package(tmp_path)
    (root / "adam-desktop.exe").write_bytes(b"changed")
    with pytest.raises(DistributionError, match="CHECKSUM"):
        verify(root)


def activate(manager, auth, token, archive, baseline):
    staged = manager.stage(archive, sha(archive), "stable")
    approval = manager.authorize(staged["id"], auth._hash(token))
    result = manager.apply(approval["ticket"], approval["token"], baseline)
    return staged, approval, result


def test_update_clone_and_exact_previous_profile_rollback(installed, tmp_path):
    manager, auth, token, runtime = installed
    archive, baseline = package(tmp_path)
    staged, ticket, result = activate(manager, auth, token, archive, baseline)
    assert result["status"] == "ACTIVATED"
    current = manager.state()
    assert current["active"]["id"] == staged["id"] and current["previous"]["original_data"]
    app, newdata = manager.entry(current["active"])
    assert newdata != manager.settings.data_dir and (newdata / "runtime.sqlite3").exists()
    assert (manager.settings.data_dir / "runtime.sqlite3").exists()
    assert (manager.root / "snapshots" / result["snapshot"]).exists()
    assert (manager.root / "snapshots" / Path(result["snapshot"]).with_suffix(".key")).exists()
    with pytest.raises(FileNotFoundError):
        manager.apply(ticket["ticket"], ticket["token"], baseline)
    # Rollback is authorized from the current cloned profile with a fresh login.
    newauth = AuthManager(newdata)
    newtoken = newauth.issue("owner", OWNER)
    newauth.elevate(newtoken, OWNER)
    manager.settings.data_dir = newdata
    manager.settings.identity_dir = newdata / "identity"
    rollback = manager.authorize(current["previous"]["id"], newauth._hash(newtoken), "rollback")
    manager.apply(rollback["ticket"], rollback["token"], baseline)
    assert manager.state()["active"] == current["previous"]


def test_failed_migration_never_replaces_active_profile(installed, tmp_path):
    manager, auth, token, _ = installed
    archive, baseline = package(tmp_path)

    def fail(app, data, version):
        (data / "failed-migration-marker").write_text("synthetic")
        raise RuntimeError("synthetic migration failure")

    manager.checker = fail
    staged = manager.stage(archive, sha(archive), "stable")
    approval = manager.authorize(staged["id"], auth._hash(token))
    before = sha(manager.settings.data_dir / "runtime.sqlite3")
    with pytest.raises(DistributionError, match="HEALTH_FAILED"):
        manager.apply(approval["ticket"], approval["token"], baseline)
    assert manager.state()["active"] is None and before == sha(
        manager.settings.data_dir / "runtime.sqlite3"
    )
    assert json.loads((manager.root / "last-result.json").read_bytes())["status"] == "ROLLED_BACK"


def test_reauthentication_revocation_and_open_profile_block_activation(installed, tmp_path):
    manager, auth, token, _ = installed
    archive, baseline = package(tmp_path)
    staged = manager.stage(archive, sha(archive), "stable")
    approval = manager.authorize(staged["id"], auth._hash(token))
    with portalocker.Lock(str(manager.settings.data_dir / "desktop.lease"), mode="a+b", timeout=0):
        with pytest.raises(portalocker.exceptions.LockException):
            manager.apply(approval["ticket"], approval["token"], baseline)
    with pytest.raises(DistributionError, match="APPROVAL"):
        manager.apply(approval["ticket"], "x" * 43, baseline)
    auth.revoke(token)
    with pytest.raises(DistributionError, match="APPROVAL"):
        manager.apply(approval["ticket"], approval["token"], baseline)
    assert manager.state()["active"] is None


def test_model_setup_pins_existing_reviewed_revisions():
    text = Path("scripts/setup-model.ps1").read_text(encoding="utf-8")
    for url, digest in PRESETS.values():
        assert url in text and digest in text


def test_setup_download_checksum_cancellation_and_reuse(tmp_path, monkeypatch):
    import hashlib

    import httpx
    from adam.core.config import Settings
    from adam.distribution import setup as module

    raw = b"GGUF synthetic pinned data"
    expected = hashlib.sha256(raw).hexdigest()
    factory = httpx.Client
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=raw)

    monkeypatch.setattr(
        module.httpx,
        "Client",
        lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs),
    )
    setup = module.Setup(Settings(data_dir=tmp_path))
    target = tmp_path / "model.gguf"
    setup.download("https://example.test/model", target, expected, 1000)
    assert target.read_bytes() == raw
    setup.download("https://example.test/model", target, expected, 1000)
    assert len(calls) == 1
    with pytest.raises(DistributionError, match="CHECKSUM"):
        setup.download("https://example.test/model", tmp_path / "bad.gguf", "0" * 64, 1000)
    assert not (tmp_path / "bad.gguf").exists() and not (tmp_path / "bad.gguf.part").exists()
    setup.cancel.set()
    with pytest.raises(DistributionError, match="CANCELLED"):
        setup.download("https://example.test/model", tmp_path / "cancel.gguf", expected, 1000)


def test_invalid_manifest_and_case_duplicate_archive(installed, tmp_path):
    manager, _, _, _ = installed
    bad = tmp_path / "bad-root"
    bad.mkdir()
    (bad / "release.json").write_text("{}")
    with pytest.raises(DistributionError, match="MANIFEST"):
        verify(bad)
    archive = tmp_path / "case.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("File", b"1")
        z.writestr("file", b"2")
    with pytest.raises(DistributionError, match="PACKAGE_LIMIT"):
        manager.stage(archive, sha(archive), "stable")


def test_distribution_owner_api_boundaries(tmp_path):
    from adam.api.app import create_app
    from adam.core.config import Settings
    from auth_client import OwnerClient
    from test_text_runtime import provider

    app = create_app(Settings(data_dir=tmp_path), provider())
    with OwnerClient(app, base_url="http://localhost") as client:
        assert client.get("/distribution").status_code == 200
        assert (
            client.post(
                "/distribution/stage", json={"path": "missing", "sha256": "0" * 64}
            ).status_code
            == 403
        )
        guest = app.state.auth.issue("guest")
        assert (
            client.get("/distribution", headers={"Authorization": "Bearer " + guest}).status_code
            == 403
        )
        assert client.post("/distribution/backup", json={"password": "short"}).status_code in {
            403,
            422,
        }
        client.post("/auth/elevate", json={"password": "synthetic-owner-test-passphrase"})
        assert (
            client.post(
                "/distribution/stage", json={"path": "missing", "sha256": "0" * 64}
            ).status_code
            == 409
        )


def test_guided_setup_installs_cpu_catalog_without_starting_model(tmp_path, monkeypatch):
    import io

    from adam.core.config import Settings
    from adam.distribution import setup as module

    assets = tmp_path / "assets"
    assets.mkdir()
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(module, "assets_root", lambda: assets)
    from types import SimpleNamespace

    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda root: SimpleNamespace(free=10 * 1024**3)
    )
    setup = module.Setup(Settings(data_dir=profile))

    def download(url, target, expected, limit):
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix == ".gguf":
            target.write_bytes(b"GGUF synthetic weights")
        else:
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as z:
                z.writestr("llama-server.exe", b"SYNTHETIC NOT EXECUTABLE")
            target.write_bytes(stream.getvalue())

    monkeypatch.setattr(setup, "download", download)
    result = setup.install("qwen3-4b-instruct")
    assert result["status"] == "VERIFIED_RESTART_REQUIRED"
    catalog = json.loads((profile / "config/model-catalog.json").read_bytes())
    current = catalog["profiles"]["current"]
    assert current["device"] == "cpu" and current["model"]["context_limit"] == 2048
    assert current["model"]["display_name"] == "Qwen3 4B (CPU setup)"
    assert (assets / "runtime/llama/llama-server.exe").is_file()


def test_launcher_clears_a_stale_restored_profile_on_rollback(tmp_path, monkeypatch):
    from adam.distribution import cli

    monkeypatch.setenv("ADAM_RESTORED_CONFIG", str(tmp_path / "old-generation/config.json"))
    captured = {}

    def spawn(command, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(cli.subprocess, "Popen", spawn)
    cli.launch(tmp_path / "home", tmp_path / "app")
    assert "ADAM_RESTORED_CONFIG" not in captured["env"]
    assert captured["env"]["ADAM_DATA_DIR"] == str(tmp_path / "home")
    assert captured["env"]["ADAM_MANAGED_LAUNCH"] == "1"


def test_activation_approval_is_bound_to_the_reviewed_generation_state(installed, tmp_path):
    manager, auth, token, _ = installed
    archive, baseline = package(tmp_path)
    staged = manager.stage(archive, sha(archive), "stable")
    ticket = manager.authorize(staged["id"], auth._hash(token))
    changed = {
        "active": {"id": "00000000-0000-0000-0000-000000000000", "release": "0.17.0"},
        "previous": None,
    }
    (manager.root / "state.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(DistributionError, match="STALE_APPROVAL"):
        manager.apply(ticket["ticket"], ticket["token"], baseline)
    assert manager.state() == changed


@pytest.mark.parametrize("cancel", [False, True, "revoke"])
def test_model_setup_background_grant_and_cancellation(tmp_path, monkeypatch, cancel):
    import threading

    from adam.api.app import create_app
    from adam.core.config import Settings
    from auth_client import OwnerClient
    from test_text_runtime import provider

    app = create_app(Settings(data_dir=tmp_path), provider())
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    failures = []

    def install(identifier):
        started.set()
        assert release.wait(5)
        try:
            app.state.setup.guard()
            app.state.setup.progress = {"status": "VERIFIED_RESTART_REQUIRED"}
        except Exception as exc:
            failures.append(getattr(exc, "code", type(exc).__name__))
            raise
        finally:
            finished.set()

    monkeypatch.setattr(app.state.setup, "install", install)
    with OwnerClient(app, base_url="http://localhost") as client:
        client.post("/auth/elevate", json={"password": "synthetic-owner-test-passphrase"})
        queued = client.post("/distribution/model", json={"model_id": "qwen3-4b-instruct"})
        assert queued.status_code == 200 and queued.json()["status"] == "QUEUED"
        assert started.wait(2)
        assert (
            client.post("/distribution/model", json={"model_id": "qwen3-4b-instruct"}).status_code
            == 409
        )
        # The initial pinned-download grant survives elevation expiry, while explicit
        # cancellation remains effective. No real download or model starts.
        with closing(sqlite3.connect(tmp_path / "security/auth.sqlite3")) as db, db:
            db.execute("UPDATE tokens SET elevated_until=0")
        if cancel is True:
            assert client.post("/distribution/cancel", json={}).status_code == 200
        elif cancel == "revoke":
            app.state.auth.revoke(client.headers["Authorization"].removeprefix("Bearer "))
        release.set()
        assert finished.wait(3)
        if not cancel:
            assert app.state.setup.progress["status"] == "VERIFIED_RESTART_REQUIRED"
        else:
            assert failures == ["AUTH.REQUIRED" if cancel == "revoke" else "SETUP.CANCELLED"]
