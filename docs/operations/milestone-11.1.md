# Milestone 11.1 — Pause and turn decisions

Implemented in release 0.10.0: active/listening, wait and take-turn decisions,
bounded silence features, a heuristic turn-end probability, English/Urdu/Roman
Urdu incomplete-word/filler handling and confidence gating. Complete utterances
can finish sooner; incomplete utterances wait longer. Pause adaptation is held
in memory, bounded to 600–1600 ms and resettable to 900 ms.

Parameterized scripted tests cover long pauses, incomplete phrases, fillers,
active speech, low confidence, reset and owner/demo isolation. Adaptation is
scoped to authenticated profiles. Biometric per-speaker attribution is not
implemented, because speaker recognition is Wave 11. No statistically calibrated
false-interruption rate or real-room conversational timing is claimed. Gate 10
tests whether these heuristics are comfortable for the actual user's speech.
