# Milestone 12.0 — Advisory speaker recognition

Implemented local CPU TitaNet embeddings, consent-based enrollment, encrypted
profile-scoped revocable templates, bounded confidence/margin matching and
explicit unknown identity. Enrollment and removal require fresh owner password
reauthentication. Voice matches grant no authority and never change Principal.
Exact repeated normalized audio is flagged; other replay/clone risk remains open.
See [speaker operations](speakers.md) and Wave 11 evidence for verification.
