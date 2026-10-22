import base64
from types import SimpleNamespace

import numpy as np
import pytest
from adam.core.config import FeatureFlags, Settings
from adam.desktop.service import desktop_app
from adam.security.request import AUTHORITY
from adam.voice.contracts import AudioInput, VoiceConfig, VoiceError
from adam.voice.social import SocialVoice
from adam.voice.speakers import SpeakerStore, identify, normalized
from fastapi.testclient import TestClient
from pydantic import ValidationError


class Cipher:
    def seal(self, value):
        return base64.b64encode(value)

    def open(self, value):
        return base64.b64decode(value)


def vector(index=0):
    return np.eye(32, dtype=np.float32)[index]


def test_templates_are_scoped_revocable_and_never_exposed(tmp_path):
    store = SpeakerStore(tmp_path, Cipher())
    owner = store.put("Owner", "owner", vector())
    assert store.records() == [owner]
    assert "vector" not in store.records()[0]
    assert identify(vector(), store.records(vectors=True), 0.7, 0.12)["role"] == "owner"
    assert not identify(vector(), store.records(vectors=True), 0.7, 0.12)["authority_granted"]
    assert SpeakerStore(tmp_path / "guest", Cipher()).records() == []
    with pytest.raises(VoiceError, match="OWNER_ALREADY_ENROLLED"):
        store.put("Other", "owner", vector(1))
    store.remove(owner["speaker_id"])
    assert store.records() == []
    assert not list(tmp_path.rglob("*.wav"))


def test_ambiguous_unknown_and_invalid_vectors_fail_closed():
    records = [
        dict(speaker_id=str(i), label=str(i), role="owner", vector=vector()) for i in range(2)
    ]
    assert identify(vector(), records, 0.7, 0.12)["role"] == "unknown"
    assert identify(vector(1), records[:1], 0.7, 0.12)["role"] == "unknown"
    assert identify(vector(), [], 0.7, 0.12)["role"] == "unknown"
    for value in [[], [0] * 32, [float("nan")] * 32, [[1] * 32]]:
        with pytest.raises(VoiceError):
            normalized(value)
    with pytest.raises(ValidationError):
        FeatureFlags(speaker_id=True)


def test_capacity_and_authority_revocation_roll_back(tmp_path):
    store = SpeakerStore(tmp_path, Cipher())
    for i in range(8):
        store.put(str(i), "guest", vector(i))
    with pytest.raises(VoiceError, match="SPEAKER_LIMIT"):
        store.put("extra", "guest", vector())
    calls = []

    def revoked():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("revoked")

    token = AUTHORITY.set(revoked)
    try:
        with pytest.raises(RuntimeError, match="revoked"):
            store.remove(store.records()[0]["speaker_id"])
    finally:
        AUTHORITY.reset(token)
    assert len(store.records()) == 8


def social(tmp_path, monkeypatch):
    speech = SimpleNamespace(
        root=tmp_path,
        transcribe=lambda a, b: dict(
            raw_transcript="hello there", confidence=0.95, requires_review=False
        ),
        transcript=lambda *a: dict(raw_transcript="", confidence=0, requires_review=True),
    )
    service = SocialVoice(speech, VoiceConfig())
    monkeypatch.setattr(service, "embed", lambda a: vector())
    monkeypatch.setattr(service, "overlap", lambda a: [])
    monkeypatch.setattr(service, "segments", lambda a: [dict(start=0, end=2, cluster=0)])
    return service


def test_unknown_background_partial_replay_and_overlap_require_review(tmp_path, monkeypatch):
    service = social(tmp_path, monkeypatch)
    audio = np.zeros(32000, dtype=np.float32)
    body = AudioInput(pcm16="unused")
    first = service.analyze(audio, body, tmp_path)
    assert first["speaker"]["role"] == "unknown" and first["requires_review"]
    assert service.analyze(audio, body, tmp_path)["replay_risk"] == "REPEATED_AUDIO"
    assert (
        service.analyze(audio, AudioInput(pcm16="unused", partial=True), tmp_path)[
            "speaker_processing"
        ]
        == "FINAL_REQUIRED"
    )
    monkeypatch.setattr(service, "overlap", lambda a: [(0, 1)])
    mixed = service.analyze(audio, body, tmp_path)
    assert mixed["raw_transcript"] == "" and mixed["requires_review"]
    assert mixed["utterances"][0]["overlap"]
    assert mixed["clarification"] and mixed["spatial"] is None


