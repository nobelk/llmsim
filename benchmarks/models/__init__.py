"""Canonical SimPy 3 benchmark models and their registry.

These three models are the Phase 0 performance baselines: they are implemented
in *SimPy 3* (never llmsim) so that later phases can compare llmsim's
reimplementations against a recorded, apples-to-apples reference. Each model is
seeded and deterministic: the same seed yields the same KPI on any machine.
"""

from collections.abc import Callable

from benchmarks.models.grid_conveyor import run_grid_conveyor
from benchmarks.models.machine_shop import run_machine_shop
from benchmarks.models.mm1 import run_mm1

# The fixed seed every baseline run uses, so KPIs are reproducible.
BASELINE_SEED = 20260712

# name -> zero-argument runner returning a KPI mapping. Keeping the three
# canonical models in one registry lets the harness assert none is missing.
MODELS: dict[str, Callable[[], dict[str, float]]] = {
    "mm1_queue": lambda: run_mm1(seed=BASELINE_SEED),
    "machine_shop": lambda: run_machine_shop(seed=BASELINE_SEED),
    "grid_conveyor": lambda: run_grid_conveyor(seed=BASELINE_SEED),
}

__all__ = [
    "BASELINE_SEED",
    "MODELS",
    "run_grid_conveyor",
    "run_machine_shop",
    "run_mm1",
]
