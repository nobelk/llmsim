"""Benchmark harness: run the three SimPy 3 models, enforce KPI and timing.

Run with ``uv run --group bench pytest benchmarks/``. This asserts all three
canonical models are present, that each is deterministic, and that each matches
its committed machine-class baseline (KPI exactly; timing within tolerance,
auto-recording when no baseline exists yet).
"""

import warnings
from typing import TYPE_CHECKING

import pytest

from benchmarks.baselines import (
    TIMING_TOLERANCE,
    load_baseline,
    machine_class,
    save_baseline,
)
from benchmarks.models import MODELS

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

# The three canonical models Phase 0 must ship. Determinism and timing tests
# parametrize over MODELS directly so coverage always tracks the registry; this
# frozenset is the single spec pin, asserted by test_all_canonical_models_present
# so the registry can never silently gain or lose a model.
EXPECTED_MODELS = frozenset({"mm1_queue", "machine_shop", "grid_conveyor"})


def test_all_canonical_models_present() -> None:
    """The registry contains exactly the three canonical models."""
    assert set(MODELS) == EXPECTED_MODELS, (
        f"benchmark registry {set(MODELS)} != expected {set(EXPECTED_MODELS)}"
    )


@pytest.mark.parametrize("name", sorted(MODELS))
def test_model_is_deterministic(name: str) -> None:
    """The same seed produces the same KPI on repeated runs."""
    runner = MODELS[name]
    assert runner() == runner(), f"{name} is not deterministic for a fixed seed"


@pytest.mark.parametrize("name", sorted(MODELS))
def test_benchmark_matches_baseline(benchmark: "BenchmarkFixture", name: str) -> None:
    """Time the model and enforce its machine-class baseline."""
    kpi = benchmark(MODELS[name])
    mean_seconds = float(benchmark.stats.stats.mean)
    _enforce_baseline(name, kpi, mean_seconds)


def _enforce_baseline(name: str, kpi: dict[str, float], mean_seconds: float) -> None:
    """Check ``kpi``/``mean_seconds`` against the baseline, recording if absent."""
    key = machine_class()
    baseline = load_baseline(key) or {"machine_class": key, "models": {}}
    entry = baseline["models"].get(name)

    if entry is None:
        baseline["models"][name] = {"kpi": kpi, "seconds": mean_seconds}
        save_baseline(baseline, key)
        warnings.warn(
            f"recorded new benchmark baseline for {name!r} on {key}; "
            f"commit benchmarks/baselines/{key}.json to enforce it",
            stacklevel=2,
        )
        return

    assert kpi == entry["kpi"], (
        f"{name} KPI drifted from baseline: {kpi} != {entry['kpi']}"
    )
    limit = entry["seconds"] * (1.0 + TIMING_TOLERANCE)
    assert mean_seconds <= limit, (
        f"{name} timing regressed on {key}: "
        f"{mean_seconds:.6f}s > {limit:.6f}s (baseline {entry['seconds']:.6f}s)"
    )
