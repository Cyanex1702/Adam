# ADR 0004: compact starter model

The user supplied i5 6th generation, 16 GB DDR4, and Quadro M4000 hardware and
authorized a downloaded model, preferably uncensored, with a normal-model fallback.
The NVIDIA driver reports 8192 MiB VRAM. The reference Qwen3-8B remains configurable;
a 4B Q4_K_M model is used for a smaller initial footprint. No architecture contract changed.

The abliterated candidate fit in memory and passed basic personality smoke tests but
was inconsistent on multilingual replies, including a response that exhausted the
output limit. It is retained as an explicitly unaccepted optional profile.
The fallback is the unmodified Qwen3-4B-Instruct-2507, quantized by Unsloth.

Files are stored on C: application data instead of F: because comparative downloads
and small-file operations exposed a large F: performance penalty. llama.cpp b11146
Vulkan detected Quadro M4000 successfully. Startup uses one slot, 4096 context,
three CPU threads, no spin polling, no built-in tools/Web UI/slots endpoint, and
restricted CORS. Only loopback services are exposed. CPU fallback is explicit.

Normal model revision: a06e946bb6b655725eafa393f4a9745d460374c9.
Normal GGUF SHA-256: 3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597.
Optional abliterated revision: c3248878a96c4b72cb4d2eb79069389c5827dbb9.
Optional GGUF SHA-256: d416c35bfba822e0156cc5257d4f8cee49f9c83e4a947f86b91d97ee8b98893c.
Vulkan ZIP SHA-256: 55a378aa095b466979d85075234f66d7655c7a7483222af0c006c0e55b4d7bd6.

Sources inspected 2026-10-05:
- https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF
- https://huggingface.co/IamLucif3r/Qwen3-4B-Instruct-2507-Abliterated
- https://github.com/ggml-org/llama.cpp/releases/tag/b11146
