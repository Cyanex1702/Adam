"""Small offline SAPI fallback; synthesize to RAM, never directly to speakers."""

import importlib
import os
from typing import Any

from adam.voice.contracts import VoiceError


def english_voice(voice: Any, language: str = "en-us") -> Any:
    tokens = voice.GetVoices()
    fallback = None
    desired = 0x409 if language == "en-us" else 0x809
    for index in range(tokens.Count):
        token = tokens.Item(index)
        languages = [int(code, 16) for code in token.GetAttribute("Language").split(";")]
        if desired in languages:
            return token
        if any(code & 0x3FF == 9 for code in languages):
            fallback = token
    if fallback is None:
        raise VoiceError("VOICE.WINDOWS_VOICE_UNAVAILABLE")
    return fallback


def available() -> bool:
    if os.name != "nt":
        return False
    try:
        com = importlib.import_module("pythoncom")
    except ImportError:
        return False
    com.CoInitialize()
    try:
        client = importlib.import_module("win32com.client")
        english_voice(client.Dispatch("SAPI.SpVoice"))
        return True
    except Exception:
        return False
    finally:
        com.CoUninitialize()


def synthesize(text: str, language: str) -> bytes:
    if os.name != "nt" or language not in {"en-us", "en-gb"}:
        raise VoiceError("VOICE.LANGUAGE_UNAVAILABLE")
    com = importlib.import_module("pythoncom")
    com.CoInitialize()
    try:
        client = importlib.import_module("win32com.client")
        voice = client.Dispatch("SAPI.SpVoice")
        voice.Voice = english_voice(voice, language)
        stream = client.Dispatch("SAPI.SpMemoryStream")
        stream.Format.Type = 26  # SAFT24kHz16BitMono
        voice.AudioOutputStream = stream
        voice.Speak(text, 16)  # SVSFIsNotXML: input cannot inject speech markup.
        data = bytes(stream.GetData())
        if stream.Format.Type != 26 or len(data) > 24000 * 2 * 45 or len(data) % 2:
            raise VoiceError("VOICE.OUTPUT_LIMIT")
        return data
    finally:
        com.CoUninitialize()