def test_multiple_speakers_never_merge_into_a_command(tmp_path, monkeypatch):
    service = social(tmp_path, monkeypatch)
    monkeypatch.setattr(
        service,
        "segments",
        lambda a: [dict(start=0, end=1, cluster=0), dict(start=1, end=2, cluster=1)],
    )
    result = service.analyze(
        np.zeros(32000, dtype=np.float32), AudioInput(pcm16="unused"), tmp_path
    )
    assert result["raw_transcript"] == "" and len(result["utterances"]) == 2
    assert result["requires_review"]


def test_owner_background_needs_address_and_never_grants_authority(tmp_path, monkeypatch):
    service = social(tmp_path, monkeypatch)
    monkeypatch.setattr(
        SpeakerStore,
        "records",
        lambda *a, **kw: [
            dict(speaker_id="fixture", label="Fixture", role="owner", vector=vector())
        ],
    )
    samples = np.zeros(32000, dtype=np.float32)
    result = service.analyze(samples, AudioInput(pcm16="unused", mode="conversation"), tmp_path)
    assert result["speaker"]["role"] == "owner" and result["requires_review"]
    assert not result["speaker"]["authority_granted"]
    service.speech.transcribe = lambda *a: dict(
        raw_transcript="Adam hello", confidence=0.95, requires_review=False
    )
    result = service.analyze(
        samples + 0.01, AudioInput(pcm16="unused", mode="conversation"), tmp_path
    )
    assert not result["requires_review"]


def test_revocation_during_enrollment_prevents_template_commit(tmp_path):
    store = SpeakerStore(tmp_path, Cipher())
    calls = []

    def revoked():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("revoked")

    token = AUTHORITY.set(revoked)
    try:
        with pytest.raises(RuntimeError, match="revoked"):
            store.put("Fixture", "owner", vector())
    finally:
        AUTHORITY.reset(token)
    assert store.records() == []


def test_enrollment_requires_fresh_password_consent_and_private_desktop(tmp_path, monkeypatch):
    nonce = "speaker-test-private-capability-87654321"
    password = "speaker-test-owner-password-87654321"
    settings = Settings(data_dir=tmp_path, features=FeatureFlags(voice=True, speaker_id=True))
    app = desktop_app(settings, nonce, probe=True)
    app.ready.state.models.manager.observe = lambda: {"mode": "NORMAL"}
    monkeypatch.setattr(
        SocialVoice,
        "enroll",
        lambda *args: {"speaker_id": "fixture", "role": "owner", "label": "Fixture"},
    )
    body = dict(
        pcm16=base64.b64encode(bytes(6 * 32000)).decode(),
        label="Fixture",
        role="owner",
        consent=True,
    )
    with TestClient(app, base_url="http://localhost", headers={"x-adam-desktop": nonce}) as client:
        assert client.get("/voice/speakers").status_code == 401
        client.post("/desktop/setup", json={"password": password})
        client.post("/auth/login", json={"password": password})
        assert client.post("/developer/voice/enroll", json=body).status_code == 403
        assert client.post("/auth/elevate", json={"password": password}).status_code == 200
        assert (
            client.post("/developer/voice/enroll", json={**body, "consent": False}).status_code
            == 422
        )
        assert client.post("/developer/voice/enroll", json=body).status_code == 200
        assert client.get("/sessions").json() == []
        client.post("/auth/switch", json={"mode": "demo"})
        assert client.post("/developer/voice/enroll", json=body).status_code == 403
