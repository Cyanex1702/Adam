import asyncio
import json
import socket
import ssl
import time
from uuid import uuid4

import httpx
import pytest
from adam.core.config import Settings
from adam.core.contracts import SessionId
from adam.desktop.service import desktop_app
from adam.mesh.contracts import Claim, MeshError
from adam.mesh.crypto import decode, encode, export, fingerprint, packet, verify
from adam.mesh.store import MeshStore
from adam.mesh.tls import prepare
from adam.security.policy import Principal, ResourcePolicy, decide
from adam.security.request import REMOTE_DEVICE
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from fastapi.testclient import TestClient

NONCE = "synthetic-mesh-desktop-capability-827197412"
PASSWORD = "synthetic-mesh-owner-passphrase-82719"


def claim(key, code):
    public = export(key)
    signed = f"1\n{code}\nAndroid phone\n{public}".encode()
    r, s = utils.decode_dss_signature(key.sign(signed, ec.ECDSA(hashes.SHA256())))
    return Claim(
        protocol=1,
        code=code,
        label="Android phone",
        public_key=public,
        signature=encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
    )


@pytest.fixture
def mesh(tmp_path):
    settings = Settings(data_dir=tmp_path, features={"mobile_mesh": True})
    boundary = desktop_app(settings, NONCE, probe=True)
    app = boundary.ready
    with TestClient(
        boundary, base_url="http://localhost", headers={"x-adam-desktop": NONCE}
    ) as desktop:
        desktop.post("/desktop/setup", json={"password": PASSWORD})
        desktop.post("/auth/login", json={"password": PASSWORD})
        desktop.post("/auth/elevate", json={"password": PASSWORD})
        manager = app.state.mesh
        with TestClient(manager.public, base_url=manager.origin) as phone:
            yield manager, desktop, phone


def paired(mesh, search=False, voice=False):
    manager, desktop, phone = mesh
    key = ec.generate_private_key(ec.SECP256R1())
    result = phone.post("/pair", json=claim(key, manager.store.ticket()).model_dump()).json()
    device = result["device_id"]
    response = desktop.post(
        "/developer/mesh/approve", json={"device_id": device, "search": search, "voice": voice}
    )
    assert response.status_code == 200, response.text
    return key, device


def rpc(mesh, key, device, op, payload=None, rid=None, issued=None):
    manager, _, phone = mesh
    body = {
        "protocol": 1,
        "device_id": device,
        "request_id": rid or str(uuid4()),
        "issued_at": issued or int(time.time()),
        "operation": op,
        "payload": payload or {},
    }
    response = phone.post("/rpc", json=packet(key, body))
    if response.status_code != 200:
        return response.status_code, response.json()
    result = response.json()
    verify(manager.store.public_key, decode(result["message"]), result["signature"])
    value = json.loads(decode(result["message"]))
    assert value["request_id"] == body["request_id"] and value["node_id"] == manager.store.node_id
    return 200, value


def test_pairing_needs_owner_approval_and_single_use_code(mesh):
    manager, desktop, phone = mesh
    key = ec.generate_private_key(ec.SECP256R1())
    body = claim(key, manager.store.ticket())
    value = phone.post("/pair", json=body.model_dump()).json()
    assert value["status"] == "PENDING"
    assert rpc(mesh, key, value["device_id"], "status")[1]["status"] == "PENDING"
    assert rpc(mesh, key, value["device_id"], "new_session")[0] == 403
    assert phone.post("/pair", json=body.model_dump()).json()["error"] == "MESH.PAIR_CODE_INVALID"
    assert (
        desktop.post("/developer/mesh/approve", json={"device_id": value["device_id"]}).status_code
        == 200
    )
    assert rpc(mesh, key, value["device_id"], "status")[1]["payload"]["sessions"] == []


def test_owner_controls_fail_without_elevation_or_capability(mesh):
    _, desktop, _ = mesh
    desktop.post("/auth/logout", json={})
    desktop.post("/auth/login", json={"password": PASSWORD})
    assert desktop.get("/developer/mesh").status_code == 403
    assert desktop.post("/developer/mesh/start", json={}).status_code == 403
    assert desktop.get("/developer/mesh", headers={"x-adam-desktop": "wrong"}).status_code == 403


