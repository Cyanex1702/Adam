# Portfolio and delivery — Wave 20

Use **Explore fictional demo** on the lock screen or **Switch to fictional demo**
in Settings. It creates a physically separate profile containing only generated
Cedar/Orchid facts, a sample project, an example goal and fictional repeated reviews.
No owner conversations, knowledge paths or secrets are copied.

Try `/show memory demo editor`, `/ask What is Cedar launch command?`, `/graph Cedar`
and `/briefing`. Inspect source evidence in **Personal intelligence**. In **Demo and
benchmarks**, inspect the sandbox, write a fictional note, verify its contents and
undo it. The note tool accepts no path, executable or network destination and only
operates within that demo profile. Unexpected changes block undo; never retry a
failed real-world action based on this fictional demonstration.

The benchmark view reads a bundled synthetic evaluation report, identifies its
model/transport and dataset digest, derives category rates from actual case results
and shows scenario durations. Scripted-probe results measure framework integration,
not Qwen quality. Durations include fixture setup; they are not token latency.
VRAM and voice benchmark measurements remain unavailable and are shown as such.
Private owner traces are never loaded into the public benchmark view.

The full **source-with-model ZIP** includes `RUN_ADAM.bat`, editable source, a
relocatable Python runtime, pinned llama.cpp and the verified Qwen model in `models/`.
Extract the entire ZIP into a writable folder, then double-click `RUN_ADAM.bat`.
It runs Python source, verifies the model hash, uses a three-thread CPU profile
with 2048 context/384 output tokens, and stores new data in `data/`. `/quit` stops
the owned model. `RUN_DEMO.bat` opens a fictional terminal profile. No global Python
installation, pip download or PowerShell execution-policy change is needed.

The smaller **GitHub source ZIP** excludes models, runtime binaries, personal data,
Git history and machine-specific operational evidence. Install locked Python
dependencies and run `scripts/setup-model.ps1` for a fresh development checkout.
Windows source CI is provided but is not claimed to have run on GitHub until pushed.
The package preparer checks source paths and runtime licenses; SHA-256 receipts
identify delivery artifacts. Nothing is published or pushed automatically.

The code is source-available under Cyanex's **Community Non-Commercial License
v1.0**, not a permissive open-source license. Third-party materials retain their
own terms. Read `LICENSE` and `THIRD_PARTY.md` before redistributing.
