from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from adam.core.contracts import Contract


class VoiceConfig(Contract):
    speaker_threshold: float = Field(default=0.7, ge=0.5, le=0.95)
    speaker_margin: float = Field(default=0.12, ge=0.05, le=0.5)
    tts_engine: Literal["kokoro", "windows"] = "kokoro"
    assets_dir: Path | None = None
    cpu_threads: int = Field(default=2, ge=1, le=4)
    confidence_threshold: float = Field(default=0.65, ge=0.4, le=0.95)
    retain_audio: bool = False
    retention_hours: int = Field(default=24, ge=1, le=168)
    retention_max_files: int = Field(default=20, ge=1, le=100)


class AudioInput(Contract):
    mode: Literal["push_to_talk", "conversation"] = "push_to_talk"
    pcm16: str = Field(max_length=2_560_000)
    sample_rate: Literal[16000] = 16000
    language: Literal["auto", "en", "ur", "hi", "es", "fr", "de", "ja", "zh"] = "auto"
    partial: bool = False
    silence_ms: int = Field(default=0, ge=0, le=30000)


class SpeechInput(Contract):
    session_id: UUID | None = None
    engine: Literal["configured", "kokoro", "windows"] = "configured"
    text: str = Field(min_length=1, max_length=240)
    language: Literal["en-us", "en-gb", "fr-fr", "es", "it", "pt-br", "hi"] = "en-us"


class TurnInput(Contract):
    text: str = Field(max_length=4000)
    confidence: float = Field(ge=0, le=1)
    silence_ms: int = Field(ge=0, le=30000)
    speech_active: bool = False
    reset_profile: bool = False
    observed_pause_ms: int | None = Field(default=None, ge=0, le=10000)


class VoiceError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Enrollment(AudioInput):
    label: str = Field(min_length=1, max_length=48, pattern=r"^[\w .'-]+$")
    role: Literal["owner", "guest"]
    consent: Literal[True]


class SpeakerRemoval(Contract):
    speaker_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
