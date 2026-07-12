"""The replication-scaling workload.

A module-level factory (importable by every backend's workers) running an
M/M/1 queue sized so per-replication simulation work dominates pool and
transport coordination -- the regime parallel replications are for.
"""

from collections.abc import Generator
from math import log as _log
from typing import Any

from llmsim import Event, Resource, Sim
from llmsim.rand.streams import SeedStream

#: Fixed study seed; the scaling numbers are timing-only, but the results
#: stay reproducible so the harness can cross-check determinism cheaply.
MASTER_SEED = 20260712

#: One config: ~6000 customers puts a replication around ~20ms, so a
#: 64-replication study runs seconds sequentially -- long enough to amortize
#: worker startup and transport, short enough for a per-PR CI gate.
CONFIG = {"arrival_rate": 0.9, "service_rate": 1.0, "customers": 6000}


def mm1_replication(stream: SeedStream, config: dict[str, float]) -> dict[str, float]:
    """Run one M/M/1 replication and return its KPIs.

    Exponential draws are computed as ``-log(1 - u) / rate`` from
    ``rng.random()`` with *locally bound* ``log``, rates, and constants --
    numerically identical to ``rng.expovariate(rate)`` (same formula, same
    underlying draws), but free of the shared-object reference-count
    contention that makes ``random.py``'s pure-Python distribution methods
    anti-scale across threads on the free-threaded build (measured 0.37x at
    8 workers; see docs/perf-notes.md). Model authors targeting the thread
    backend should draw the same way.
    """
    sim = Sim(rng=stream.rng())
    draw = sim.rng.random
    log = _log
    # Multiplying shared config floats at runtime mints thread-local float
    # objects for the hot loop below (a literal like 1.0 * 1.0 would be
    # constant-folded back into a shared code-object constant).
    arrival_rate = config["arrival_rate"] * 1.0
    service_rate = config["service_rate"] * 1.0
    one = arrival_rate * 0.0 + 1.0
    customers = int(config["customers"])

    server = Resource(sim, capacity=1)
    waits: list[float] = []

    def customer(sim: Sim) -> Generator[Event[Any], Any, None]:
        arrived = sim.now
        with server.request() as slot:
            yield slot
            waits.append(sim.now - arrived)
            yield sim.delay(-log(one - draw()) / service_rate)

    def source(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(customers):
            yield sim.delay(-log(one - draw()) / arrival_rate)
            sim.spawn(customer)

    sim.spawn(source)
    sim.run()
    return {
        "mean_wait": round(sum(waits) / len(waits), 9),
        "served": float(len(waits)),
        "makespan": round(sim.now, 9),
    }
