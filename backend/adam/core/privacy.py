"""Fail closed for declared secrets and recognizable credential material.

This is a conservative ingress boundary, not a secrets vault or general DLP classifier.
Users must never submit credentials. Unknown arbitrary secrets cannot be inferred.
"""

import base64
import json
import re
import threading
from urllib.parse import quote

_KNOWN: set[str] = set()
_ENCODED: set[str] = set()
_LOCK = threading.RLock()


def register_secret(value: str) -> None:
    """In-process denial cache; never persist values or emit them in diagnostics."""
    if value:
        with _LOCK:
            _KNOWN.add(value)
            if len(value) >= 8:
                data = value.encode("utf-8")
                _ENCODED.update(
                    {
                        base64.b64encode(data).decode(),
                        base64.urlsafe_b64encode(data).decode(),
                        base64.b64encode(data).decode().rstrip("="),
                        data.hex(),
                        data.hex().upper(),
                        quote(value, safe=""),
                        "".join(f"%{byte:02X}" for byte in data),
                        "".join(f"%{byte:02x}" for byte in data),
                        json.dumps(value, ensure_ascii=True)[1:-1],
                    }
                )


_CREDENTIALS = re.compile(
    r"\badam_session_[A-Za-z0-9_-]+\b|"
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{15,}|AKIA[A-Z0-9]{16})\b|"
    r"\b(?:password|passwd|api[_ -]?key|access[_ -]?token|client[_ -]?secret|"
    r"bearer|secret)\s*(?:is\b|[:=])\s*\S+|"
    r"\bBearer\s+[A-Za-z0-9._-]{12,}|"
    r"https?://[^\s/@:]+:[^\s/@]+@",
    re.IGNORECASE,
)


def contains_secret(text: str) -> bool:
    with _LOCK:
        return (
            bool(_CREDENTIALS.search(text))
            or any(value in text for value in _KNOWN)
            or any(value in "".join(text.split()) for value in _ENCODED)
        )


def protected_suffix_length(text: str) -> int:
    """Hold a possible known-secret prefix until subsequent tokens disambiguate it."""
    held = 0
    compact = "".join(text.split())
    positions = [index for index, char in enumerate(text) if not char.isspace()]
    with _LOCK:
        for value in _KNOWN | _ENCODED:
            for size in range(min(len(text), len(value) - 1), held, -1):
                if text.endswith(value[:size]):
                    held = size
                    break
        for value in _ENCODED:
            for size in range(min(len(compact), len(value) - 1), 0, -1):
                if compact.endswith(value[:size]):
                    held = max(held, len(text) - positions[-size])
                    break
    return held


def safe_transcript(text: str) -> str:
    # Whole-message omission avoids retaining unrecognized pieces of the same credential.
    return "[credential-bearing message omitted]" if contains_secret(text) else text
