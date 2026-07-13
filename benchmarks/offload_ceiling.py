"""Record the offload max-vs-sum ceiling curve on this build.

Run directly (``uv run python benchmarks/offload_ceiling.py [backends...]``)
to print the measured curves for the current interpreter; run under both 3.14
and 3.14t to produce the numbers published in ``docs/perf-notes.md``. The
enforcing CI gate lives in ``benchmarks/test_offload_ceiling.py``; this module
owns the model and the shared measurement helpers.

The ceiling being measured: with strict completion slots, a busy window's
wall-clock cost is the *max* of its overlapping offloads on a big-enough pool
versus the *sum* when run inline -- so the best possible speedup per window is
the number of overlapping offloads, and a model whose offloads never overlap
in simulated time gets pure dispatch overhead (the documented no-overlap
slowdown regime).
"""

import sys
import time
from collections.abc import Generator
from typing import Any

from llmsim.core.events import Event
from llmsim.core.sim import Sim
from llmsim.parallel.offload import OffloadBackendName, OffloadPool

MASTER_SEED = 20260712

#: Pure-Python CPU work per payload; ~25-40 ms per call on 2024-25 hardware,
#: large enough that per-offload dispatch (pickle + IPC) is a small fraction.
BURN_ITERATIONS = 400_000

#: Offloads overlapping in each busy window (the per-window ceiling).
CONCURRENT = 6

#: Busy windows per run; sized so the inline baseline runs ~1-2 s.
WINDOWS = 8


def offload_cpu_burn(iterations: int) -> float:
    """Burn deterministic pure-Python CPU and return a checksum."""
    total = 0.0
    increment = 1.0000001
    for index in range(iterations):
        total += increment * index - (index >> 1)
    return total


def overlapping_seconds(backend: OffloadBackendName, max_workers: int | None) -> float:
    """Time the overlapping model: CONCURRENT offloads share every window."""
    sim = Sim(seed=MASTER_SEED)

    def submitter(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(WINDOWS):
            yield sim.offload(offload_cpu_burn, BURN_ITERATIONS, delay=1.0)

    with OffloadPool(sim, backend=backend, max_workers=max_workers):
        for _ in range(CONCURRENT):
            sim.spawn(submitter)
        start = time.perf_counter()
        sim.run()
        return time.perf_counter() - start


def no_overlap_seconds(backend: OffloadBackendName, max_workers: int | None) -> float:
    """Time the no-overlap regime: one chain, never two offloads in flight."""
    sim = Sim(seed=MASTER_SEED)

    def chain(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(WINDOWS * CONCURRENT):
            yield sim.offload(offload_cpu_burn, BURN_ITERATIONS, delay=1.0)

    with OffloadPool(sim, backend=backend, max_workers=max_workers):
        sim.spawn(chain)
        start = time.perf_counter()
        sim.run()
        return time.perf_counter() - start


def main() -> None:
    """Print both curves: ``... offload_ceiling [backend ...]``."""
    import os

    backends = sys.argv[1:] or ["threads", "processes"]
    gil = sys._is_gil_enabled()
    cores = os.process_cpu_count() or 1
    print(f"build={sys.version.split()[0]} gil={gil} cores={cores}")
    print(f"payloads={WINDOWS * CONCURRENT} concurrent={CONCURRENT}")
    baseline = overlapping_seconds("inline", None)
    print(f"inline (sum): {baseline:.3f}s")
    chain_baseline = no_overlap_seconds("inline", None)
    for backend in backends:
        for workers in (2, 4, 8):
            if workers > cores:
                break
            elapsed = overlapping_seconds(backend, workers)  # type: ignore[arg-type]
            print(
                f"{backend} workers={workers}: {elapsed:.3f}s "
                f"speedup={baseline / elapsed:.2f}x "
                f"(ceiling {min(CONCURRENT, workers)}x)"
            )
        chain = no_overlap_seconds(backend, 2)  # type: ignore[arg-type]
        print(
            f"{backend} no-overlap: {chain:.3f}s vs inline "
            f"{chain_baseline:.3f}s ratio={chain / chain_baseline:.2f}x "
            f"(pure dispatch overhead)"
        )


if __name__ == "__main__":
    main()
