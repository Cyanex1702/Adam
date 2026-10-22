import base64
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest
from adam.core.config import FeatureFlags, Settings
from adam.desktop.service import desktop_app
from adam.voice.api import retain
from adam.voice.contracts import AudioInput, SpeechInput, TurnInput, VoiceConfig, VoiceError
from adam.voice.providers import LocalSpeech, decode_audio, noise_process
from adam.voice.turns import PauseProfile, interruption
from fastapi.testclient import TestClient
from pydantic import ValidationError

NONCE = "synthetic-voice-desktop-capability-827197412"
PASSWORD = "synthetic-voice-owner-passphrase-82719"


def audio(seconds=1, **kwargs):
    return AudioInput(pcm16=base64.b64encode(bytes(32000 * seconds)).decode(), **kwargs)


@pytest.mark.parametrize(
    "value",
    ["bad!", "AAAA", "AA==", base64.b64encode(bytes(1920002)).decode()],
    ids=["invalid-base64", "too-short", "unaligned", "over-duration"],
)
def test_audio_rejects_invalid_base64_alignment_and_duration(value):
    with pytest.raises((VoiceError, ValidationError)):
        decode_audio(AudioInput(pcm16=value))


def test_pcm_limits_and_noise_adapter_do_not_amplify_noise():
    assert len(decode_audio(audio(60))) == 960000
    samples = np.full(16000, 0.01, dtype=np.float32)
    assert np.max(np.abs(noise_process(samples))) < 1e-6
    with pytest.raises(ValidationError):
        AudioInput(pcm16="", sample_rate=48000)
    with pytest.raises(ValidationError):
        SpeechInput(text="fixture", language="ur")


@pytest.mark.parametrize(
    "text,kind",
    [
        ("stop!", "HARD_INTERRUPT"),
        ("please stop", "HARD_INTERRUPT"),
        ("mhm", "ACKNOWLEDGEMENT"),
        ("mm-hm", "ACKNOWLEDGEMENT"),
        ("actually open the other one", "CORRECTION"),
        ("tell me more", "NEW_REQUEST"),
    ],
)
def test_interruptions(text, kind):
    assert interruption(text, 0.9) == kind
    assert interruption(text, 0.2) == "UNCERTAIN"


@pytest.mark.parametrize(
    "text", ["open my", "I need the", "because", "ایک اور", "then...", "Could you,", "mera"]
)
def test_incomplete_sentences_wait_through_thinking_pauses(text):
    profile = PauseProfile()
    body = TurnInput(text=text, confidence=0.9, silence_ms=2000)
    result = profile.decide(body)
    assert result["recommended_action"] == "WAIT"
    assert "LINGUISTICALLY_INCOMPLETE" in result["reason_codes"]
    assert (
        result["wait_ms"]
        > profile.decide(TurnInput(text="What time is it?", confidence=0.9, silence_ms=2000))[
            "wait_ms"
        ]
    )


def test_complete_turn_speech_low_confidence_and_bounded_reversible_adaptation():
    profile = PauseProfile()
    assert (
        profile.decide(TurnInput(text="Please explain that.", confidence=0.9, silence_ms=1200))[
            "recommended_action"
        ]
        == "TAKE_TURN"
    )
    assert (
        profile.decide(
            TurnInput(
                text="Please explain that.", confidence=0.9, silence_ms=12000, speech_active=True
            )
        )["recommended_action"]
        == "LISTEN"
    )
    assert (
        profile.decide(TurnInput(text="Delete it.", confidence=0.2, silence_ms=12000))[
            "recommended_action"
        ]
        == "WAIT"
    )
    for _ in range(200):
        profile.decide(TurnInput(text="", confidence=1, silence_ms=0, observed_pause_ms=10000))
    assert 600 <= profile.pause_ms <= 1600
    profile.decide(TurnInput(text="", confidence=1, silence_ms=0, reset_profile=True))
    assert profile.pause_ms == 900


def test_confidence_raw_transcript_and_repair_remain_distinct(tmp_path):
    speech = LocalSpeech(VoiceConfig(assets_dir=tmp_path))
    segment = SimpleNamespace(
        text="open the other one", no_speech_prob=0.2, avg_logprob=-2, start=0, end=2
    )
    result = speech.transcript([segment], "en", 0.99)
    assert result["requires_review"]
    assert result["raw_transcript"] == result["repaired_transcript"]
    assert not result["repair_applied"] and result["confidence"] < 0.2
    segment.no_speech_prob = 0.9
    assert speech.transcript([segment], "en", 0.9)["raw_transcript"] == ""


def test_retention_default_off_partial_never_written_and_enabled_bounded(tmp_path):
    settings = Settings(data_dir=tmp_path)
    retain(tmp_path, audio(), settings)
    assert not (tmp_path / "voice").exists()
    settings.voice = VoiceConfig(retain_audio=True, retention_max_files=2)
    retain(tmp_path, audio(partial=True), settings)
    assert not (tmp_path / "voice").exists()
    for _ in range(5):
        retain(tmp_path, audio(), settings)
    assert len(list((tmp_path / "voice/audio").glob("*.wav"))) == 2
    for path in (tmp_path / "voice/audio").glob("*.wav"):
        os.utime(path, (1, 1))
    retain(tmp_path, audio(), settings)
    assert len(list((tmp_path / "voice/audio").glob("*.wav"))) == 1


