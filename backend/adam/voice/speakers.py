"""Profile-scoped, revocable advisory voice templates. No biometric authentication."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from adam.core.migrations import migrate
from adam.resilience.archive import scoped
from adam.security.request import check_authority
from adam.security.vault import DPAPI, Sealer
from adam.voice.contracts import VoiceError

MIGRATIONS = (
    (
        1,
        (
            "CREATE TABLE speakers (speaker_id TEXT PRIMARY KEY, label TEXT NOT NULL, "
            "role TEXT NOT NULL CHECK(role IN ('owner','guest')), template BLOB NOT NULL, "
            "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
            "CREATE UNIQUE INDEX single_owner ON speakers(role) WHERE role='owner'",
        ),
    ),
)
MODEL_ID = "titanet-small:ad4a1802485d8b34"


def normalized(vector: Any) -> NDArray[np.float32]:
    value = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(value))
    if (
        value.ndim != 1
        or not 32 <= len(value) <= 1024
        or not np.isfinite(value).all()
        or not np.isfinite(norm)
        or norm < 1e-6
    ):
        raise VoiceError("VOICE.INVALID_EMBEDDING")
    return value / np.float32(norm)


class SpeakerStore:
    def __init__(self, root: Path, sealer: Sealer | None = None) -> None:
        self.root = root
        self.path = scoped(root, "voice/speakers.sqlite3")
        self.sealer = sealer or DPAPI()

    def records(self, *, vectors: bool = False) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT speaker_id,label,role,template FROM speakers ORDER BY created_at,speaker_id"
            ).fetchall()
        result = []
        for identifier, label, role, cipher in rows:
            item = {"speaker_id": identifier, "label": label, "role": role}
            if vectors:
                try:
                    payload = json.loads(self.sealer.open(cipher))
                    if payload["model"] != MODEL_ID:
                        raise ValueError("Template model differs; re-enroll")
                    item["vector"] = normalized(payload["vector"])
                except Exception:
                    raise VoiceError("VOICE.TEMPLATE_UNAVAILABLE") from None
            result.append(item)
        return result

    def put(self, label: str, role: str, vector: NDArray[np.float32]) -> dict[str, str]:
        check_authority()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migrate(self.path, MIGRATIONS)
        identifier = str(uuid4())
        cipher = self.sealer.seal(
            json.dumps({"model": MODEL_ID, "vector": normalized(vector).tolist()}).encode()
        )
        with closing(sqlite3.connect(self.path)) as db, db:
            if db.execute("SELECT count(*) FROM speakers").fetchone()[0] >= 8:
                raise VoiceError("VOICE.SPEAKER_LIMIT")
            try:
                db.execute(
                    "INSERT INTO speakers(speaker_id,label,role,template) VALUES(?,?,?,?)",
                    (identifier, label, role, cipher),
                )
            except sqlite3.IntegrityError:
                raise VoiceError("VOICE.OWNER_ALREADY_ENROLLED") from None
            check_authority()
        return {"speaker_id": identifier, "label": label, "role": role}

    def remove(self, identifier: str) -> None:
        check_authority()
        if self.path.exists():
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("PRAGMA secure_delete=ON")
                db.execute("DELETE FROM speakers WHERE speaker_id=?", (identifier,))
                check_authority()


def identify(
    vector: NDArray[np.float32], records: list[dict[str, Any]], threshold: float, margin: float
) -> dict[str, Any]:
    scored = sorted(
        [(float(normalized(vector) @ normalized(r["vector"])), i) for i, r in enumerate(records)],
        reverse=True,
    )
    score = scored[0][0] if scored else 0.0
    gap = score - scored[1][0] if len(scored) > 1 else score
    result: dict[str, Any] = {
        "speaker_id": None,
        "role": "unknown",
        "confidence": round(max(0.0, score), 3),
        "confidence_kind": "uncalibrated_cosine",
        "authority_granted": False,
    }
    if scored and score >= threshold and gap >= margin:
        record = records[scored[0][1]]
        result.update(speaker_id=record["speaker_id"], role=record["role"], label=record["label"])
    return result
