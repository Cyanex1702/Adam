# Milestone 9.0 - Offline Hardware Profiler

The local profiler measures CPU, RAM, storage and OS, detects GPUs through
nvidia-smi with a Windows CIM name-only fallback, and reports optional sensors as
null when unavailable. It does not probe internet reachability or collect host
names, serials, MACs or IPs. Runtime availability distinguishes installed files
from verified acceleration. An optional bounded SHA-256 benchmark measures local
memory/CPU throughput, not model quality or disk/GPU performance.

`python -m adam.compute.cli hardware --benchmark` runs locally without starting
ADAM or a model. `/developer/hardware?benchmark=true` requires fresh owner access.
Nine profiler tests cover offline operation, unchanged store, 8 GiB VRAM parsing,
unavailable values, failed probes and timeout sanitization. Full regression and
static checks are required at the checkpoint.

Measurement references: [psutil](https://psutil.io/),
[NVIDIA SMI](https://docs.nvidia.com/deploy/nvidia-smi/index.html).
No new generation model or GPU driver is installed.
