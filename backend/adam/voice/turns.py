import re
from dataclasses import dataclass
from typing import Any

from adam.voice.contracts import TurnInput


def interruption(text: str, confidence: float) -> str:
    if confidence < 0.65:
        return "UNCERTAIN"
    value = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if value in {"mhm", "mmhm", "mm hmm", "mm hm", "uh huh", "okay", "ok", "yes", "yeah", "hmm"}:
        return "ACKNOWLEDGEMENT"
    if value in {"stop", "stop please", "please stop", "cancel", "be quiet", "بس", "رکو"}:
        return "HARD_INTERRUPT"
    if value.startswith(("actually ", "no i meant", "wait ", "instead ", "نہیں ")):
        return "CORRECTION"
    return "NEW_REQUEST" if len(value.split()) >= 2 else "UNCERTAIN"


@dataclass
class PauseProfile:
    """Session-local pause style; supplied device session is not speaker identity."""

    pause_ms: float = 900

    def decide(self, body: TurnInput) -> dict[str, Any]:
        if body.reset_profile:
            self.pause_ms = 900
        if body.observed_pause_ms is not None:
            observation = min(1600, max(600, body.observed_pause_ms))
            self.pause_ms = min(1600, max(600, self.pause_ms * 0.9 + observation * 0.1))
        text = body.text.strip()
        words = text.lower().rstrip(".,!?۔؟").split()
        incomplete = (
            not words
            or words[-1]
            in {
                "and",
                "or",
                "but",
                "because",
                "if",
                "the",
                "a",
                "to",
                "my",
                "with",
                "from",
                "um",
                "uh",
                "so",
                "then",
                "کہ",
                "اور",
                "لیکن",
                "کیونکہ",
                "میرا",
                "میری",
                "aur",
                "lekin",
                "kyunki",
                "mera",
                "meri",
            }
            or text.endswith(("...", "…", ",", ":", "-"))
        )
        complete = bool(text) and text.endswith((".", "?", "!", "۔", "؟")) and not incomplete
        wait = self.pause_ms + (2200 if incomplete else 0 if complete else 800)
        low = body.confidence < 0.65
        action = "LISTEN" if body.speech_active else "WAIT"
        reasons = ["SPEECH_ACTIVE"] if body.speech_active else []
        if incomplete:
            reasons.append("LINGUISTICALLY_INCOMPLETE")
        if low:
            reasons.append("LOW_CONFIDENCE_REVIEW_REQUIRED")
        if not body.speech_active and text and not low and body.silence_ms >= wait:
            action = "TAKE_TURN"
            reasons.append("PAUSE_AND_LANGUAGE_AGREE")
        probability = (
            0.0 if body.speech_active or not text else min(0.99, body.silence_ms / wait * 0.85)
        )
        if low:
            probability = min(probability, 0.4)
        return {
            "recommended_action": action,
            "turn_end_probability": round(probability, 3),
            "reason_codes": reasons,
            "wait_ms": round(wait),
            "pause_profile_ms": round(self.pause_ms),
        }
