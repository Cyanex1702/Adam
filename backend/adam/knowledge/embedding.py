"""Pinned, offline CPU inference. No implicit Hugging Face downloads or PyTorch."""

import hashlib
import threading
from pathlib import Path
from typing import Protocol

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
from tokenizers import Tokenizer

MODEL_ID = "intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3"
FILES = {
    "model.onnx": (
        "onnx/model.onnx",
        "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665",
    ),
    "tokenizer.json": (
        "tokenizer.json",
        "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
    ),
}


class EmbeddingUnavailable(RuntimeError):
    pass


class Embedder(Protocol):
    model_id: str
    dimensions: int

    def documents(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class LocalE5:
    model_id = MODEL_ID
    dimensions = 384

    def __init__(self, directory: Path, threads: int = 2) -> None:
        self.directory = directory
        self.threads = threads
        self._session: ort.InferenceSession | None = None
        self._tokenizer: Tokenizer | None = None
        self._lock = threading.RLock()

    def _load(self) -> None:
        if self._session is not None:
            return
        for name, (_, digest) in FILES.items():
            path = self.directory / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise EmbeddingUnavailable(
                    "Embedding files absent/unverified; run setup-knowledge.ps1."
                )
        try:
            options = ort.SessionOptions()
            options.intra_op_num_threads = self.threads
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(
                str(self.directory / "model.onnx"), options, providers=["CPUExecutionProvider"]
            )
            tokenizer = Tokenizer.from_file(str(self.directory / "tokenizer.json"))
            tokenizer.enable_truncation(max_length=512)
            tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
            self._session, self._tokenizer = session, tokenizer
        except Exception:
            raise EmbeddingUnavailable("Local embedding model could not initialize.") from None

    def _encode(self, texts: list[str], prefix: str) -> list[list[float]]:
        with self._lock:
            self._load()
            assert self._session is not None and self._tokenizer is not None
            vectors: list[list[float]] = []
            for start in range(0, len(texts), 2):
                encodings = self._tokenizer.encode_batch(
                    [prefix + text for text in texts[start : start + 2]]
                )
                ids = np.asarray([item.ids for item in encodings], dtype=np.int64)
                mask = np.asarray([item.attention_mask for item in encodings], dtype=np.int64)
                inputs = {
                    "input_ids": ids,
                    "attention_mask": mask,
                    "token_type_ids": np.zeros_like(ids),
                }
                output = np.asarray(
                    self._session.run(
                        None, {item.name: inputs[item.name] for item in self._session.get_inputs()}
                    )[0]
                )
                pooled = (output * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1)[:, None]
                normalized = pooled / np.maximum(np.linalg.norm(pooled, axis=1)[:, None], 1e-12)
                vectors.extend(normalized.astype(float).tolist())
            return vectors

    def documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, "passage: ")

    def query(self, text: str) -> list[float]:
        return self._encode([text], "query: ")[0]

    def close(self) -> None:
        with self._lock:
            self._session, self._tokenizer = None, None
