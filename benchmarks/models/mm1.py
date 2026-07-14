"""M/M/1 queue: one server, Poisson arrivals, exponential service (SimPy 3)."""

import random

import simpy


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
    # --8<-- [start:setup]
    rng = random.Random(seed)
    env = simpy.Environment()
    server = simpy.Resource(env, capacity=1)
    total_wait = 0.0
    total_service = 0.0
    num_served = 0
    # --8<-- [end:setup]

    # --8<-- [start:customer]
    def customer() -> object:
        nonlocal total_wait, total_service, num_served
        arrived_at = env.now
        with server.request() as slot:
            yield slot
            total_wait += env.now - arrived_at
            service_time = rng.expovariate(service_rate)
            total_service += service_time
            num_served += 1
            yield env.timeout(service_time)
    # --8<-- [end:customer]

    # --8<-- [start:arrivals]
    def arrivals() -> object:
        for _ in range(num_customers):
            yield env.timeout(rng.expovariate(arrival_rate))
            env.process(customer())
    # --8<-- [end:arrivals]

    # --8<-- [start:run]
    env.process(arrivals())
    env.run()
    # --8<-- [end:run]

    return {
        "mean_wait": round(total_wait / num_served, 6),
        "utilization": round(total_service / env.now, 6),
        "num_served": float(num_served),
    }
