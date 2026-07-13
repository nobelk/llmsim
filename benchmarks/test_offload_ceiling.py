"""Enforcing floor gate for offload max-vs-sum overlap speedup.

Follows the Phase 2/3 CI precedent: the enforced gate pins the process
backend at 2 workers (genuine parallelism on every runner class) and requires
only a catastrophic-regression floor -- real overlap scaling measured
1.66x locally at 2 workers, while a serialization regression (offloads
accidentally resolved at submission, or the slot blocking on every future in
turn) reads ~1.0x. The full per-backend curves, including the thread
backend's build-dependent behavior and the no-overlap regime, are recorded in
``docs/perf-notes.md`` instead (docs-honesty rule).
"""

import os

import pytest

from benchmarks import skip_if_shared_macos_ci
from benchmarks.offload_ceiling import overlapping_seconds

#: Workers used by the gate: 2-way parallelism exists on every CI runner
#: class (see benchmarks/test_replication_scaling.py).
GATE_WORKERS = 2

#: Enforced minimum overlap speedup at GATE_WORKERS on the process backend.
#: Measured 1.66x locally on both builds; ~1.0x means the overlap machinery
#: regressed to serial execution.
MIN_SPEEDUP = 1.25

GATE_BACKEND = "processes"


def test_offload_overlap_floor_gate() -> None:
    skip_if_shared_macos_ci()
    if (os.process_cpu_count() or 1) < 2:
        pytest.skip("offload overlap gate needs at least 2 cores")
    baseline = overlapping_seconds("inline", None)
    elapsed = overlapping_seconds(GATE_BACKEND, GATE_WORKERS)
    speedup = baseline / elapsed
    assert speedup >= MIN_SPEEDUP, (
        f"offload overlap speedup at {GATE_WORKERS} workers is "
        f"{speedup:.2f}x inline, below the {MIN_SPEEDUP:.2f}x floor "
        f"(inline {baseline:.2f}s, pooled {elapsed:.2f}s)"
    )