def test_shared_session_handoff_chat_and_idempotency(mesh):
    manager, desktop, _ = mesh
    key, device = paired(mesh)
    _, created = rpc(mesh, key, device, "new_session")
    sid = created["payload"]["session_id"]
    rid = str(uuid4())
    _, result = rpc(mesh, key, device, "chat", {"session_id": sid, "text": "Hi from Android"}, rid)
    assert result["status"] == "VERIFIED", result
    assert result["payload"]["model_answer"] == "UNVERIFIED"
    assert (
        rpc(mesh, key, device, "chat", {"session_id": sid, "text": "Hi from Android"}, rid)[1]
        == result
    )
    assert len(manager.runtime.store.history(SessionId(sid))) == 1
    assert (
        rpc(mesh, key, device, "chat", {"session_id": sid, "text": "Different"}, rid)[1]["error"]
        == "MESH.IDEMPOTENCY_CONFLICT"
    )
    assert (
        desktop.post("/desktop/chat", json={"session_id": sid, "text": "Hi"}).json()["error"]
        == "MESH.NOT_PRIMARY"
    )
    assert (
        rpc(mesh, key, device, "handoff", {"session_id": sid, "primary": "desktop"})[1]["status"]
        == "VERIFIED"
    )
    assert (
        rpc(mesh, key, device, "chat", {"session_id": sid, "text": "Hello"})[1]["error"]
        == "MESH.NOT_PRIMARY"
    )
    assert (
        desktop.post("/desktop/chat", json={"session_id": sid, "text": "Hi PC"}).status_code == 200
    )


def test_unshared_history_denied_and_explicit_sharing_required(mesh):
    manager, desktop, _ = mesh
    key, device = paired(mesh)
    sid = str(manager.runtime.sessions.resolve(None, str(uuid4())).session_id)
    assert (
        rpc(mesh, key, device, "session", {"session_id": sid})[1]["error"]
        == "MESH.SESSION_NOT_SHARED"
    )
    assert (
        desktop.post(
            "/developer/mesh/share", json={"session_id": sid, "device_id": device}
        ).status_code
        == 422
    )
    assert (
        desktop.post(
            "/developer/mesh/share", json={"session_id": sid, "device_id": device, "consent": True}
        ).status_code
        == 200
    )
    assert rpc(mesh, key, device, "session", {"session_id": sid})[1]["status"] == "VERIFIED"
    key2, device2 = paired(mesh)
    assert rpc(mesh, key2, device2, "session", {"session_id": sid})[0] == 403


@pytest.mark.parametrize(
    "text",
    [
        "/tool filesystem.read {}",
        "/remember semantic secret = test",
        "Remember that my editor is Test",
        "/plan test",
    ],
)
def test_mobile_cannot_run_privileged_commands(mesh, text):
    key, device = paired(mesh)
    sid = rpc(mesh, key, device, "new_session")[1]["payload"]["session_id"]
    assert (
        rpc(mesh, key, device, "chat", {"session_id": sid, "text": text})[1]["error"]
        == "MESH.COMMAND_DENIED"
    )


def test_signatures_expiry_schema_and_origin_fail_closed(mesh):
    manager, _, phone = mesh
    key, device = paired(mesh)
    other = ec.generate_private_key(ec.SECP256R1())
    assert rpc(mesh, other, device, "status")[1]["error"] == "MESH.BAD_SIGNATURE"
    assert (
        rpc(mesh, key, device, "status", issued=int(time.time()) - 120)[1]["error"]
        == "MESH.REQUEST_EXPIRED"
    )
    assert (
        rpc(mesh, key, device, "session", {"session_id": "bad"})[1]["error"] == "MESH.INPUT_INVALID"
    )
    assert (
        rpc(mesh, key, device, "status", {"unexpected": "test"})[1]["error"] == "MESH.INPUT_INVALID"
    )
    assert phone.post(
        "/rpc", json={"message": "private-input", "signature": "x", "extra": "private"}
    ).json() == {"error": "MESH.INVALID_PACKET"}
    assert phone.get("/", headers={"origin": "https://other.example"}).status_code == 403
    assert phone.get("/", headers={"host": "other.example"}).status_code == 403
    with TestClient(manager.public, base_url="http://127.0.0.1:9443") as insecure:
        assert insecure.get("/").status_code == 403
    assert phone.get("/memory").status_code == 404


