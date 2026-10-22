import base64
import binascii
import importlib
import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
from numpy.typing import NDArray

from adam.voice import windows
from adam.voice.contracts import AudioInput, SpeechInput, VoiceConfig, VoiceError


def voice_assets(config: VoiceConfig) -> Path:
    if config.assets_dir:
        return config.assets_dir.expanduser().resolve()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    primary = root / "ADAM/models/voice"
    cached = root / "Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local/ADAM/models/voice"
    if (
        os.name == "nt"
        and not (primary / "manifest.json").is_file()
        and (cached / "manifest.json").is_file()
    ):
        return cached
    return primary.resolve()


def decode_audio(body: AudioInput) -> NDArray[np.float32]:
    try:
        raw = base64.b64decode(body.pcm16, validate=True)
    except (ValueError, binascii.Error):
        raise VoiceError("VOICE.INVALID_AUDIO") from None
    if len(raw) % 2 or not 3200 <= len(raw) <= 16000 * 2 * 60:
        raise VoiceError("VOICE.INVALID_AUDIO")
    return np.asarray(np.frombuffer(raw, dtype="<i2"), dtype=np.float32) / np.float32(32768)


def noise_process(audio: NDArray[np.float32]) -> NDArray[np.float32]:
    # DC removal only: browser capture requests echo cancellation/noise suppression.
    # Never amplify fan noise into speech. Silero VAD remains the speech detector.
    return np.asarray(np.clip(audio - np.mean(audio), -1, 1), dtype=np.float32)


class LocalSpeech:
    def __init__(self, config: VoiceConfig) -> None:
        self.config = config
        self.root = voice_assets(config)
        self.stt: Any = None
        self.tts: Any = None
        self.windows_ready: bool | None = None

    def status(self) -> dict[str, Any]:
        if self.windows_ready is None:
            self.windows_ready = windows.available()
        stt = all(
            (self.root / "faster-whisper-base" / n).is_file()
            for n in ["model.bin", "config.json", "tokenizer.json"]
        )
        tts = all((self.root / n).is_file() for n in ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"])
        return {
            "stt_ready": stt,
            "tts_ready": tts if self.config.tts_engine == "kokoro" else self.windows_ready,
            "kokoro_ready": tts,
            "windows_ready": self.windows_ready,
            "default_tts_engine": self.config.tts_engine,
            "stt_provider": "faster-whisper-base/cpu/int8",
            "tts_provider": "kokoro-onnx/cpu/int8"
            if self.config.tts_engine == "kokoro"
            else "windows-sapi/offline",
            "raw_audio_retention": self.config.retain_audio,
            "recognition_languages": ["auto", "en", "ur", "hi", "es", "fr", "de", "ja", "zh"],
            "speech_languages": ["en-us", "en-gb", "fr-fr", "es", "it", "pt-br", "hi"],
            "limitations": [
                "confidence_is_heuristic",
                "no_speaker_identity",
                "headphones_recommended",
                "urdu_tts_unavailable",
            ],
        }

    def transcribe(self, audio: NDArray[np.float32], body: AudioInput) -> dict[str, Any]:
        if not self.status()["stt_ready"]:
            raise VoiceError("VOICE.ASSETS_MISSING")
        if float(np.sqrt(np.mean(audio**2))) < 0.001:
            return self.transcript([], "unknown", 0.0)
        if self.stt is None:
            module = importlib.import_module("faster_whisper")
            self.stt = module.WhisperModel(
                str(self.root / "faster-whisper-base"),
                device="cpu",
                compute_type="int8",
                cpu_threads=self.config.cpu_threads,
                num_workers=1,
                local_files_only=True,
            )
        segments, info = self.stt.transcribe(
            audio,
            language=None if body.language == "auto" else body.language,
            beam_size=1,
            best_of=1,
            temperature=0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
            word_timestamps=False,
            hallucination_silence_threshold=1.0,
        )
        items = list(segments)
        return self.transcript(items, info.language, float(info.language_probability))

    def transcript(self, segments: list[Any], language: str, probability: float) -> dict[str, Any]:
        raw = " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()[:4000]
        confidence = min(
            (math.exp(min(0, s.avg_logprob)) * (1 - s.no_speech_prob) for s in segments),
            default=0.0,
        )
        confidence = min(1.0, max(0.0, confidence))
        return {
            "raw_transcript": raw,
            "repaired_transcript": raw,
            "repair_applied": False,
            "confidence": round(confidence, 3),
            "confidence_kind": "heuristic_uncalibrated",
            "language": language,
            "language_probability": round(probability, 3),
            "requires_review": not raw or confidence < self.config.confidence_threshold,
            "segments": [
                {
                    "start": float(s.start),
                    "end": float(s.end),
                    "no_speech_probability": float(s.no_speech_prob),
                }
                for s in segments[:128]
            ],
        }

    def synthesize(self, body: SpeechInput) -> dict[str, Any]:
        started = time.monotonic()
        engine = self.config.tts_engine if body.engine == "configured" else body.engine
        if engine == "windows":
            return self.output(windows.synthesize(body.text, body.language), started, engine)
        if not self.status()["kokoro_ready"]:
            raise VoiceError("VOICE.ASSETS_MISSING")
        if self.tts is None:
            options = ort.SessionOptions()
            options.intra_op_num_threads = self.config.cpu_threads
            options.inter_op_num_threads = 1
            module = importlib.import_module("kokoro_onnx")
            session = ort.InferenceSession(
                str(self.root / "kokoro-v1.0.int8.onnx"),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self.tts = module.Kokoro.from_session(session, str(self.root / "voices-v1.0.bin"))
        voices = {
            "en-us": "af_heart",
            "en-gb": "bf_emma",
            "fr-fr": "ff_siwis",
            "es": "ef_dora",
            "it": "if_sara",
            "pt-br": "pf_dora",
            "hi": "hf_alpha",
        }
        samples, rate = self.tts.create(body.text, voice=voices[body.language], lang=body.language)
        samples = np.asarray(samples, dtype=np.float32)
        if rate != 24000 or not np.isfinite(samples).all() or len(samples) > 24000 * 45:
            raise VoiceError("VOICE.OUTPUT_LIMIT")
        pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
        return self.output(pcm, started, engine)

    @staticmethod
    def output(pcm: bytes, started: float, engine: str) -> dict[str, Any]:
        duration = len(pcm) / 48000
        elapsed = time.monotonic() - started
        return {
            "pcm16": base64.b64encode(pcm).decode("ascii"),
            "sample_rate": 24000,
            "provider": engine,
            "duration_seconds": duration,
            "processing_seconds": round(elapsed, 3),
            "slower_than_realtime": elapsed > duration,
        }
