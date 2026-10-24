# Local model library

Open **Model library** after signing into the owner workspace. The model is a
replaceable inference component; conversation history, identity and memory remain
in ADAM when models change.

1. Scan common locations, or enter a specific local model folder. Scanning reads
   directory metadata and regular `.gguf` headers. It does not load, move, copy or
   approve weights, and makes no Internet requests.
2. Review each discovered file. Choose **Quick chat**, **Balanced**, or
   **Reasoning / complex tasks**, then approve its checksum. These are user-assigned
   roles, not measured model-quality claims. Discovery's size suggestion is only
   an estimate.
3. Choose **Use now** for an explicit selection in this runtime, or enable
   **Automatic model selection** for approved candidates. The saved startup default
   is unchanged. The existing promotion/benchmark workflow remains separate.

The inference runtime must already be installed; use Setup and recovery if it is
missing. Search covers ADAM's models, Downloads, Models, LM Studio and the Hugging
Face cache where regular GGUF files are present. Symbolic links, junctions,
network shares, Ollama manifests and non-GGUF formats are not imported. A search
is bounded to five seconds, 5,000 directory entries, depth eight and 100 results.
Select a more specific folder if a broad scan reaches its bounds. At most 20
profiles can be registered in the existing catalog.

Automatic selection uses a transparent task-complexity heuristic, approved roles
and an available-RAM estimate. Eco chooses the smaller fitting model within the
requested role; Priority favors the larger fitting model in that role. If no role
matches, it considers other approved fitting candidates. This is not a reasoning
benchmark, and the size of a model does not prove its suitability.

Only one owned model is loaded at a time during switching. The old owned process
is unloaded before the new one starts. A failed candidate gets one attempt to
restore the prior model and a 60-second automatic-selection cooldown. If no
alternative fits, the current selection is retained and ordinary admission checks
still apply. Existing third-party processes are never terminated.

Checksums are verified again when switching to a different approved file. Changed
size/mtime invalidates its discovery record; rescan and reapprove it. Actual load
errors remain failures, not success receipts. A newly selected model receives the
same framework context subject to its own context budget; older history can be
trimmed according to normal context policy.

Local paths and approval metadata stay in the private profile. The shareable
diagnostic report contains neither these paths nor conversation text. Automatic
selection is off by default. Model-library approvals are not portable evidence of
trust on a different device; review discovered files again after migration.

Source terminal equivalents:

```text
/models scan
/models scan "D:\Models"
/models list
/models approve DISCOVERED_ID quick
/models use DISCOVERED_ID
/models auto on
/models auto off
```

IDs must come from the actual discovery list. Owner-local authorization is required
for discovery, selection and mode changes; guests, demos and remote devices cannot
configure the machine's model library.