def test_revoke_blocks_cached_results_and_old_key_repair(mesh):
    manager, desktop, phone = mesh
    key, device = paired(mesh, search=True)
    rid = str(uuid4())
    assert rpc(mesh, key, device, "search", {"query": "report"}, rid)[1]["status"] == "VERIFIED"
    desktop.post("/developer/mesh/revoke", json={"device_id": device})
    assert (
        rpc(mesh, key, device, "search", {"query": "report"}, rid)[1]["error"]
        == "MESH.DEVICE_DENIED"
    )
    assert (
        phone.post("/pair", json=claim(key, manager.store.ticket()).model_dump()).json()["error"]
        == "MESH.KEY_ALREADY_REGISTERED"
    )
    key2, device2 = paired(mesh)
    assert device2 != device and rpc(mesh, key2, device2, "status")[1]["status"] == "VERIFIED"


def test_search_readonly_scope_and_capability(mesh, tmp_path):
    manager, _, _ = mesh
    key, device = paired(mesh)
    assert (
        rpc(mesh, key, device, "search", {"query": "report"})[1]["error"]
        == "MESH.CAPABILITY_DENIED"
    )
    key2, device2 = paired(mesh, search=True)
    folder = tmp_path / "tool-sandbox"
    folder.mkdir(exist_ok=True)
    (folder / "report.txt").write_text("Synthetic document")
    (tmp_path / "private-report.txt").write_text("Outside sandbox")
    value = rpc(mesh, key2, device2, "search", {"query": "report"})[1]
    assert value["status"] == "VERIFIED", value
    assert "report.txt" in str(value) and "private-report" not in str(value)
    assert "Synthetic document" not in str(value)
    assert (
        rpc(mesh, key2, device2, "search", {"query": "report", "path": ".."})[1]["status"]
        == "ERROR"
    )


def test_interrupted_request_does_not_reexecute_after_restart(mesh):
    manager, _, _ = mesh
    key, device = paired(mesh)
    rid = str(uuid4())
    digest = "interrupted"
    assert manager.store.reserve(device, rid, digest) is None
    restarted = MeshStore(manager.runtime.settings.data_dir)
    assert restarted.node_id == manager.store.node_id
    with pytest.raises(MeshError, match="MESH.RESULT_UNCERTAIN"):
        restarted.reserve(device, rid, digest)


@pytest.mark.parametrize(
    "policy", ["local_only", "CORE_ONLY", "TRUSTED_DEVICES", "OWNER_DEVICES", "ALL_APPROVED"]
)
def test_remote_context_obeys_replication_and_secrets(policy):
    resource = ResourcePolicy(
        sensitivity="PRIVATE",
        allowed_audiences=["owner"],
        subjects=["owner"],
        disclosure_owner="owner",
        source_actor="owner",
        replication_policy=policy,
    )
    assert decide(Principal(), resource).allowed
    token = REMOTE_DEVICE.set(str(uuid4()))
    try:
        assert decide(Principal(), resource).allowed == (policy not in {"local_only", "CORE_ONLY"})
        assert not decide(
            Principal(), resource.model_copy(update={"sensitivity": "SECRET"})
        ).allowed
    finally:
        REMOTE_DEVICE.reset(token)


def test_tls_setup_never_accepts_public_or_wildcard_bind(tmp_path):
    for address in ["0.0.0.0", "8.8.8.8", "::1"]:
        with pytest.raises(ValueError):
            prepare(tmp_path, address)
    cert = prepare(tmp_path, "127.0.0.1")
    assert cert.is_file()
    assert b"ENCRYPTED PRIVATE KEY" in (tmp_path / "mesh/tls/key.pem").read_bytes()
    assert not (tmp_path / "mesh/tls/ca-key.pem").exists()
    with pytest.raises(MeshError, match="ALREADY_CONFIGURED"):
        prepare(tmp_path, "127.0.0.1")


def test_static_mobile_assets_and_listener_default_off(mesh):
    manager, desktop, phone = mesh
    assert not manager.status()["listening"]
    for path in ["/", "/client.js", "/style.css"]:
        response = phone.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert desktop.post("/developer/mesh/code", json={}).json()["error"] == "MESH.OFFLINE"


