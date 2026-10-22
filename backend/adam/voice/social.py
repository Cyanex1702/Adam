"""Bounded CPU speaker diarization; inseparable overlap always requires clarification."""

import hashlib
import importlib
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
from numpy.typing import NDArray

from adam.voice.contracts import AudioInput, VoiceConfig, VoiceError
from adam.voice.providers import LocalSpeech
from adam.voice.speakers import SpeakerStore, identify, normalized


class SocialVoice:
    def __init__(self, speech: LocalSpeech, config: VoiceConfig) -> None:
        self.speech, self.config = speech, config
        self.root = speech.root / "speaker"
        self.embedding: Any = None
        self.diarizer: Any = None
        self.segmentation: Any = None
        self.seen: OrderedDict[tuple[str, str], float] = OrderedDict()

    def status(self) -> dict[str, Any]:
        return {
            "speaker_ready": (self.root / "nemo_en_titanet_small.onnx").is_file(),
            "diarization_ready": (
                self.root / "sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx"
            ).is_file(),
            "spatial_audio": "DEFERRED_MONO_CAPTURE",
            "speaker_authority": "ADVISORY_ONLY",
        }

    def load(self) -> None:
        if (
            self.embedding is not None
            and self.diarizer is not None
            and self.segmentation is not None
        ):
            return
        if not all(self.status()[key] for key in ["speaker_ready", "diarization_ready"]):
            raise VoiceError("VOICE.SPEAKER_ASSETS_MISSING")
        k = importlib.import_module("sherpa_onnx")
        embedding = k.SpeakerEmbeddingExtractorConfig(
            model=str(self.root / "nemo_en_titanet_small.onnx"),
            num_threads=self.config.cpu_threads,
            provider="cpu",
        )
        self.embedding = k.SpeakerEmbeddingExtractor(embedding)
        segment = str(self.root / "sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx")
        config = k.OfflineSpeakerDiarizationConfig(
            segmentation=k.OfflineSpeakerSegmentationModelConfig(
                pyannote=k.OfflineSpeakerSegmentationPyannoteModelConfig(model=segment),
                num_threads=1,
                provider="cpu",
            ),
            embedding=embedding,
            clustering=k.FastClusteringConfig(num_clusters=-1, threshold=0.5),
            min_duration_on=0.3,
            min_duration_off=0.4,
        )
        self.diarizer = k.OfflineSpeakerDiarization(config)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.segmentation = ort.InferenceSession(
            segment, sess_options=options, providers=["CPUExecutionProvider"]
        )

    def embed(self, audio: NDArray[np.float32]) -> NDArray[np.float32]:
        self.load()
        if len(audio) < 16000:
            raise VoiceError("VOICE.SPEAKER_AUDIO_TOO_SHORT")
        stream = self.embedding.create_stream()
        stream.accept_waveform(sample_rate=16000, waveform=np.ascontiguousarray(audio))
        stream.input_finished()
        if not self.embedding.is_ready(stream):
            raise VoiceError("VOICE.SPEAKER_AUDIO_TOO_SHORT")
        return normalized(self.embedding.compute(stream))

    def overlap(self, audio: NDArray[np.float32]) -> list[tuple[float, float]]:
        self.load()
        regions = []
        # Pyannote powerset classes 4,5,6 contain two simultaneous speakers.
        for start in range(0, len(audio), 160000):
            chunk = audio[start : start + 160000]
            padded = np.pad(chunk, (0, 160000 - len(chunk)))[None, None, :]
            scores = np.asarray(self.segmentation.run(None, {"x": padded})[0])[0]
            mask = np.argmax(scores, axis=-1) >= 4
            count = int(np.ceil(len(chunk) / 160000 * len(mask)))
            active = np.flatnonzero(mask[:count])
            if len(active) / len(mask) * 10 >= 0.12:
                regions.append(
                    (
                        start / 16000 + float(active[0]) / len(mask) * 10,
                        start / 16000 + float(active[-1] + 1) / len(mask) * 10,
                    )
                )
        return regions

    def segments(self, audio: NDArray[np.float32]) -> list[dict[str, Any]]:
        self.load()
        result = self.diarizer.process(np.ascontiguousarray(audio)).sort_by_start_time()
        if len(result) > 16 or len({r.speaker for r in result}) > 4:
            raise VoiceError("VOICE.TOO_MANY_SPEAKERS")
        return [
            {
                "start": max(0.0, float(r.start)),
                "end": min(len(audio) / 16000, float(r.end)),
                "cluster": int(r.speaker),
            }
            for r in result
            if r.end - r.start >= 0.6
        ]

    def replay(self, root: Path, audio: NDArray[np.float32], *, partial: bool) -> str:
        if partial:
            return "NOT_ASSESSED_PARTIAL"
        key = (str(root), hashlib.sha256(audio.tobytes()).hexdigest())
        now = time.monotonic()
        repeat = key in self.seen and now - self.seen[key] < 600
        self.seen[key] = now
        self.seen.move_to_end(key)
        while len(self.seen) > 128:
            self.seen.popitem(last=False)
        return "REPEATED_AUDIO" if repeat else "NOT_RULED_OUT"

    def analyze(self, audio: NDArray[np.float32], body: AudioInput, root: Path) -> dict[str, Any]:
        if body.partial:
            result = self.speech.transcribe(audio, body)
            return {
                **result,
                "requires_review": True,
                "speaker": {"role": "unknown", "authority_granted": False},
                "speaker_processing": "FINAL_REQUIRED",
                "utterances": [],
                "replay_risk": "NOT_ASSESSED_PARTIAL",
            }
        overlap = self.overlap(audio)
        segments = self.segments(audio)
        records = SpeakerStore(root).records(vectors=True)
        replay = self.replay(root, audio, partial=False)
        utterances = []
        for segment in segments:
            start, end = segment["start"], segment["end"]
            mixed = any(start < b and end > a for a, b in overlap)
            if mixed:
                utterances.append(
                    {
                        **segment,
                        "raw_transcript": "",
                        "confidence": 0,
                        "speaker": {"role": "unknown", "authority_granted": False},
                        "overlap": True,
                        "requires_review": True,
                    }
                )
                continue
            piece = audio[int(start * 16000) : int(end * 16000)]
            identity = (
                identify(
                    self.embed(piece),
                    records,
                    self.config.speaker_threshold,
                    self.config.speaker_margin,
                )
                if len(piece) >= 16000
                else {"role": "unknown", "authority_granted": False}
            )
            transcript = self.speech.transcribe(piece, body)
            addressed = body.mode == "push_to_talk" or any(
                word in transcript["raw_transcript"].lower().split()
                for word in ["adam", "adam,", "آدم", "ایڈم"]
            )
            utterances.append(
                {
                    **segment,
                    **transcript,
                    "speaker": identity,
                    "overlap": False,
                    "addressed": addressed,
                    "requires_review": transcript["requires_review"]
                    or identity["role"] != "owner"
                    or not addressed,
                }
            )
        single = len({s["cluster"] for s in segments}) == 1 and bool(utterances) and not overlap
        result = (
            utterances[0].copy()
            if single and len(utterances) == 1
            else self.speech.transcript([], "unknown", 0)
        )
        if single and len(utterances) > 1:
            result.update(
                raw_transcript=" ".join(u["raw_transcript"] for u in utterances),
                repaired_transcript=" ".join(u["raw_transcript"] for u in utterances),
                confidence=min(u["confidence"] for u in utterances),
                speaker=utterances[0]["speaker"],
                requires_review=any(u["requires_review"] for u in utterances),
            )
        result.update(
            utterances=utterances,
            overlap=bool(overlap),
            overlap_regions=overlap,
            replay_risk=replay,
            spatial=None,
            speaker_processing="COMPLETE",
            clarification="Please speak one at a time, address ADAM, "
            "and review the intended speaker's words."
            if not single
            else "",
        )
        if not single or replay == "REPEATED_AUDIO":
            result["requires_review"] = True
        return result

    def enroll(
        self, audio: NDArray[np.float32], root: Path, label: str, role: str
    ) -> dict[str, str]:
        if not 6 * 16000 <= len(audio) <= 20 * 16000:
            raise VoiceError("VOICE.ENROLLMENT_DURATION")
        if self.overlap(audio):
            raise VoiceError("VOICE.ENROLLMENT_MULTIPLE_SPEAKERS")
        segments = self.segments(audio)
        if (
            len({s["cluster"] for s in segments}) != 1
            or sum(s["end"] - s["start"] for s in segments) < 4
        ):
            raise VoiceError("VOICE.ENROLLMENT_MULTIPLE_SPEAKERS")
        vectors = [self.embed(piece) for piece in np.array_split(audio, 3)]
        # Within-sample consistency is distinct from recognition against a template.
        # Both are conservative heuristics, not calibrated biometric probabilities.
        if min(float(a @ b) for a in vectors for b in vectors) < 0.6:
            raise VoiceError("VOICE.ENROLLMENT_INCONSISTENT")
        return SpeakerStore(root).put(label, role, normalized(np.mean(vectors, axis=0)))
