"""Machine shop: machines make parts, break down, and share repairers (SimPy 3).

Adapted from the classic SimPy machine-shop example: a pool of machines each
produce parts, fail at random intervals, and queue for a limited set of
repairers under a preemptive priority discipline.
"""

import random

import simpy

PART_TIME_MEAN = 10.0
PART_TIME_SIGMA = 2.0
MEAN_TIME_TO_FAILURE = 300.0
REPAIR_TIME = 30.0
SHOP_DURATION = 4000.0


def _time_per_part(rng: random.Random) -> float:
    """Return a strictly positive processing time for one part.

    Uses ``gauss`` (a fixed number of draws per call) rather than
    ``normalvariate`` (a rejection loop): a fixed draw count keeps the shared
    random stream from shifting wholesale if a libm rounding difference ever
    flips a rejection decision, which would otherwise make the recorded KPI
    fail exact-equality enforcement across otherwise-identical machines.
    """
    return max(0.1, rng.gauss(PART_TIME_MEAN, PART_TIME_SIGMA))


class _Machine:
    """A single machine that makes parts and occasionally breaks down."""

    def __init__(
        self,
        env: simpy.Environment,
        repairers: simpy.PreemptiveResource,
        rng: random.Random,
    ) -> None:
        self.env = env
        self.repairers = repairers
        self.rng = rng
        self.parts_made = 0
        self.broken = False
        self.process = env.process(self._work())
        env.process(self._break())

    def _work(self) -> object:
        while True:
            remaining = _time_per_part(self.rng)
            while remaining > 0:
                started = self.env.now
                try:
                    yield self.env.timeout(remaining)
                    remaining = 0.0
                    self.parts_made += 1
                except simpy.Interrupt:
                    self.broken = True
                    remaining -= self.env.now - started
                    with self.repairers.request(priority=1) as repair:
                        yield repair
                        yield self.env.timeout(REPAIR_TIME)
                    self.broken = False

    def _break(self) -> object:
        while True:
            yield self.env.timeout(self.rng.expovariate(1.0 / MEAN_TIME_TO_FAILURE))
            if not self.broken:
                self.process.interrupt()


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
    rng = random.Random(seed)
    env = simpy.Environment()
    repairers = simpy.PreemptiveResource(env, capacity=num_repairers)
    machines = [_Machine(env, repairers, rng) for _ in range(num_machines)]
    env.run(until=SHOP_DURATION)

    total_parts = sum(machine.parts_made for machine in machines)
    return {
        "parts_made": float(total_parts),
        "parts_per_machine": round(total_parts / num_machines, 6),
    }