def test_real_tls_listener_trust_and_shutdown(mesh, tmp_path):
    manager, desktop, _ = mesh
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    prepare(tmp_path, "127.0.0.1", port)
    started = desktop.post("/developer/mesh/start", json={})
    assert started.status_code == 200, started.text
    url = started.json()["url"]
    with pytest.raises(httpx.ConnectError):
        httpx.get(url, timeout=3, trust_env=False)
    context = ssl.create_default_context(cafile=str(tmp_path / "mesh/tls/ca.pem"))
    with httpx.Client(base_url=url, verify=context, trust_env=False, timeout=5) as client:
        assert client.get("/").status_code == 200
        key = ec.generate_private_key(ec.SECP256R1())
        code = desktop.post("/developer/mesh/code", json={}).json()["code"]
        paired = client.post("/pair", json=claim(key, code).model_dump()).json()
        assert paired["status"] == "PENDING"
        assert (
            desktop.post(
                "/developer/mesh/approve", json={"device_id": paired["device_id"]}
            ).status_code
            == 200
        )
        request = {
            "protocol": 1,
            "device_id": paired["device_id"],
            "request_id": str(uuid4()),
            "issued_at": int(time.time()),
            "operation": "status",
            "payload": {},
        }
        result = client.post("/rpc", json=packet(key, request)).json()
        verify(paired["public_key"], decode(result["message"]), result["signature"])
        assert json.loads(decode(result["message"]))["payload"]["health"] == "ONLINE"
    assert desktop.post("/developer/mesh/stop", json={}).json()["listening"] is False
    with pytest.raises(httpx.ConnectError):
        httpx.get(url, verify=context, timeout=3, trust_env=False)


def test_revocation_during_operation_never_releases_result(mesh):
    manager, _, _ = mesh
    key, device = paired(mesh, search=True)

    async def scenario():
        began, release = asyncio.Event(), asyncio.Event()
        original = manager.execute

        async def delayed(value):
            began.set()
            await release.wait()
            return {"private": "must not escape"}

        manager.execute = delayed
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager.public), base_url=manager.origin
            ) as client:
                request = {
                    "protocol": 1,
                    "device_id": device,
                    "request_id": str(uuid4()),
                    "issued_at": int(time.time()),
                    "operation": "search",
                    "payload": {"query": "report"},
                }
                task = asyncio.create_task(client.post("/rpc", json=packet(key, request)))
                await began.wait()
                manager.store.revoke(device)
                status_request = {
                    **request,
                    "request_id": str(uuid4()),
                    "operation": "status",
                    "payload": {},
                }
                denied = await asyncio.wait_for(
                    client.post("/rpc", json=packet(key, status_request)), timeout=1
                )
                assert denied.status_code == 403  # Do not wait behind the active operation.
                release.set()
                response = await task
                assert response.status_code == 403
                assert "must not escape" not in response.text
        finally:
            manager.execute = original

    asyncio.run(scenario())


def test_concurrent_duplicate_executes_once(mesh):
    manager, _, _ = mesh
    key, device = paired(mesh, search=True)

    async def scenario():
        began, release = asyncio.Event(), asyncio.Event()
        original, calls = manager.execute, []

        async def delayed(value):
            calls.append(value.request_id)
            began.set()
            await release.wait()
            return {"files": []}

        manager.execute = delayed
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager.public), base_url=manager.origin
            ) as client:
                body = {
                    "protocol": 1,
                    "device_id": device,
                    "request_id": str(uuid4()),
                    "issued_at": int(time.time()),
                    "operation": "search",
                    "payload": {"query": "report"},
                }
                first = asyncio.create_task(client.post("/rpc", json=packet(key, body)))
                await began.wait()
                second = asyncio.create_task(client.post("/rpc", json=packet(key, body)))
                await asyncio.sleep(0.05)
                release.set()
                one, two = await asyncio.gather(first, second)
                assert len(calls) == 1 and one.status_code == two.status_code == 200
                assert decode(one.json()["message"]) == decode(two.json()["message"])
        finally:
            manager.execute = original

    asyncio.run(scenario())


def test_actual_memory_and_retrieval_context_excludes_core_only(mesh, tmp_path):
    from adam.core.runtime import ChatRequest
    from adam.knowledge.contracts import SourcePolicy
    from adam.knowledge.retrieval import QueryRequest, RetrievalService
    from test_retrieval import TestEmbedder, make_service

    manager, _, _ = mesh
    runtime = manager.runtime
    asyncio.run(runtime.chat(ChatRequest(text="/remember preference editor = CoreOnlyEditor")))
    assert "CoreOnlyEditor" in runtime.memories.context("editor")
    knowledge, ingest = make_service(tmp_path)
    ingest("core.md", "Core-only launch command is launch_secret_alpha.")
    shared = ingest(
        "shared.md",
        "Shared launch command is launch_public_beta.",
        policy=SourcePolicy(replication_policy="OWNER_DEVICES"),
    )
    retrieval = RetrievalService(knowledge, TestEmbedder())
    try:
        assert (
            "launch_secret_alpha" in retrieval.search(QueryRequest(query="launch command")).context
        )
        token = REMOTE_DEVICE.set(str(uuid4()))
        try:
            assert "CoreOnlyEditor" not in runtime.memories.context("editor")
            result = retrieval.search(QueryRequest(query="launch command"))
            assert result.evidence and all(
                e.source.source_id == shared.source_id for e in result.evidence
            )
            assert "launch_secret_alpha" not in result.context
            assert "launch_public_beta" in result.context
        finally:
            REMOTE_DEVICE.reset(token)
        assert "CoreOnlyEditor" in runtime.memories.context("editor")
    finally:
        retrieval.close()


