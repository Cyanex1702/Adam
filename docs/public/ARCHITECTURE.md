# Architecture

ADAM separates personal state and permissions from replaceable model weights.

```mermaid
flowchart TD
    Desktop[Tauri desktop and React UI] --> Local[Private loopback desktop service]
    Phone[Approved Android browser over LAN TLS] --> Mesh[Device pairing and scoped mesh gateway]
    Mesh --> API[Authenticated API boundary]
    Local --> API
    CLI[Local trusted source terminal] --> Runtime[ADAM runtime]
    API --> Profiles[Owner / guest / fictional demo profiles]
    Profiles --> Runtime
    Runtime --> Identity[Identity and epistemic contracts]
    Runtime --> Memory[SQLite memory and valid-time history]
    Runtime --> RAG[Local sources, keyword / optional semantic retrieval]
    Runtime --> Models[Model-independent provider and resource admission]
    Models --> Llama[Owned llama.cpp and external local adapters]
    API --> Personal[Evidence-linked graph, goals and manual briefings]
    Personal --> Memory
    API --> Actions[Reviewed actions, tasks and explicit Win32 plans]
    Actions --> Verify[Bounded provider and result verification]
    API --> Recovery[Encrypted backup, staged restore, update and rollback]
    API --> Training[Disabled-by-default synthetic behavior experiment]
    API --> Portfolio[Fictional sandbox and bundled benchmark evidence]
```

The SQLite runtime database contains versioned memory, conversations, knowledge
metadata and personal structures. Foreign keys bind relationships/goals to source
memory; forgetting cascades to dependent structures. Other subsystems retain their
own bounded stores. Portable backups preserve source data and omit derived indexes
and device secrets. Restore revokes sessions and resets device/training consent.

Models produce text; ordinary chat has no direct computer-action authority.
Explicit action providers validate permissions and current state separately.
The personal graph is an annotation layer and cannot override source evidence.
Screenshots/OCR do not become trusted instructions. Trace events store bounded
metadata rather than hidden reasoning or chat payloads.

The source-with-model bundle runs editable `backend/adam` Python using a copied,
relocatable Python runtime. It places weights in `models`, llama.cpp in
`runtime/llama`, and new local state in `data`. The desktop installer is separate:
it contains a frozen backend and compiled frontend. Both share runtime contracts.
