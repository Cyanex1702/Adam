# Milestone 4.2

The separate vault database contains encrypted payloads, opaque handles and purpose
metadata. Windows uses current-user DPAPI with UI disabled. The explicit encrypted
fallback uses Fernet authenticated encryption and Argon2id with 64 MiB, three passes
and four lanes; only its salt/verifier/ciphertext persist. Fallback keys require an
owner-supplied passphrase after restart. Disabled, locked, corrupt and unavailable
backends fail closed; no plaintext fallback exists.

HTTP/terminal vault management requires owner reauthentication. Backend consumers
are registered only by trusted code, bound to purpose, and receive a SecretValue
whose ordinary representation is redacted. Returned values are discarded; failures
use fixed codes. No API can return a raw value or register a callable. Tool execution
remains Wave 5 work.

NEVER_LOG events are omitted entirely. Known values and owner/fallback passwords are
registered in a private in-process denial cache, excluded from ordinary memory,
source chunks, history views and constructed context before tokenizer calls. Vault
operations do not enter ordinary chat storage/audit. Unknown arbitrary secret strings
cannot be inferred. The vault does not retroactively encrypt preexisting cleartext
records or external files/backups. Python cannot promise forensic RAM erasure.

70 regression tests, Ruff lint/format and strict mypy pass. Vault tests cover both
real Windows DPAPI and fallback encryption/restart, callback scope and errors,
unavailability, swapped ciphertext, validation without echoes, omission from audit,
model context and embedding inputs. Twelve captured adversarial guest/demo requests
exclude owner private context. A revoked live WebSocket cannot commit another command.
Runtime/package 0.4.0; core schema remains 6, auth schema 1, vault schema 1.

Crypto choices follow the primary [Fernet documentation](https://cryptography.io/en/latest/fernet/)
and Microsoft's [DPAPI scope and example](https://learn.microsoft.com/en-us/windows/win32/seccrypto/example-c-program-using-cryptprotectdata).
