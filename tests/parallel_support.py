"""Module-level factories for the parallel test suites.

Execution backends transport work as (importable callable, seed spec, config)
references, so every factory used by the backend/replication tests must live
at module level in an importable module. Process and interpreter workers
import this module by name (``tests.parallel_support``); the repo root is on
``sys.path`` via pytest's ``pythonpath`` and propagates to spawned workers.
"""

import threading
import time
from collections.abc import Generator
from typing import Any

from llmsim.core.events import Event
from llmsim.core.sim import Sim
from llmsim.parallel.backends import CancelToken
from llmsim.rand.streams import SeedStream


def sequential_reference(
    factory: Any,
    configs: list[dict[str, float]],
    replications: int,
    master_seed: int,
) -> dict[tuple[int, int], Any]:
    """Run a study in-process, one replication at a time, in key order.

    The reproducibility oracle every parallel test compares against; keep it
    the single source of truth for what "the sequential reference" means.
    """
    from llmsim.rand.streams import SeedTree

    tree = SeedTree(master_seed)
    return {
        (config_index, replication_index): factory(
            tree.stream(config_index, replication_index), config
        )
        for config_index, config in enumerate(configs)
        for replication_index in range(replications)
    }


def trivial_task(stream: SeedStream, config: Any) -> tuple[int, int, float]:
    """Return the identity triple plus the stream's first draw."""
    return (stream.config_index, stream.replication_index, stream.rng().random())


def echo_config(stream: SeedStream, config: Any) -> Any:
    """Return the config unchanged (round-trip transport check)."""
    return config


def unpicklable_result(stream: SeedStream, config: Any) -> Any:
    """Return a value that cannot cross a pickle boundary."""
    return lambda: None


def failing_factory(stream: SeedStream, config: Any) -> Any:
    """Raise a model error to exercise the fail-fast contract."""
    raise ValueError(f"model blew up at config {stream.config_index}")


def mm1_kpis(stream: SeedStream, config: dict[str, float]) -> dict[str, float]:
    """Run a small M/M/1 queue and return its KPIs (canonical model).

    A deterministic function of the stream: same seed, same KPIs, on any
    backend, worker count, or build.
    """
    sim = Sim(rng=stream.rng())
    rng = sim.rng
    arrival_rate = config.get("arrival_rate", 0.9)
    service_rate = config.get("service_rate", 1.0)
    customers = int(config.get("customers", 200))

    from llmsim.resources.resource import Resource

    server = Resource(sim, capacity=1)
    waits: list[float] = []

    def customer(sim: Sim) -> Generator[Event[Any], Any, None]:
        arrived = sim.now
        with server.request() as slot:
            yield slot
            waits.append(sim.now - arrived)
            yield sim.delay(rng.expovariate(service_rate))

    def source(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(customers):
            yield sim.delay(rng.expovariate(arrival_rate))
            sim.spawn(customer)

    sim.spawn(source)
    sim.run()
    return {
        "mean_wait": round(sum(waits) / len(waits), 9),
        "served": float(len(waits)),
        "makespan": round(sim.now, 9),
    }


def store_throughput(stream: SeedStream, config: dict[str, float]) -> dict[str, float]:
    """Run a producer/consumer pipeline through a Store (canonical model)."""
    sim = Sim(rng=stream.rng())
    rng = sim.rng
    items = int(config.get("items", 50))

    from llmsim.resources.store import Store

    buffer: Store[float] = Store(sim, capacity=5)
    consumed: list[float] = []

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(items):
            yield sim.delay(rng.expovariate(2.0))
            yield buffer.put(round(rng.random(), 9))

    def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
        while len(consumed) < items:
            item = yield buffer.get()
            consumed.append(item)
            yield sim.delay(rng.expovariate(1.5))

    sim.spawn(producer)
    sim.spawn(consumer)
    sim.run()
    return {
        "checksum": round(sum(consumed), 9),
        "count": float(len(consumed)),
        "makespan": round(sim.now, 9),
    }


#: Set by :func:`cooperative_factory` the moment it starts stepping, so a test
#: can cancel strictly *mid-replication* instead of racing a wall-clock timer
#: against lazy generator startup. Thread-backend only (shared memory).
cooperative_started = threading.Event()


def cooperative_factory(
    stream: SeedStream, config: Any, cancel: CancelToken
) -> dict[str, float]:
    """Consult the cancellation handle between ``step()`` calls.

    The cooperative-cancellation contract: a handle-aware factory checks the
    token between steps and stops mid-replication when it fires. Signals
    :data:`cooperative_started` once stepping begins and paces each step so
    the run comfortably outlives any cancel latency on a slow runner.
    """
    sim = Sim(rng=stream.rng())
    for _ in range(10_000):
        sim.delay(1.0)
    steps = 0
    cooperative_started.set()
    while sim.peek() != float("inf"):
        if cancel.cancelled:
            break
        sim.step()
        steps += 1
        time.sleep(0.0005)  # ~5s uncancelled worst case; ~ms cancel response
    return {"steps": float(steps), "cancelled": float(cancel.cancelled)}


#: Per-worker call counter proving warm-pool reuse: a reused interpreter (or
#: process) keeps this module's state across replications, so successive calls
#: in one worker see 1, 2, 3, ...
_calls_in_this_worker = 0


def counting_factory(stream: SeedStream, config: Any) -> int:
    """Return how many replications this worker has run so far."""
    global _calls_in_this_worker
    _calls_in_this_worker += 1
    return _calls_in_this_worker


def large_payload_factory(stream: SeedStream, config: Any) -> dict[str, list[float]]:
    """Return a payload big enough for spooling to matter."""
    rng = stream.rng()
    return {"draws": [rng.random() for _ in range(2_000)]}


def slow_uncooperative_factory(stream: SeedStream, config: Any) -> dict[str, float]:
    """Own the whole ``sim.run()`` without consulting any handle."""
    sim = Sim(rng=stream.rng())
    for tick in range(1, 101):
        sim.delay(float(tick))  # a ladder of events out to t=100
    time.sleep(0.05)
    sim.run()
    return {"now": sim.now}
