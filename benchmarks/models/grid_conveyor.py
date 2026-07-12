"""100x100 grid conveyor network: items traverse contended segments (SimPy 3).

Each grid cell is a single-capacity conveyor segment. Items enter at the
top-left, travel along row 0 to the right edge, then down the right column to
the bottom-right exit, requesting each segment in turn so that staggered items
contend for shared cells.
"""

import random

import simpy

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
    rng = random.Random(seed)
    env = simpy.Environment()
    segments = {
        (row, col): simpy.Resource(env, capacity=1)
        for row in range(rows)
        for col in range(cols)
    }
    route = _route(rows, cols)
    total_transit = 0.0
    delivered = 0

    def item() -> object:
        nonlocal total_transit, delivered
        entered_at = env.now
        for cell in route:
            with segments[cell].request() as slot:
                yield slot
                yield env.timeout(SEGMENT_TRANSIT)
        total_transit += env.now - entered_at
        delivered += 1

    def feeder() -> object:
        for _ in range(num_items):
            yield env.timeout(rng.expovariate(1.0 / ARRIVAL_INTERVAL_MEAN))
            env.process(item())

    env.process(feeder())
    env.run()

    return {
        "items_delivered": float(delivered),
        "mean_transit": round(total_transit / delivered, 6),
    }
