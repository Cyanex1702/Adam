# Release limits

- The supported packaged target is Windows x64. Windows source CI is prepared;
  no GitHub-hosted execution is claimed before it actually runs.
- The offline source bundle uses the verified Qwen3-4B Q4_K_M model in a conservative
  three-thread CPU configuration. Performance depends on available RAM and active
  applications. Resource guards remain enabled.
- Semantic knowledge search, speech recognition, speaker models and general visual
  reasoning need their own optional assets. The full source ZIP includes the chat
  model; it does not imply every optional model is installed. Keyword RAG and
  Windows TTS are available without those extra weights.
- Computer actions support selected standard Win32 fields/buttons with explicit
  review and state verification. Custom-drawn/browser controls, global input and
  automatic rollback of clicks are unsupported.
- Graph matching is bounded keyword/entity search over explicit annotations.
  Routine suggestions are conservative repeated-record heuristics, not behavioral
  certainty or autonomous planning.
- Fine-tuning is experimental. Its data/recipe/comparison workflow is implemented;
  no trained or promoted adapter is claimed.
- Benchmark evidence has a declared synthetic or real-model execution mode. Missing
  VRAM/voice measurements remain unavailable. Finite fixtures do not prove general
  correctness or real-world quality.
- Current desktop, voice/social, Android, clean-VM and other physical-machine human
  acceptance remains pending where no human gate result has been recorded.
