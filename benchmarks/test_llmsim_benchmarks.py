"""llmsim canonical-model gate: KPI equivalence, determinism, and speedup.

Run with ``uv run --group bench pytest benchmarks/``. For each of the three
canonical models this asserts:

* **Equivalence** -- the llmsim model produces the *same* KPI as its SimPy 3
  reference for the shared seed (llmsim reproduces SimPy 3's event ordering and
  RNG draw sequence exactly).
* **Determinism** -- the same seed yields the same KPI on repeated llmsim runs.
* **Speedup** -- a head-to-head, same-machine timing of llmsim against SimPy 3
  clears a per-model threshold. ``grid_conveyor`` (object-heavy) clears the
  >=1.2x design target; the call-bound ``mm1_queue`` and ``machine_shop`` run at
  parity, enforced as a no-meaningful-regression floor. The measured ratios and
  the parity regime are documented in ``docs/perf-notes.md`` (docs-honesty rule).
"""

import time
from collections.abc import Callable

import pytest

from benchmarks.llmsim_models import LLMSIM_MODELS
from benchmarks.models import MODELS as SIMPY_MODELS

# The three canonical models, asserted present so the registry cannot silently
# drift from the SimPy 3 reference registry.
EXPECTED_MODELS = frozenset({"mm1_queue", "machine_shop", "grid_conveyor"})

# Per-model enforced minimum speedup (SimPy 3 time / llmsim time), measured
# head-to-head on the same machine. ``grid_conveyor`` clears the >=1.2x design
# target (measured ~1.24-1.38x locally); its CI floor sits below that with
# margin so the gate catches a genuine regression toward parity without flaking
# on shared-runner noise at the exact 1.2x line. The call-bound models are
# dominated by generator ``send``/``heapq`` work that is identical in both
# engines, so they run at parity and are gated only against a meaningful
# regression (see docs/perf-notes.md).
MIN_SPEEDUP = {
    "grid_conveyor": 1.15,
    "mm1_queue": 0.9,
    "machine_shop": 0.9,
}

# Repetitions for the head-to-head timing; the fastest (least-interrupted) run
# of each engine is compared, the standard stable micro-benchmark statistic.
# A larger count makes the min more robust on noisy CI runners.
TIMING_REPETITIONS = 15


def _best_seconds(runner: Callable[[], dict[str, float]]) -> float:
    """Return the fastest wall-clock time of *runner* over several repetitions."""
    runner()  # warm caches / JIT before measuring
    best = float("inf")
    for _ in range(TIMING_REPETITIONS):
        start = time.perf_counter()
        runner()
        best = min(best, time.perf_counter() - start)
    return best


def test_all_canonical_models_present() -> None:
    """The llmsim registry contains exactly the three canonical models."""
    assert set(LLMSIM_MODELS) == EXPECTED_MODELS
    assert set(LLMSIM_MODELS) == set(SIMPY_MODELS)


@pytest.mark.parametrize("name", sorted(EXPECTED_MODELS))
def test_llmsim_matches_simpy_kpi(name: str) -> None:
    """Each llmsim model reproduces its SimPy 3 reference KPI exactly."""
    assert LLMSIM_MODELS[name]() == SIMPY_MODELS[name]()


@pytest.mark.parametrize("name", sorted(EXPECTED_MODELS))
def test_llmsim_is_deterministic(name: str) -> None:
    """Each llmsim model is same-seed-same-result across repeated runs."""
    runner = LLMSIM_MODELS[name]
    assert runner() == runner()


@pytest.mark.parametrize("name", sorted(EXPECTED_MODELS))
def test_llmsim_speedup_vs_simpy(name: str) -> None:
    """llmsim clears its per-model speedup threshold against SimPy 3."""
    simpy_seconds = _best_seconds(SIMPY_MODELS[name])
    llmsim_seconds = _best_seconds(LLMSIM_MODELS[name])
    speedup = simpy_seconds / llmsim_seconds
    assert speedup >= MIN_SPEEDUP[name], (
        f"{name}: llmsim speedup {speedup:.3f}x below required "
        f"{MIN_SPEEDUP[name]}x (SimPy {simpy_seconds * 1000:.3f}ms, "
        f"llmsim {llmsim_seconds * 1000:.3f}ms)"
    )
