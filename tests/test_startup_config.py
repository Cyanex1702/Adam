import os

import pytest
from adam.core.config import resolve_embedding_dir


@pytest.mark.skipif(os.name != "nt", reason="Windows Store asset paths")
def test_embedding_cache_reuse_keeps_runtime_data_separate(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path), "ADAM_DATA_DIR": str(tmp_path / "private-data")}
    primary = tmp_path / "ADAM" / "models" / "multilingual-e5-small"
    cache = (
        tmp_path
        / "Packages"
        / "OpenAI.Codex_2p2nqsd0c76g0"
        / "LocalCache"
        / "Local"
        / "ADAM"
        / "models"
        / "multilingual-e5-small"
    )
    assert resolve_embedding_dir(env) == primary
    cache.mkdir(parents=True)
    (cache / "model.onnx").write_bytes(b"test-only")
    (cache / "tokenizer.json").write_bytes(b"test-only")
    assert resolve_embedding_dir(env) == cache
    primary.mkdir(parents=True)
    (primary / "model.onnx").write_bytes(b"test-only")
    assert resolve_embedding_dir(env) == primary
