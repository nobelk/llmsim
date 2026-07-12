"""100x100 grid conveyor network on llmsim: items traverse contended segments.

A one-for-one port of ``benchmarks/models/grid_conveyor.py`` (SimPy 3) to the
llmsim API.
"""

from collections.abc import Generator
from typing import Any

from llmsim import Event, Resource, Sim

SEGMENT_TRANSIT = 1.0
ARRIVAL_INTERVAL_MEAN = 2.0


def _route(rows: int, cols: int) -> list[tuple[int, int]]:
    """Return the fixed L-shaped path of cells from entry to exit."""
    top_row = [(0, col) for col in range(cols)]
    right_column = [(row, cols - 1) for row in range(1, rows)]
    return top_row + right_column


def run_grid_conveyor(
    seed: int,
    rows: int = 100,
    cols: int = 100,
    num_items: int = 40,
) -> dict[str, float]:
    """Simulate the grid conveyor network and return flow KPIs.

    Args:
        seed: Master seed for the single shared random stream.
        rows: Grid height (number of conveyor rows).
        cols: Grid width (number of conveyor columns).
        num_items: Number of items pushed through the network.

    Returns:
        Mapping with ``items_delivered`` and ``mean_transit`` (mean end-to-end
        time across delivered items).
    """
    sim = Sim(seed=seed)
    rng = sim.rng
    segments = {
        (row, col): Resource(sim, capacity=1)
        for row in range(rows)
        for col in range(cols)
    }
    route = _route(rows, cols)
    total_transit = 0.0
    delivered = 0

    def item(sim: Sim) -> Generator[Event[Any], Any, None]:
        nonlocal total_transit, delivered
        entered_at = sim.now
        for cell in route:
            with segments[cell].request() as slot:
                yield slot
                yield sim.delay(SEGMENT_TRANSIT)
        total_transit += sim.now - entered_at
        delivered += 1

    def feeder(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(num_items):
            yield sim.delay(rng.expovariate(1.0 / ARRIVAL_INTERVAL_MEAN))
            sim.spawn(item)

    sim.spawn(feeder)
    sim.run()

    return {
        "items_delivered": float(delivered),
        "mean_transit": round(total_transit / delivered, 6),
    }
