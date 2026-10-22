# Threat model

ADAM assumes a trusted OS account, trusted local app/runtime files and deliberate
owner approval. It does not defend against local administrator compromise, a
malicious replacement interpreter, an attacker controlling the owner's shell or
forensic access to earlier backups and disk remnants.

| Boundary | Enforcement | Limit |
| --- | --- | --- |
| Owner vs guest/demo | Expiring authentication and physically separate runtime profiles; policy checks precede matching/context | The local owner terminal trusts the OS account |
| Core vs phone | Explicit pairing, trusted LAN TLS, device proof and scoped grants | Android trust/re-pair acceptance still needs physical testing |
| Model vs tools | Reviewed action/task endpoints, digests, fresh authority and verification | Finite checks do not prove every external application effect |
| Screen text vs authority | OCR is untrusted input; standard Win32 action provider uses explicit owner plans | Custom browser/game controls and global mouse/keyboard automation are unsupported |
| Stored facts vs graph | Privacy-filtered source references, current/historical status and cascade deletion | Manual annotations can be mistaken; source evidence takes precedence |
| Personal memory vs training | No automatic chat collection; per-example synthetic/export consent, secret/overlap checks, owner elevation | Unknown personal facts require human review; no validated adapter is provided |
| Update vs live data | Expected package hash, one-use approval, closed profile lease, encrypted snapshot, cloned migration and atomic activation | A checksum is not a publisher signature; no automatic external update feed exists |
| Public demo vs owner environment | Fictional seed data, profile-local note tool, sanitized bundled benchmark report | Demo rubrics are not unrestricted PC access or real-world model-quality guarantees |

Data is local by default, but ordinary conversation/source stores are cleartext
under the OS account. The vault and portable backups use separate encryption.
Recognized credentials are rejected/omitted; filtering is heuristic. Opt-in
network integrations have their own review and destination controls. Runtime
models, source packages, backups and exports require separate distribution care.
