# Third-party materials

The Community Non-Commercial License v1.0 applies to Cyanex's ADAM material.
Section 10 preserves each third-party component's own terms. It does not relicense
models, Python, llama.cpp or Python/JavaScript/Rust dependencies.

The full offline source distribution includes:

| Component | Origin and notice |
| --- | --- |
| Qwen3-4B-Instruct-2507, Unsloth Q4_K_M GGUF | [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), [quantization](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF); Apache 2.0. Full model license and pinned artifact metadata are under `models/`. |
| llama.cpp b11146 Windows Vulkan runtime, used in CPU mode by default | [Upstream](https://github.com/ggml-org/llama.cpp); MIT license included under `runtime/llama/`. Included OpenMP notices remain there. |
| CPython 3.13 | [Python license](https://docs.python.org/3/license.html); complete `LICENSE.txt` retained under `runtime/python/`. |
| Python dependencies | Exact versions in `requirements.lock.txt`; package metadata and supplied license directories are retained under `runtime/python/Lib/site-packages/`. |
| Desktop dependencies | Versions and dependency trees in `apps/desktop/package-lock.json` and `apps/desktop/src-tauri/Cargo.lock`; installed desktop artifacts are a separate distribution. |

The full offline ZIP is a distribution artifact, not a Git repository. Its `models`,
`runtime` and `data` folders are excluded from Git. The GitHub source ZIP does not
contain model weights or third-party runtime binaries. Redistribution must retain
the applicable notices and satisfy the licenses of the included components.
