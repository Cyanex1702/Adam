import asyncio
import base64
import time
import wave
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from adam.compute.contracts import ComputeError
from adam.compute.resources import ManagedProvider, PriorityScheduler
from adam.core.config import Settings
from adam.security.auth import AuthError
from adam.security.gateway import CURRENT
from adam.voice.contracts import (
    AudioInput,
    Enrollment,
    SpeakerRemoval,
    SpeechInput,
    TurnInput,
    VoiceError,
)
from adam.voice.providers import LocalSpeech, decode_audio, noise_process
from adam.voice.social import SocialVoice
from adam.voice.speakers import SpeakerStore
from adam.voice.turns import PauseProfile, interruption


def expire(root: Path, settings: Settings, *, reserve: int = 0) -> None:
    from adam.resilience.archive import scoped

    folder = scoped(root, "voice/audio")
    if not folder.exists():
        return
    cutoff = time.time() - settings.voice.retention_hours * 3600
    files = sorted(folder.glob("*.wav"), key=lambda path: path.stat().st_mtime)
    for index, path in enumerate(files):
        if (
            path.stat().st_mtime < cutoff
            or index < len(files) - settings.voice.retention_max_files + reserve
        ):
            scoped(root, str(path.relative_to(root))).unlink()


def retain(root: Path, body: AudioInput, settings: Settings) -> None:
    if not settings.voice.retain_audio or body.partial:
        return
    from adam.resilience.archive import scoped

    folder = scoped(root, "voice/audio")
    folder.mkdir(parents=True, exist_ok=True)
    expire(root, settings, reserve=1)
    target = scoped(root, f"voice/audio/{uuid4()}.wav")
    with wave.open(str(target), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(base64.b64decode(body.pcm16, validate=True))


def install_voice(app: FastAPI, settings: Settings, models: ManagedProvider) -> None:
    speech = LocalSpeech(settings.voice)
    social = SocialVoice(speech, settings.voice)
    app.state.voice = speech
    profiles: OrderedDict[str, PauseProfile] = OrderedDict()
    schedulers = {
        True: PriorityScheduler(settings.compute),
        False: PriorityScheduler(settings.compute),
    }
    pending = {True: 0, False: 0}
    original_lifespan = app.router.lifespan_context

    async def cleanup_audio() -> None:
        while True:
            # Owned retained audio only. Expiry runs at startup and every minute;
            # after app shutdown, overdue files expire on its next launch.
            roots = [settings.data_dir, *settings.data_dir.glob("profiles/*/*")]
            for root in roots:
                try:
                    await asyncio.to_thread(expire, root, settings)
                except (OSError, ValueError):
                    continue
            await asyncio.sleep(60)

    @asynccontextmanager
    async def lifespan(active: FastAPI) -> AsyncIterator[Any]:
        async with original_lifespan(active) as state:
            cleanup = asyncio.create_task(cleanup_audio())
            try:
                yield state
            finally:
                cleanup.cancel()
                with suppress(asyncio.CancelledError):
                    await cleanup

    app.router.lifespan_context = lifespan

    def profile() -> PauseProfile:
        key = str(CURRENT.get().settings.data_dir)
        if key not in profiles:
            if len(profiles) >= 16:
                profiles.popitem(last=False)
            profiles[key] = PauseProfile()
        profiles.move_to_end(key)
        return profiles[key]

    def enabled() -> None:
        if not settings.features.voice:
            raise VoiceError("VOICE.DISABLED")

    @app.exception_handler(VoiceError)
    async def voice_error(request: Request, exc: VoiceError) -> JSONResponse:
        return JSONResponse({"error": exc.code}, status_code=409)

    @app.get("/voice/status")
    async def status() -> dict[str, Any]:
        return {
            "enabled": settings.features.voice,
            "speaker_enabled": settings.features.speaker_id,
            **speech.status(),
            **social.status(),
        }

    async def run(function: Any, *, listening: bool = False) -> Any:
        enabled()
        if pending[listening] >= 2:
            raise VoiceError("VOICE.BUSY")
        pending[listening] += 1
        try:
            if models.observe()["mode"] == "DEGRADED":
                raise VoiceError("RESOURCE.PRESSURE")
            # Separate bounded STT/TTS lanes keep interruption decoding available
            # during synthesis and GPU generation. Each model caps its CPU threads.
            return await schedulers[listening].run("CRITICAL" if listening else "NORMAL", function)
        except VoiceError:
            raise
        except (MemoryError, ComputeError):
            raise VoiceError("VOICE.RESOURCE_UNAVAILABLE") from None
        except Exception:
            # Never serialize library exceptions containing audio, paths or text.
            raise VoiceError("VOICE.PROVIDER_FAILED") from None
        finally:
            pending[listening] -= 1

    app.state.voice_run = run

    @app.post("/voice/transcribe")
    async def transcribe(body: AudioInput) -> dict[str, Any]:
        enabled()
        audio = noise_process(decode_audio(body))
        root = CURRENT.get().settings.data_dir

        def process() -> dict[str, Any]:
            result = (
                social.analyze(audio, body, root)
                if settings.features.speaker_id
                else speech.transcribe(audio, body)
            )
            retain(root, body, settings)
            return result

        result: dict[str, Any] = await run(process, listening=True)
        result["partial"] = body.partial
        result["interruption"] = interruption(result["raw_transcript"], result["confidence"])
        result["turn"] = profile().decide(
            TurnInput(
                text=result["raw_transcript"],
                confidence=result["confidence"],
                silence_ms=body.silence_ms,
            )
        )
        return result

    @app.get("/voice/speakers")
    async def speakers() -> list[dict[str, Any]]:
        enabled()
        return await asyncio.to_thread(SpeakerStore(CURRENT.get().settings.data_dir).records)

    def enrollment_enabled() -> None:
        enabled()
        if not settings.features.speaker_id:
            raise VoiceError("VOICE.SPEAKER_DISABLED")
        if CURRENT.get().principal.mode != "owner":
            raise AuthError("AUTH.ELEVATION_REQUIRED")
        from adam.security.request import check_authority

        check_authority()

    @app.post("/developer/voice/enroll")
    async def enroll(body: Enrollment) -> dict[str, str]:
        enrollment_enabled()
        if body.partial:
            raise VoiceError("VOICE.ENROLLMENT_FINAL_REQUIRED")
        audio = noise_process(decode_audio(body))
        root = CURRENT.get().settings.data_dir
        result: dict[str, str] = await run(
            lambda: social.enroll(audio, root, body.label, body.role), listening=True
        )
        return result

    @app.post("/developer/voice/remove")
    async def remove(body: SpeakerRemoval) -> dict[str, bool]:
        enrollment_enabled()
        await asyncio.to_thread(
            SpeakerStore(CURRENT.get().settings.data_dir).remove, body.speaker_id
        )
        return {"removed": True}

    @app.post("/voice/turn")
    async def turn(body: TurnInput) -> dict[str, Any]:
        enabled()
        return profile().decide(body)

    @app.post("/voice/speak")
    async def speak(body: SpeechInput) -> dict[str, Any]:
        def authority() -> None:
            from adam.security.request import check_authority

            check_authority()
            if body.session_id and hasattr(app.state, "mesh"):
                if app.state.mesh.store.primary(str(body.session_id))["primary"] != "desktop":
                    raise VoiceError("VOICE.NOT_PRIMARY")

        authority()
        result: dict[str, Any] = await run(lambda: speech.synthesize(body))
        authority()
        return result
