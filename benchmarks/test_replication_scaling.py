"""Enforcing parallel-efficiency gate for replication throughput.

Standard CI runners have only a few cores, so the enforced gate is a
per-core-efficiency floor at ``min(4, cpu_count)`` workers rather than the
headline speedup, which is recorded from a many-core run in
``docs/perf-notes.md`` (docs-honesty rule). The floor carries generous margin
under the locally measured efficiencies (0.77x/core at 4 workers on a 10-core
M5; Linux forkserver workers start cheaper than macOS spawn) so the gate
catches a real scaling regression -- e.g. accidental serialization in the
coordinator -- without flaking on runner noise.
"""

import os

import pytest

from benchmarks.replication_scaling import parallel_seconds, sequential_seconds

# Enforced minimum per-core efficiency (speedup / workers) at GATE_WORKERS
# workers. Measured locally: 0.72-0.77 at 4 workers (processes); the floor
# sits far below so only a genuine regression trips it.
EFFICIENCY_FLOOR = 0.40

GATE_WORKERS = min(4, os.process_cpu_count() or 1)

# The gate pins the process backend -- the one whose scaling llmsim stands
# behind on every build today. The thread backend currently anti-scales on
# 3.14t (interpreter-level refcount contention, a documented slowdown regime
# in docs/perf-notes.md), so gating "auto" would gate a known-red regime on
# free-threaded runners rather than catch llmsim regressions.
GATE_BACKEND = "processes"


def test_parallel_efficiency_gate() -> None:
    if GATE_WORKERS < 2:
        pytest.skip("parallel-efficiency gate needs at least 2 cores")
    baseline = sequential_seconds()
    elapsed = parallel_seconds(GATE_WORKERS, backend=GATE_BACKEND)
    speedup = baseline / elapsed
    floor = EFFICIENCY_FLOOR * GATE_WORKERS
    assert speedup >= floor, (
        f"replication throughput at {GATE_WORKERS} workers is {speedup:.2f}x "
        f"sequential, below the {floor:.2f}x efficiency gate "
        f"(sequential {baseline:.2f}s, parallel {elapsed:.2f}s)"
    )
