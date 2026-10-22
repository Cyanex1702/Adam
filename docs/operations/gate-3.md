# Gate 3 — Knowledge and grounded answers

Wave 3 is automated verified. Gate 3 human validation remains pending. Use these
fictional samples first, then a few of your own documents. They are not automatically
ingested into your normal data. Existing conversation and memory commands still work.

Start from PowerShell:

```powershell
Set-Location -LiteralPath '%PROJECT_ROOT%'
.\scripts\start.ps1
```

The embedding model is already downloaded and verified on this machine. Fresh setup:
run `scripts\dev.ps1 -Install -Command init`, then `scripts\setup-knowledge.ps1` once.
The latter explicitly downloads about 487 MB from Hugging Face. Subsequent operation
is offline. The model uses two CPU threads and no GPU resources.

In the ADAM terminal:

```text
/namespace demo
/ingest "%PROJECT_ROOT%\docs\examples\wave3\launch.md"
/ingest "%PROJECT_ROOT%\docs\examples\wave3\backup.txt"
/ingest "%PROJECT_ROOT%\docs\examples\wave3\worker.py"
/ingest "%PROJECT_ROOT%\docs\examples\wave3\security.pdf"
/ask What command launches Cedar and what port does it use?
/ask Cedar launch command and Orchid backup schedule
/ask How does Birch protect saved files?
/ask What salary does Cedar pay?
/ask Orchid ka backup kis din hota hai?
/ask Cedar سروس کیسے شروع کریں؟
/inspect Cedar launch command
/sources
```

Expect quoted source text and citations with path, source ID, version and line/page
locator. The salary question should abstain. Multi-source questions should show both
relevant documents. `/inspect` shows first-stage ranking, lexical/semantic scores,
freshness exclusions and HYBRID or KEYWORD mode. Scores measure relevance, not truth.
The API's `/knowledge/answer` additionally shows reranked citations, sufficiency and
conflict details. Open `http://127.0.0.1:8765/docs` after starting with `-Api` to inspect it.

Test conflicts:

```text
/ingest "%PROJECT_ROOT%\docs\examples\wave3\conflict.txt"
/ask What is retry_limit?
```

Expect a conflict between 3 and 5 with both citations, without choosing a value.
Conflict detection covers repeated structured fields (`key = value`, `key: value`,
simple `key is value`). It does not establish arbitrary prose contradictions.

Test freshness using **copies** of the samples under `%PROJECT_ROOT%\knowledge-demo`:
create the folder and copy the sample files there before ingesting those paths.

1. Ingest the copy of launch.md in a new namespace, e.g. `/namespace freshness`.
2. Edit its port from 9123 to 9444. `/refresh` should mark it STALE; `/ask` must exclude
   its previous content. `/reindex` alone does not parse changed originals.
3. Reingest the same path. Its version should increase and the new port should appear.
4. Rename the file, then reingest the new path. Its canonical source ID should stay
   the same. Before reingestion, the missing old path is excluded.
5. Delete the copy. `/refresh` and subsequent questions must exclude that source.
6. Switch to `/namespace unrelated`. Demo evidence must not appear in that scope.
7. Use `/reindex`, `/quit`, restart, `/namespace demo`, then ask again. Verify citations
   still work. `/sessions` and `/resume ID` restore prior successful turn receipts.
8. `/show memory retry_limit` must not invent a personal memory from indexed documents.

For your own files outside the project, configure an explicit root in the TOML
selected through `ADAM_CONFIG` (or `adam.local.toml` when using the dev helper):

```toml
[knowledge]
enabled = true
allowed_roots = ["%PROJECT_ROOT%", "%USERPROFILE%/Documents/My Knowledge"]
chunk_chars = 1000
embedding_threads = 2
```

Use UTF-8 text/code and text PDFs. Scanned PDFs need OCR elsewhere. Files are bounded
to 32 MiB and extracted text to one million characters. Index and SQLite data reside
under `%LOCALAPPDATA%\ADAM\knowledge` and `%LOCALAPPDATA%\ADAM\runtime.sqlite3`.
Original blobs and version history remain available after a source disappears;
rebuilds affect derived vectors, not original data.

Grounded answers use an **extractive policy**: exact canonical text (with displayed
line-break formatting), source citations and RETRIEVED status. They do not produce
free-form model summaries or translations. Relevance/sufficiency is heuristic and
can abstain on supported questions or return only partially relevant excerpts. Source
claims are not independently verified. Ordinary chat uses Qwen; `/ask` explicitly
selects knowledge mode. Knowledge turns are excluded from ordinary chat context,
rolling owner summaries and automatic personal-memory candidate extraction.

One process can own a local Qdrant index at a time. A second API/terminal uses keyword
retrieval with an explicit diagnostic. Close the first before rebuilding in another.
This remains a local OS-account owner alpha; guest authentication belongs to Wave 4.

Record outcomes for citations, missing answers, multi-source evidence, conflicts,
freshness, namespaces, cross-language retrieval and memory continuity. Gate 3 is ready
for your testing; Wave 4 has not begun.
