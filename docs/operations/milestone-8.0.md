# Milestone 8.0 - Snapshot and Backup

Implemented encrypted, versioned, integrity-checked snapshots and protected
maintenance API endpoints. Verification: 121 tests, Ruff lint/format, strict mypy
and all 22 framework/security scenarios pass.

Snapshots use existing task/action mutexes and SQLite writer reservations to copy
committed stores together. Busy work fails visibly rather than returning a mixed
snapshot. Models, derived vectors, transient profiles and trace caches are excluded.
Canonical knowledge blobs and sandbox receipts/files are retained. Identity and
active typed settings are serialized independently of the model.

The ADAMBK01 envelope uses AES-256-GCM with a random salt and nonce and an Argon2id
passphrase-derived key (64 MiB, three passes, four lanes). Its header is authenticated;
manifest and filenames are encrypted. File SHA-256, schema/migration checksums,
SQLite integrity/foreign keys and identity checks must pass before publication.
No keys/passphrases are saved. Atomic publication precedes generation retention.
The vault is excluded by default; explicit inclusion preserves its existing sealed DB.
Auth verifier is encrypted in the snapshot; live session tokens are always removed.

Tests cover wrong passwords, tampering, checksum/identity changes, unsafe paths,
compression rejection, retention/failure, executor contention, corruption, WAL and
fresh-owner API authorization. WAL snapshots normalize only the copied header for
portable deserialization, following [SQLite's documented guidance](https://www.sqlite.org/c3ref/deserialize.html).
AEAD usage follows [cryptography's API contract](https://cryptography.io/en/latest/hazmat/primitives/aead/).
The first WAL test also needed its synthetic vault-purpose label corrected.

This format has a 256 MiB bound to avoid exhausting the target PC. Snapshots are
briefly plaintext in process memory, never an unencrypted backup file. External
OS edits cannot be locked by ADAM; detected file changes abort the snapshot.
