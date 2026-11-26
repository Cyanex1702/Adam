import os

import pytest
from adam.core.config import resolve_embedding_dir


@pytest.mark.skipif(os.name != "nt", reason="Windows Store asset paths")
def test_embedding_defaults_to_primary_without_a_mapped_cache(tmp_path):
    env = {"LOCALAPPDATA": str(tmp_path), "ADAM_DATA_DIR": str(tmp_path / "private-data")}
    primary = tmp_path / "ADAM" / "models" / "multilingual-e5-small"
    cache = (
        tmp_path
        / "Packages"
        / "Example.Host_fixture"
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
    assert resolve_embedding_dir(env) == primary
    primary.mkdir(parents=True)
    (primary / "model.onnx").write_bytes(b"test-only")
    assert resolve_embedding_dir(env) == primary
