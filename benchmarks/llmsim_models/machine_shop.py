"""Machine shop on llmsim: machines make parts, break down, share repairers.

A one-for-one port of ``benchmarks/models/machine_shop.py`` (SimPy 3) to the
llmsim API, including the preemptive-priority repair discipline.
"""

import random
from collections.abc import Generator
from typing import Any

from llmsim import Event, Interrupt, PreemptiveResource, Sim

PART_TIME_MEAN = 10.0
PART_TIME_SIGMA = 2.0
MEAN_TIME_TO_FAILURE = 300.0
REPAIR_TIME = 30.0
SHOP_DURATION = 4000.0


def _time_per_part(rng: random.Random) -> float:
    """Return a strictly positive processing time for one part.

    Uses ``gauss`` (a fixed number of draws per call) rather than
    ``normalvariate`` (a rejection loop) so the shared random stream cannot shift
    wholesale if a libm rounding difference ever flips a rejection decision --
    the same rationale as the SimPy 3 reference model.
    """
    return max(0.1, rng.gauss(PART_TIME_MEAN, PART_TIME_SIGMA))


class _Machine:
    """A single machine that makes parts and occasionally breaks down."""

    # --8<-- [start:init]
    def __init__(
        self, sim: Sim, repairers: PreemptiveResource, rng: random.Random
    ) -> None:
        self.sim = sim
        self.repairers = repairers
        self.rng = rng
        self.parts_made = 0
        self.broken = False
        self.process = sim.spawn(self._work)
        sim.spawn(self._break)
    # --8<-- [end:init]

    # --8<-- [start:work]
    def _work(self, sim: Sim) -> Generator[Event[Any], Any, None]:
        while True:
            remaining = _time_per_part(self.rng)
            while remaining > 0:
                started = self.sim.now
                try:
                    yield self.sim.delay(remaining)
                    remaining = 0.0
                    self.parts_made += 1
                except Interrupt:
                    self.broken = True
                    remaining -= self.sim.now - started
                    with self.repairers.request(priority=1) as repair:
                        yield repair
                        yield self.sim.delay(REPAIR_TIME)
                    self.broken = False
    # --8<-- [end:work]

    # --8<-- [start:break]
    def _break(self, sim: Sim) -> Generator[Event[Any], Any, None]:
        while True:
            yield self.sim.delay(self.rng.expovariate(1.0 / MEAN_TIME_TO_FAILURE))
            if not self.broken:
                self.process.interrupt()
    # --8<-- [end:break]


def run_machine_shop(
    seed: int,
    num_machines: int = 10,
    num_repairers: int = 2,
) -> dict[str, float]:
    """Simulate the machine shop and return production KPIs.

    Args:
        seed: Master seed for the single shared random stream.
        num_machines: Number of part-producing machines.
        num_repairers: Number of shared, preemptable repairers.

    Returns:
        Mapping with ``parts_made`` (total across all machines) and
        ``parts_per_machine`` (the per-machine mean).
    """
    # --8<-- [start:run]
    sim = Sim(seed=seed)
    rng = sim.rng
    repairers = PreemptiveResource(sim, capacity=num_repairers)
    machines = [_Machine(sim, repairers, rng) for _ in range(num_machines)]
    sim.run(until=SHOP_DURATION)
    # --8<-- [end:run]

    total_parts = sum(machine.parts_made for machine in machines)
    return {
        "parts_made": float(total_parts),
        "parts_per_machine": round(total_parts / num_machines, 6),
    }
