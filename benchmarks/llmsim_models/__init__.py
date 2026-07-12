"""Canonical benchmark models reimplemented on llmsim.

These mirror the SimPy 3 reference models in ``benchmarks/models`` one-for-one so
the two can be compared apples-to-apples: for a given seed each llmsim model
produces the *same* KPI as its SimPy 3 twin (llmsim faithfully reproduces
SimPy 3's event ordering and RNG draw sequence), while running faster. The
benchmark harness enforces both properties.
"""

from collections.abc import Callable

from benchmarks.llmsim_models.grid_conveyor import run_grid_conveyor
from benchmarks.llmsim_models.machine_shop import run_machine_shop
from benchmarks.llmsim_models.mm1 import run_mm1

# The fixed seed every baseline run uses, shared with the SimPy 3 reference
# models so their KPIs line up exactly.
BASELINE_SEED = 20260712

# name -> zero-argument runner returning a KPI mapping, keyed identically to the
# SimPy 3 registry so the harness can pair each llmsim model with its reference.
LLMSIM_MODELS: dict[str, Callable[[], dict[str, float]]] = {
    "mm1_queue": lambda: run_mm1(seed=BASELINE_SEED),
    "machine_shop": lambda: run_machine_shop(seed=BASELINE_SEED),
    "grid_conveyor": lambda: run_grid_conveyor(seed=BASELINE_SEED),
}

__all__ = [
    "BASELINE_SEED",
    "LLMSIM_MODELS",
    "run_grid_conveyor",
    "run_machine_shop",
    "run_mm1",
]
