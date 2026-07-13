"""Loose PDES performance floor: sharding must never be catastrophic.

Per the Phase 3 key decision, correctness is gated strictly (the equivalence
suite) while performance is measured and published; the only CI-enforced
timing assertion is that a 2-shard threaded run is not catastrophically
slower than the sequential reference. Measured ratios: ~1.1x on 3.14t and
~0.90x on the GIL build (time-sliced threads + barrier overhead) on a 10-core
M5 — the 0.5x floor trips only on a genuine synchronizer regression (e.g. a
barrier storm), not on build or runner variance. Timing assertions are
skipped on shared macOS CI runners (Phase 2 measured ~20% best-of-N spread
there); KPI-free correctness runs on every platform via the test suite.
"""

import warnings

from benchmarks import skip_if_shared_macos_ci
from benchmarks.pdes_scaling import GRID_UNTIL, grid_topology, timed_run

MIN_TWO_SHARD_RATIO = 0.5


def test_two_shard_run_is_not_catastrophically_slower() -> None:
    skip_if_shared_macos_ci()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # GIL-build notice
        sequential = timed_run(grid_topology(1), until=GRID_UNTIL, mode="sequential")
        sharded = timed_run(grid_topology(2), until=GRID_UNTIL, mode="threads")
    ratio = sequential / sharded
    assert ratio >= MIN_TWO_SHARD_RATIO, (
        f"2-shard grid conveyor ran at {ratio:.2f}x sequential, below the "
        f"{MIN_TWO_SHARD_RATIO}x catastrophic-regression floor "
        f"(sequential {sequential:.2f}s, sharded {sharded:.2f}s)"
    )
