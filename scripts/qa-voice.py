"""Actual local STT/TTS over the private service; disposable profiles, no microphone."""

import argparse
import base64
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import psutil
from adam import APP_VERSION
from faster_whisper.audio import decode_audio


def words(text):
    return re.findall(r"\w+", text.lower())


def wer(reference, hypothesis):
    a, b = words(reference), words(hypothesis)
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(row[j] + 1, next_row[j - 1] + 1, row[j - 1] + (x != y)))
        row = next_row
    return row[-1] / max(1, len(a))


def pcm(audio):
    return base64.b64encode((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()).decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--real-chat", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    fixture = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "ADAM/qa/jfk.flac"
    source = "https://raw.githubusercontent.com/openai/whisper/main/tests/jfk.flac"
    if not fixture.exists():
        response = httpx.get(source, timeout=60, follow_redirects=True)
        response.raise_for_status()
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_bytes(response.content)
    samples = decode_audio(str(fixture), sampling_rate=16000)
    reference = (
        "And so my fellow Americans ask not what your country can do for you "
        "ask what you can do for your country"
    )
    checks, metrics = [], {}

    def check(name, value):
        if not value:
            raise AssertionError(name)
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="adam-wave10-voice-") as directory:
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
                base_url=f"http://127.0.0.1:{receipt['port']}", timeout=180
            ) as client:
                check("private capability required", client.get("/voice/status").status_code == 403)
                client.headers["x-adam-desktop"] = receipt["nonce"]
                check(
                    "authenticated voice required", client.get("/voice/status").status_code == 401
                )
                password = "synthetic-voice-qa-owner-passphrase-817234"
                check(
                    "first setup",
                    client.post("/desktop/setup", json={"password": password}).status_code == 200,
                )
                check(
                    "owner login",
                    client.post("/auth/login", json={"password": password}).status_code == 200,
                )
                status = client.get("/voice/status").json()
                check(
                    "real local speech assets ready",
                    status["enabled"] and status["stt_ready"] and status["tts_ready"],
                )
                check("raw retention off", status["raw_audio_retention"] is False)
                check(
                    "browser origin denied",
                    client.get(
                        "/voice/status", headers={"origin": "http://localhost:8765"}
                    ).status_code
                    == 403,
                )

                def transcribe(name, waveform, **kwargs):
                    start = time.monotonic()
                    response = client.post(
                        "/voice/transcribe",
                        json={"pcm16": pcm(waveform), "language": "en", **kwargs},
                    )
                    if response.status_code != 200:
                        raise AssertionError(name + ": " + str(response.json()))
                    result = response.json()
                    metrics[name] = {
                        "elapsed_seconds": round(time.monotonic() - start, 3),
                        "audio_seconds": round(len(waveform) / 16000, 3),
                        "confidence": result["confidence"],
                        "requires_review": result["requires_review"],
                        "wer": round(wer(reference, result["raw_transcript"]), 3),
                    }
                    return result

                clean = transcribe("clean_public_fixture", samples)
                check("clean WER at most 0.30", metrics["clean_public_fixture"]["wer"] <= 0.30)
                check(
                    "raw versus repaired exposed",
                    clean["raw_transcript"] == clean["repaired_transcript"]
                    and not clean["repair_applied"],
                )
                quiet = transcribe("quiet_public_fixture", samples * 0.15)
                check("quiet speech visible", bool(quiet["raw_transcript"]))
                rng = np.random.default_rng(817234)
                rms = float(np.sqrt(np.mean(samples**2)))
                noisy = samples + rng.normal(0, rms / 3.16, len(samples)).astype(np.float32)
                transcribe("noise_10db_fixture", noisy)
                check("10dB noise WER at most 0.45", metrics["noise_10db_fixture"]["wer"] <= 0.45)
                silent = transcribe("silence", np.zeros(32000, dtype=np.float32))
                check(
                    "silence does not invent speech",
                    not silent["raw_transcript"] and silent["requires_review"],
                )
                partial = transcribe("partial_public_fixture", samples[: 5 * 16000], partial=True)
                check("partial STT labeled", partial["partial"] and bool(partial["raw_transcript"]))
                check(
                    "speech decoding creates no chat history", client.get("/sessions").json() == []
                )
                for name, text, expected in [
                    ("complete", "What time is it?", "TAKE_TURN"),
                    ("incomplete", "I need my", "WAIT"),
                    ("filler", "well um", "WAIT"),
                    ("urdu_incomplete", "ایک اور", "WAIT"),
                ]:
                    result = client.post(
                        "/voice/turn", json={"text": text, "confidence": 0.9, "silence_ms": 2000}
                    ).json()
                    check("pause scenario " + name, result["recommended_action"] == expected)
                for index in range(0 if args.real_chat else 2):
                    start = time.monotonic()
                    response = client.post(
                        "/voice/speak",
                        json={
                            "text": "Hello. ADAM runs locally on this computer.",
                            "language": "en-us",
                            "engine": "kokoro",
                        },
                    )
                    check("real Kokoro output " + str(index), response.status_code == 200)
                    output = response.json()
                    elapsed = time.monotonic() - start
                    check(
                        "PCM sample rate and duration " + str(index),
                        output["sample_rate"] == 24000
                        and output["duration_seconds"] > 1
                        and len(base64.b64decode(output["pcm16"])) > 48000,
                    )
                    metrics["tts_" + str(index)] = {
                        "elapsed_seconds": round(elapsed, 3),
                        "audio_seconds": round(output["duration_seconds"], 3),
                        "real_time_factor": round(elapsed / output["duration_seconds"], 3),
                    }
                if status["windows_ready"]:
                    start = time.monotonic()
                    response = client.post(
                        "/voice/speak",
                        json={
                            "text": "Hello. ADAM runs locally on this computer.",
                            "language": "en-us",
                            "engine": "windows",
                        },
                    )
                    check("real Windows offline speech", response.status_code == 200)
                    output = response.json()
                    elapsed = time.monotonic() - start
                    check(
                        "Windows PCM and provider",
                        output["provider"] == "windows"
                        and output["sample_rate"] == 24000
                        and output["duration_seconds"] > 1,
                    )
                    metrics["windows_tts"] = {
                        "elapsed_seconds": round(elapsed, 3),
                        "audio_seconds": round(output["duration_seconds"], 3),
                        "real_time_factor": round(elapsed / output["duration_seconds"], 3),
                    }
                    check(
                        "Windows speech faster than playback", elapsed < output["duration_seconds"]
                    )
                    check(
                        "unsupported Windows language rejected",
                        client.post(
                            "/voice/speak",
                            json={"text": "Bonjour", "language": "fr-fr", "engine": "windows"},
                        ).status_code
                        == 409,
                    )
                if args.real_chat:
                    check(
                        "real Qwen provider",
                        client.get("/identity").json()["model"]["provider"] != "fixture",
                    )
                    response = client.post(
                        "/desktop/chat",
                        json={
                            "text": "Reply in one short English sentence to this transcript: "
                            + clean["raw_transcript"]
                        },
                    )
                    events = [json.loads(item) for item in response.text.splitlines()]
                    terminal = events[-1]
                    if terminal["event_type"] != "agent.completed":
                        raise AssertionError(
                            "integrated chat: "
                            + terminal.get("payload", {})
                            .get("error", {})
                            .get("code", "missing completion")
                        )
                    check("real transcript-to-Qwen completion", bool(terminal["payload"]["text"]))
                    response = client.post(
                        "/voice/speak",
                        json={"text": terminal["payload"]["text"][:200], "engine": "windows"},
                    )
                    if response.status_code != 200:
                        failure = response.json().get("error", "UNKNOWN")
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        args.output.write_text(
                            json.dumps(
                                {
                                    "release": APP_VERSION,
                                    "kind": "real-speech-and-Qwen",
                                    "passed": False,
                                    "failure": "response-to-PCM: " + str(failure),
                                    "completed_checks": checks,
                                    "metrics": metrics,
                                    "available_ram_mib": round(
                                        psutil.virtual_memory().available / 1024**2
                                    ),
                                },
                                indent=2,
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                        print("Integrated speech response failed:", failure)
                    check(
                        "real Qwen response-to-PCM",
                        response.status_code == 200 and response.json()["duration_seconds"] > 0,
                    )
                check("no raw audio persisted", not list(Path(directory).rglob("*.wav")))
                owned = psutil.Process(child.pid)
                metrics["service_rss_mib"] = round(
                    sum(
                        p.memory_info().rss
                        for p in [owned, *owned.children(recursive=True)]
                        if p.is_running()
                    )
                    / 1024**2,
                    1,
                )
                if args.real_chat:
                    check(
                        "combined speech/model tree below 8GiB RSS",
                        metrics["service_rss_mib"] < 8192,
                    )
                else:
                    check("speech process below 2GiB RSS", metrics["service_rss_mib"] < 2048)
                client.post("/auth/switch", json={"mode": "demo"})
                check("demo speech status", client.get("/voice/status").status_code == 200)
                check(
                    "demo cannot elevate via voice",
                    client.post(
                        "/voice/turn",
                        json={
                            "text": "owner",
                            "confidence": 1,
                            "silence_ms": 1000,
                            "elevated": True,
                        },
                    ).status_code
                    == 422,
                )
                client.post("/auth/logout")
                check("logout revokes voice", client.get("/voice/status").status_code == 401)
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                raise AssertionError("voice service did not shut down") from None
        check("owned voice service stops on EOF", child.returncode == 0)
    report = {
        "release": APP_VERSION,
        "kind": "real-speech-and-Qwen"
        if args.real_chat
        else "real-speech-frozen-service"
        if args.service
        else "real-speech-source-service",
        "passed": len(checks),
        "checks": checks,
        "metrics": metrics,
        "fixture": {"source": source, "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()},
        "limits": (
            "Public prerecorded speech plus synthetic noise; no real microphone, room acoustics, "
            "code-switch or speaker-echo validation. "
            + (
                "Real Qwen and Windows speech were loaded together; "
                "Kokoro was skipped to match the compact default."
                if args.real_chat
                else "LLM is an explicitly synthetic QA provider in this suite; "
                "real Qwen tested separately."
            )
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": len(checks), "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
