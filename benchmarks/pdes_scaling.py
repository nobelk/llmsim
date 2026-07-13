"""PDES scaling measurements: shard count and lookahead degradation.

Run directly (``uv run python -m benchmarks.pdes_scaling``) to print both
curves for the current build; run under 3.14t to produce the numbers
published in ``docs/perf-notes.md``. The enforcing CI gate lives in
``benchmarks/test_pdes_scaling.py``; this module owns the workloads and
measurement helpers.

Two workloads:

* ``grid_topology`` — the sharded grid conveyor (row bands, transit time as
  lookahead): the roadmap's reference model for shard-count scaling.
* ``ring_topology`` — shards in a ring, each mixing local events (fixed
  spacing) with cross-ring messages at a *parameterized* lookahead: sweeping
  lookahead toward the event spacing produces the documented slowdown curve
  (lookahead -> 0 means horizons advance one event at a time).
"""

import sys
import time
from collections.abc import Generator
from typing import Any

from llmsim import Event, Resource, ShardedSim, ShardPorts, Sim
from llmsim.parallel.pdes import RunMode

MASTER_SEED = 20260712

_ROWS = 16
_COLS = 32
_ITEMS = 400
_SEGMENT_TRANSIT = 1.0
_ARRIVAL_MEAN = 1.5


def grid_topology(shards: int) -> ShardedSim:
    """The sharded grid conveyor sized for benchmarking.

    Unlike the Phase 1 L-route model, items traverse the grid in a
    *serpentine* (row 0 left-to-right, row 1 right-to-left, ...), so every
    row band carries the same number of cells and the shards are balanced --
    the regime PDES is for. Items pipeline through bands; the boundary
    crossing's transit time is the channel lookahead.
    """
    assert _ROWS % shards == 0
    band_height = _ROWS // shards
    topo = ShardedSim(shards, master_seed=MASTER_SEED)

    def band_route(shard_index: int) -> list[tuple[int, int]]:
        route: list[tuple[int, int]] = []
        for row in range(shard_index * band_height, (shard_index + 1) * band_height):
            cols = range(_COLS) if row % 2 == 0 else range(_COLS - 1, -1, -1)
            route.extend((row, col) for col in cols)
        return route

    def make_builder(shard_index: int) -> None:
        is_first = shard_index == 0
        is_last = shard_index == shards - 1
        route = band_route(shard_index)

        @topo.shard(shard_index)
        def build_band(sim: Sim, ports: ShardPorts) -> None:
            segments = {cell: Resource(sim, capacity=1) for cell in route}
            out = (
                None
                if is_last
                else ports.out(f"band_{shard_index}", lookahead=_SEGMENT_TRANSIT)
            )

            def walker(
                sim: Sim, item_id: int, entered_at: float
            ) -> Generator[Event[Any], Any, None]:
                for cell in route:
                    with segments[cell].request() as slot:
                        yield slot
                        yield sim.delay(_SEGMENT_TRANSIT)
                if out is not None:
                    out.send((item_id, entered_at), delay=_SEGMENT_TRANSIT)

            if is_first:

                def feeder(sim: Sim) -> Generator[Event[Any], Any, None]:
                    for item_id in range(_ITEMS):
                        yield sim.delay(sim.rng.expovariate(1.0 / _ARRIVAL_MEAN))
                        sim.spawn(walker, item_id, sim.now)

                sim.spawn(feeder)
            else:
                inbox = ports.inbox(f"band_{shard_index - 1}")

                def receiver(sim: Sim) -> Generator[Event[Any], Any, None]:
                    while True:
                        item_id, entered_at = yield inbox.get()
                        sim.spawn(walker, item_id, entered_at)

                sim.spawn(receiver)

    for shard_index in range(shards):
        make_builder(shard_index)
    return topo


def ring_topology(shards: int, *, lookahead: float, spacing: float) -> ShardedSim:
    """Shards in a ring: local work at *spacing*, ring messages at *lookahead*."""
    topo = ShardedSim(shards, master_seed=MASTER_SEED)

    def make_builder(shard_index: int) -> None:
        @topo.shard(shard_index)
        def build_node(sim: Sim, ports: ShardPorts) -> None:
            out = ports.out(f"ring_{shard_index}", lookahead=lookahead)
            inbox = ports.inbox(f"ring_{(shard_index - 1) % shards}")

            def local_work(sim: Sim) -> Generator[Event[Any], Any, None]:
                for _ in range(2_000):
                    yield sim.delay(spacing)

            def forwarder(sim: Sim) -> Generator[Event[Any], Any, None]:
                out.send(0, delay=lookahead)
                while True:
                    hops = yield inbox.get()
                    if sim.now >= 2_000 * spacing:
                        return
                    out.send(hops + 1, delay=lookahead)

            sim.spawn(local_work)
            sim.spawn(forwarder)

    for shard_index in range(shards):
        make_builder(shard_index)
    return topo


def timed_run(topo: ShardedSim, *, until: float, mode: RunMode) -> float:
    """Wall-clock one full run in the given mode."""
    start = time.perf_counter()
    topo.run(until, mode=mode)
    return time.perf_counter() - start


#: Long enough for all items to clear the serpentine (route ~512 cells +
#: arrival span + queueing).
GRID_UNTIL = 1_400.0


def main() -> None:
    """Print the shard-scaling and lookahead-degradation curves."""
    print(f"build={sys.version.split()[0]} gil={sys._is_gil_enabled()}")

    print("--- grid conveyor: shard scaling (lookahead = segment transit) ---")
    baseline = timed_run(grid_topology(1), until=GRID_UNTIL, mode="sequential")
    print(f"sequential reference: {baseline:.3f}s")
    for shards in (1, 2, 4, 8):
        elapsed = timed_run(grid_topology(shards), until=GRID_UNTIL, mode="threads")
        print(f"shards={shards}: {elapsed:.3f}s speedup={baseline / elapsed:.2f}x")

    spacing = 0.25
    print("--- ring: lookahead degradation (local spacing = 0.25) ---")
    ring_until = 2_000 * spacing
    ring_baseline = timed_run(
        ring_topology(4, lookahead=4 * spacing, spacing=spacing),
        until=ring_until,
        mode="sequential",
    )
    print(f"sequential reference (L=4x spacing): {ring_baseline:.3f}s")
    for ratio in (4.0, 2.0, 1.0, 0.5, 0.25):
        topo = ring_topology(4, lookahead=ratio * spacing, spacing=spacing)
        elapsed = timed_run(topo, until=ring_until, mode="threads")
        print(
            f"lookahead={ratio:g}x spacing: {elapsed:.3f}s "
            f"speedup={ring_baseline / elapsed:.2f}x"
        )


if __name__ == "__main__":
    main()
