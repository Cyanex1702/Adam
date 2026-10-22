# Milestone 9.1 - Resource Manager

The shared provider manager exposes lifecycle, bounded telemetry history, RAM and
storage admission, optional measured GPU admission and a capability envelope.
Priority classes are CRITICAL, INTERACTIVE, HIGH, NORMAL, LOW and IDLE. Background
consolidation and explicit reindex use low-priority scheduling; queued interactive
generation runs first at safe operation boundaries. A running SQLite/embedding
operation is not forcibly interrupted. Cancelled threaded work keeps its slot
until the worker has finished, preventing overlapping mutations.

Out-of-memory faults and repeated transport failures latch ERROR, reject further
generation and require cooldown plus explicit healthy reload. No automatic crash
restart loop is installed. Explicit memory commands remain usable under compute
pressure. A live turn blocks load/unload/swap. Cancellation closes nested streams
and releases session leases and scheduler slots.

External provider load/unload attaches/detaches the adapter; it never terminates
someone else's server. The next milestone adds owned-process lifecycle. GPU
admission is opt-in for GPU-backed models; missing VRAM measurements then fail
closed. CPU-backed models do not claim to manage GPU allocation.

`/developer/compute`, `/load` and `/unload` require fresh owner access. Developer
health includes resource pressure and honest capability degradation. Unit tests
use synthetic host headroom; explicit pressure/OOM tests remain deterministic.
Live QA measures actual hardware and is not covered by that fixture.
