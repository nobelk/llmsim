"""M/M/1 queue on llmsim: one server, Poisson arrivals, exponential service.

A one-for-one port of ``benchmarks/models/mm1.py`` (SimPy 3) to the llmsim API.
"""

from collections.abc import Generator
from typing import Any

from llmsim import Event, Resource, Sim


def run_mm1(
    seed: int,
    arrival_rate: float = 0.9,
    service_rate: float = 1.0,
    num_customers: int = 2000,
) -> dict[str, float]:
    """Simulate an M/M/1 queue and return its steady-state KPIs.

    Args:
        seed: Master seed for the single shared random stream.
        arrival_rate: Mean arrival rate (lambda) of the Poisson process.
        service_rate: Mean service rate (mu) of the exponential server.
        num_customers: Number of customers to route through the queue.

    Returns:
        Mapping with ``mean_wait`` (mean time in queue), ``utilization``
        (fraction of time the server was busy), and ``num_served``.
    """
    sim = Sim(seed=seed)
    rng = sim.rng
    server = Resource(sim, capacity=1)
    total_wait = 0.0
    total_service = 0.0
    num_served = 0

    def customer(sim: Sim) -> Generator[Event[Any], Any, None]:
        nonlocal total_wait, total_service, num_served
        arrived_at = sim.now
        with server.request() as slot:
            yield slot
            total_wait += sim.now - arrived_at
            service_time = rng.expovariate(service_rate)
            total_service += service_time
            num_served += 1
            yield sim.delay(service_time)

    def arrivals(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(num_customers):
            yield sim.delay(rng.expovariate(arrival_rate))
            sim.spawn(customer)

    sim.spawn(arrivals)
    sim.run()

    return {
        "mean_wait": round(total_wait / num_served, 6),
        "utilization": round(total_service / sim.now, 6),
        "num_served": float(num_served),
    }