def test_expired_pair_code_and_private_start_errors(mesh, tmp_path):
    import sqlite3

    manager, desktop, phone = mesh
    key = ec.generate_private_key(ec.SECP256R1())
    code = manager.store.ticket()
    with sqlite3.connect(manager.store.path) as db:
        db.execute("UPDATE tickets SET expires=0")
    assert (
        phone.post("/pair", json=claim(key, code).model_dump()).json()["error"]
        == "MESH.PAIR_CODE_INVALID"
    )
    (tmp_path / "mesh/network.json").write_text("bad json")
    assert desktop.post("/developer/mesh/start", json={}).json() == {
        "error": "MESH.TLS_UNAVAILABLE"
    }
    assert not manager.status()["listening"]


def test_damaged_optional_mesh_identity_does_not_crash_local_chat(tmp_path):
    folder = tmp_path / "mesh"
    folder.mkdir()
    registry = folder / "registry.sqlite3"
    registry.write_bytes(b"damaged synthetic registry")
    original = registry.read_bytes()
    boundary = desktop_app(
        Settings(data_dir=tmp_path, features={"mobile_mesh": True}), NONCE, probe=True
    )
    with TestClient(
        boundary, base_url="http://localhost", headers={"x-adam-desktop": NONCE}
    ) as client:
        client.post("/desktop/setup", json={"password": PASSWORD})
        client.post("/auth/login", json={"password": PASSWORD})
        client.post("/auth/elevate", json={"password": PASSWORD})
        status = client.get("/developer/mesh").json()
        assert status["error"] == "MESH.IDENTITY_UNAVAILABLE" and not status["listening"]
        assert client.post("/developer/mesh/start", json={}).status_code == 409
        assert (
            client.post("/desktop/chat", json={"text": "Local chat still works"}).status_code == 200
        )
    assert registry.read_bytes() == original


def test_revoked_key_cannot_repair_using_alternative_der_encoding(mesh):
    manager, desktop, phone = mesh
    key, device = paired(mesh)
    desktop.post("/developer/mesh/revoke", json={"device_id": device})
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint
    )
    # Same P-256 key, compressed EC point in SubjectPublicKeyInfo DER.
    compressed = encode(
        bytes.fromhex("3039301306072a8648ce3d020106082a8648ce3d030107032200") + point
    )
    assert fingerprint(compressed) == fingerprint(export(key))
    body = claim(key, manager.store.ticket())
    signed = f"1\n{body.code}\n{body.label}\n{compressed}".encode()
    r, s = utils.decode_dss_signature(key.sign(signed, ec.ECDSA(hashes.SHA256())))
    body = body.model_copy(
        update={
            "public_key": compressed,
            "signature": encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")),
        }
    )
    response = phone.post("/pair", json=body.model_dump())
    assert response.json()["error"] == "MESH.KEY_ALREADY_REGISTERED"


def test_mobile_notifications_redacted_and_revocation_fallback(mesh):
    from datetime import UTC, datetime

    manager, desktop, _ = mesh
    key, device = paired(mesh)
    _, created = rpc(mesh, key, device, "new_session")
    sid = created["payload"]["session_id"]
    response = desktop.post(
        "/operations/schedule",
        json={
            "request_id": str(uuid4()),
            "text": "Private appointment details",
            "due_at": datetime.now(UTC).isoformat(),
            "route": "ACTIVE",
            "session_id": sid,
        },
    )
    assert response.status_code == 200
    manager.app.state.operations.tick()
    _, status = rpc(mesh, key, device, "status")
    alerts = status["payload"]["notifications"]
    assert len(alerts) == 1
    assert "Private appointment" not in str(alerts) and sid not in str(alerts)
    assert desktop.get("/operations/inbox").json() == []
    desktop.post("/developer/mesh/revoke", json={"device_id": device})
    assert rpc(mesh, key, device, "status")[0] == 403
    assert desktop.get("/operations/inbox").json()[0]["text"] == "Private appointment details"
