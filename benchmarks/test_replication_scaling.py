"""Enforcing parallel-efficiency gate for replication throughput.

Standard CI runners have only ~2 *physical* cores (their reported vCPUs are
SMT threads), so the enforced gate runs 2 workers -- genuine parallelism on
every runner class -- and requires a total speedup that cleanly separates
real scaling (measured 1.6-2.0x at 2 workers, processes) from an accidental
coordinator serialization (which reads ~1.0x). The headline many-core curve
is recorded in ``docs/perf-notes.md`` instead (docs-honesty rule).
"""

import os

import pytest

from benchmarks.replication_scaling import parallel_seconds, sequential_seconds

#: Workers used by the gate: 2-way parallelism exists on every CI runner
#: class; higher counts oversubscribe hyperthreaded 2-core runners and turn
#: the gate into an SMT lottery (observed: 1.58x at "4 workers" on 2 cores).
GATE_WORKERS = 2

#: Enforced minimum total speedup at GATE_WORKERS. Measured 1.87-1.98x
#: locally and ~1.6x+ on CI runners; a serialization regression reads ~1.0x.
MIN_SPEEDUP = 1.35

# The gate pins the process backend -- the one whose scaling llmsim stands
# behind on every build today. The thread backend currently anti-scales on
# 3.14t (interpreter-level refcount contention, a documented slowdown regime
# in docs/perf-notes.md), so gating "auto" would gate a known-red regime on
# free-threaded runners rather than catch llmsim regressions.
GATE_BACKEND = "processes"


def test_parallel_efficiency_gate() -> None:
    if (os.process_cpu_count() or 1) < 2:
        pytest.skip("parallel-efficiency gate needs at least 2 cores")
    baseline = sequential_seconds()
    elapsed = parallel_seconds(GATE_WORKERS, backend=GATE_BACKEND)
    speedup = baseline / elapsed
    assert speedup >= MIN_SPEEDUP, (
        f"replication throughput at {GATE_WORKERS} workers is {speedup:.2f}x "
        f"sequential, below the {MIN_SPEEDUP:.2f}x gate "
        f"(sequential {baseline:.2f}s, parallel {elapsed:.2f}s)"
    )
