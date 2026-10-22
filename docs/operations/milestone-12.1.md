# Milestone 12.1 — Diarization and overlap

Implemented pyannote segmentation with CPU sherpa-onnx clustering, timed
per-speaker transcript review and conservative overlap clarification. At most
four clusters and sixteen returned segments are accepted per bounded recording.
Unknown, guest, partial, background and overlapping speech cannot automatically
dispatch through the desktop's voice controls. Multi-speaker transcripts are
never merged into one automatic command. No source separation is claimed.
Human acoustic/identity acceptance remains Gate 11 NOT_STARTED.
