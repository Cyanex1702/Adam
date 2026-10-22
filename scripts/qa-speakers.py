"""Real CPU models over public recordings and the private source/frozen service."""

import argparse
import base64
import gc
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import psutil
from adam import APP_VERSION
from adam.voice.contracts import VoiceConfig
from adam.voice.providers import LocalSpeech
from adam.voice.social import SocialVoice
from adam.voice.speakers import identify
from faster_whisper.audio import decode_audio


def pcm(audio):
    return base64.b64encode((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()).decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--real-chat", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    social = SocialVoice(LocalSpeech(VoiceConfig()), VoiceConfig())
    fixture = social.root / "1-two-speakers-en.wav"
    source = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/1-two-speakers-en.wav"
    if not fixture.exists():
        response = httpx.get(source, timeout=120, follow_redirects=True)
        response.raise_for_status()
        fixture.write_bytes(response.content)
    assert (
        hashlib.sha256(fixture.read_bytes()).hexdigest()
        == "f1c877dc01595e28be7147bf2fe38e5268147a868bf3fdb5c37b97f5940e21f3"
    )
    with wave.open(str(fixture)) as stream:
        audio = (
            np.frombuffer(stream.readframes(stream.getnframes()), "<i2").astype("float32") / 32768
        )
    checks, metrics = [], {}

    def check(name, value):
        if not value:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(
                    dict(
                        release=APP_VERSION,
                        passed=False,
                        failure=name,
                        completed_checks=checks,
                        metrics=metrics,
                    ),
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            raise AssertionError(name)
        checks.append(name)

    start = time.monotonic()
    segments = social.segments(audio)
    overlap = social.overlap(audio)
    vectors = [
        social.embed(audio[int(s["start"] * 16000) : int(s["end"] * 16000)]) for s in segments
    ]
    metrics["cpu_diarization_seconds"] = round(time.monotonic() - start, 3)
    metrics["segments"] = segments
    metrics["same_and_other_scores"] = [[round(float(a @ b), 3) for b in vectors] for a in vectors]
    check("real fixture has two speaker clusters", len({s["cluster"] for s in segments}) == 2)
    check("sequential fixture has no detected overlap", not overlap)
    records = [
        dict(speaker_id="public-A", role="owner", label="Public A", vector=vectors[0]),
        dict(speaker_id="public-B", role="guest", label="Public B", vector=vectors[2]),
    ]
    check(
        "held-out first voice matches owner template",
        identify(vectors[1], records, 0.7, 0.12)["role"] == "owner",
    )
    check(
        "held-out second voice matches guest template",
        identify(vectors[3], records, 0.7, 0.12)["role"] == "guest",
    )
    mixed = (audio[26000:58000] + audio[150000:182000]) * 0.5
    check("synthetic simultaneous voices detected", bool(social.overlap(mixed)))
    # The app loads its own models. Release the harness's duplicate CPU sessions
    # before measuring combined STT/diarization/LLM memory on a 16 GB machine.
    del social
    gc.collect()
    # Public prerecorded fixtures only; no personal microphone or owner template.
    jfk = Path(os.environ["LOCALAPPDATA"]) / "ADAM/qa/jfk.flac"
    if not jfk.exists():
        response = httpx.get(
            "https://raw.githubusercontent.com/openai/whisper/main/tests/jfk.flac", timeout=60
        )
        response.raise_for_status()
        jfk.parent.mkdir(parents=True, exist_ok=True)
        jfk.write_bytes(response.content)
    enrollment = decode_audio(str(jfk), sampling_rate=16000)[:160000]
    with tempfile.TemporaryDirectory(prefix="adam-speaker-qa-") as directory:
        command = (
            [str(args.service.resolve())]
            if args.service
            else [sys.executable, "-m", "adam.desktop.service"]
        )
        if not args.real_chat:
            command.append("--probe")
        command += ["--data-dir", directory, "--config", str(repo / "adam.compact.toml")]
        child = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            receipt_queue = queue.Queue()
            threading.Thread(
                target=lambda: receipt_queue.put(child.stdout.readline()), daemon=True
            ).start()
            line = receipt_queue.get(timeout=150)
            if not line:
                raise RuntimeError(child.stderr.read()[-3000:])
            receipt = json.loads(line)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{receipt['port']}",
                timeout=240,
                headers={"x-adam-desktop": receipt["nonce"]},
            ) as client:
                password = "public-speaker-qa-owner-password-938175"
                check(
                    "unauthenticated speaker data denied",
                    client.get("/voice/speakers").status_code == 401,
                )
                client.post("/desktop/setup", json={"password": password}).raise_for_status()
                client.post("/auth/login", json={"password": password}).raise_for_status()
                status = client.get("/voice/status").json()
                check(
                    "installed speaker assets ready",
                    status["speaker_ready"] and status["diarization_ready"],
                )
                check(
                    "mono spatial audio explicitly deferred",
                    status["spatial_audio"] == "DEFERRED_MONO_CAPTURE",
                )
                body = dict(
                    pcm16=pcm(enrollment), label="Public QA fixture", role="owner", consent=True
                )
                check(
                    "enrollment requires fresh elevation",
                    client.post("/developer/voice/enroll", json=body).status_code == 403,
                )
                client.post("/auth/elevate", json={"password": password}).raise_for_status()
                check(
                    "enrollment requires consent",
                    client.post(
                        "/developer/voice/enroll", json={**body, "consent": False}
                    ).status_code
                    == 422,
                )
                started = time.monotonic()
                response = client.post("/developer/voice/enroll", json=body)
                if response.status_code != 200:
                    raise AssertionError("real enrollment: " + response.text)
                enrolled = response.json()
                metrics["enrollment_seconds"] = round(time.monotonic() - started, 3)
                check(
                    "real encrypted template enrolled",
                    client.get("/voice/speakers").json() == [enrolled],
                )

                def transcribe(samples, **kwargs):
                    response = client.post(
                        "/voice/transcribe", json=dict(pcm16=pcm(samples), language="en", **kwargs)
                    )
                    if response.status_code != 200:
                        metrics["failed_request_error"] = response.json().get("error")
                        metrics["available_ram_mib_at_failure"] = round(
                            psutil.virtual_memory().available / 1024**2
                        )
                        check("transcription request accepted", False)
                    return response.json()

                result = transcribe(enrollment)
                check(
                    "owner segments recognized only as advisory",
                    any(u["speaker"]["role"] == "owner" for u in result["utterances"])
                    and all(
                        u["speaker"]["authority_granted"] is False for u in result["utterances"]
                    ),
                )
                check(
                    "short uncertain owner segments still require review", result["requires_review"]
                )
                check(
                    "exact replay requires review",
                    transcribe(enrollment)["replay_risk"] == "REPEATED_AUDIO",
                )
                unknown = transcribe(audio[26000:104000])
                check(
                    "unregistered voice requires review",
                    unknown["speaker"]["role"] == "unknown" and unknown["requires_review"],
                )
                mixed_result = transcribe(mixed)
                check(
                    "overlap never produces combined command",
                    mixed_result["overlap"]
                    and mixed_result["requires_review"]
                    and not mixed_result["raw_transcript"],
                )
                multi = transcribe(audio)
                check(
                    "two voices produce separate review streams",
                    len(multi["utterances"]) >= 2
                    and not multi["raw_transcript"]
                    and multi["requires_review"],
                )
                background = transcribe(enrollment, mode="conversation")
                check("speech without address requires review", background["requires_review"])
                check(
                    "recognition did not create chat history", client.get("/sessions").json() == []
                )
                check("raw recordings were not retained", not list(Path(directory).rglob("*.wav")))
                if args.real_chat:
                    check(
                        "real Qwen provider",
                        client.get("/identity").json()["model"]["provider"] != "fixture",
                    )
                    response = client.post(
                        "/desktop/chat",
                        json={
                            "text": "Reply in one short English sentence to this "
                            "reviewed transcript: " + unknown["raw_transcript"]
                        },
                    )
                    events = [json.loads(line) for line in response.text.splitlines()]
                    terminal = events[-1]
                    metrics["chat_terminal_event"] = terminal["event_type"]
                    metrics["chat_error_code"] = (
                        terminal.get("payload", {}).get("error", {}).get("code")
                    )
                    check(
                        "reviewed speaker transcript completes through Qwen",
                        terminal["event_type"] == "agent.completed"
                        and bool(terminal["payload"]["text"]),
                    )
                    response = client.post(
                        "/voice/speak",
                        json={"text": terminal["payload"]["text"][:200], "engine": "windows"},
                    )
                    check(
                        "real Qwen reply produces Windows PCM",
                        response.status_code == 200 and response.json()["duration_seconds"] > 0,
                    )
                check(
                    "template can be revoked",
                    client.post(
                        "/developer/voice/remove", json={"speaker_id": enrolled["speaker_id"]}
                    ).status_code
                    == 200
                    and not client.get("/voice/speakers").json(),
                )
                process = psutil.Process(child.pid)
                metrics["service_tree_rss_mib"] = round(
                    sum(p.memory_info().rss for p in [process, *process.children(recursive=True)])
                    / 1024**2,
                    1,
                )
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        check("service stops on capability EOF", child.returncode == 0)
    report = dict(
        release=APP_VERSION,
        kind="real-speakers-and-Qwen"
        if args.real_chat
        else "real-speakers-frozen"
        if args.service
        else "real-speakers-source",
        passed=len(checks),
        checks=checks,
        metrics=metrics,
        fixture=dict(source=source, sha256=hashlib.sha256(fixture.read_bytes()).hexdigest()),
        limits="Public prerecorded English voices and synthetic mixture only. "
        "Scores are not calibrated probabilities. Exact replay detection is not liveness "
        "or clone detection. Human two-person microphone Gate 11 remains pending.",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