def voice_client(root, enabled=True):
    settings = Settings(
        data_dir=root,
        features=FeatureFlags(voice=enabled),
        voice=VoiceConfig(assets_dir=root / "missing-assets"),
    )
    app = desktop_app(settings, NONCE, probe=True)
    app.ready.state.models.manager.observe = lambda: {"mode": "NORMAL"}
    return TestClient(app, base_url="http://localhost", headers={"x-adam-desktop": NONCE})


def login(client):
    client.post("/desktop/setup", json={"password": PASSWORD})
    assert client.post("/auth/login", json={"password": PASSWORD}).status_code == 200


def test_voice_requires_both_capability_and_authentication_and_has_text_fallback(tmp_path):
    with voice_client(tmp_path) as client:
        assert client.get("/voice/status").status_code == 401
        login(client)
        assert client.get("/voice/status").json()["stt_ready"] is False
        assert client.get("/identity").json()["capabilities"]["voice"] == "CONFIGURED_LOCAL_DESKTOP"
        assert (
            client.post("/voice/transcribe", json=audio().model_dump()).json()["error"]
            == "VOICE.ASSETS_MISSING"
        )
        assert (
            client.post(
                "/desktop/chat", json={"text": "/remember preference drink = Tea"}
            ).status_code
            == 200
        )
        client.headers["origin"] = "http://localhost:8765"
        assert client.get("/voice/status").status_code == 403


def test_voice_disabled_and_unknown_fields_do_not_echo_audio(tmp_path):
    with voice_client(tmp_path, enabled=False) as client:
        login(client)
        assert not client.get("/voice/status").json()["enabled"]
        assert (
            client.post("/voice/speak", json={"text": "synthetic private text"}).json()["error"]
            == "VOICE.DISABLED"
        )
        result = client.post(
            "/voice/transcribe", json={"pcm16": "private-audio", "authority": "owner"}
        )
        assert result.status_code == 422 and "private-audio" not in result.text
        result = client.post("/voice/turn", content=b"x" * 16385)
        assert result.status_code == 413


def test_voice_profiles_and_transcripts_do_not_grant_authority_or_create_history(
    tmp_path, monkeypatch
):
    def transcript(self, waveform, body):
        return {
            "raw_transcript": "delete all files",
            "repaired_transcript": "delete all files",
            "confidence": 0.2,
            "requires_review": True,
        }

    monkeypatch.setattr(LocalSpeech, "transcribe", transcript)
    with voice_client(tmp_path) as client:
        login(client)
        result = client.post("/voice/transcribe", json=audio().model_dump()).json()
        assert result["requires_review"] and result["interruption"] == "UNCERTAIN"
        assert client.get("/sessions").json() == []
        value = {"text": "hello", "confidence": 1, "silence_ms": 0, "observed_pause_ms": 1600}
        owner = client.post("/voice/turn", json=value).json()["pause_profile_ms"]
        client.post("/auth/switch", json={"mode": "demo"})
        demo = client.post(
            "/voice/turn", json={"text": "", "confidence": 1, "silence_ms": 0}
        ).json()["pause_profile_ms"]
        assert owner > demo == 900
        assert not list(tmp_path.rglob("*.wav"))


def test_interruption_decoding_does_not_wait_for_speech_synthesis(tmp_path, monkeypatch):
    synthesizing = threading.Event()
    heard = threading.Event()

    def synthesize(self, body):
        synthesizing.set()
        assert heard.wait(timeout=3), "STT was blocked behind synthesis"
        return {"pcm16": "AAA=", "sample_rate": 24000}

    def transcribe(self, waveform, body):
        heard.set()
        return {"raw_transcript": "stop", "confidence": 0.9, "requires_review": False}

    monkeypatch.setattr(LocalSpeech, "synthesize", synthesize)
    monkeypatch.setattr(LocalSpeech, "transcribe", transcribe)
    with voice_client(tmp_path) as client, ThreadPoolExecutor(max_workers=1) as executor:
        login(client)
        pending = executor.submit(client.post, "/voice/speak", json={"text": "fixture"})
        assert synthesizing.wait(timeout=3)
        result = client.post("/voice/transcribe", json=audio().model_dump())
        assert result.status_code == 200 and result.json()["interruption"] == "HARD_INTERRUPT"
        assert pending.result(timeout=3).status_code == 200


def test_windows_engine_selection_preserves_pcm_and_rejects_unsupported_language(monkeypatch):
    from adam.voice import windows
    from adam.voice.contracts import SpeechInput

    captured = []

    def synthesize(text, language):
        captured.append((text, language))
        return b"\x00\x01" * 24000

    monkeypatch.setattr(windows, "synthesize", synthesize)
    speech = LocalSpeech(VoiceConfig(tts_engine="windows"))
    result = speech.synthesize(SpeechInput(text="<speak>literal input</speak>"))
    assert result["provider"] == "windows" and result["duration_seconds"] == 1
    assert base64.b64decode(result["pcm16"]) == b"\x00\x01" * 24000
    assert captured == [("<speak>literal input</speak>", "en-us")]


def test_windows_engine_rejects_unsupported_language_before_com():
    from adam.voice import windows

    with pytest.raises(VoiceError, match="VOICE.LANGUAGE_UNAVAILABLE"):
        windows.synthesize("Bonjour", "fr-fr")
