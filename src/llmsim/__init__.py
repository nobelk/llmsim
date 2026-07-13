"""llmsim: parallel discrete-event simulation for Python 3.14+.

This module is the public API surface. Symbols are re-exported here as each
engine capability lands in its roadmap phase. Phase 1 exposes the sequential
core: the :class:`Sim` event loop, the generic :class:`Event`, generator and
coroutine :class:`Process` support, condition composition, and the resource,
container, and store primitives.

A minimal simulation::

    import llmsim

    def customer(sim, bank, service_time):
        arrive = sim.now
        with bank.request() as slot:
            yield slot
            wait = sim.now - arrive
            yield sim.delay(service_time)

    sim = llmsim.Sim(seed=0)
    bank = llmsim.Resource(sim, capacity=2)
    sim.spawn(customer, bank, service_time=5.0)
    sim.run(until=100.0)
"""

from llmsim import rt
from llmsim.core.conditions import AllOf, AnyOf, Condition
from llmsim.core.errors import EmptySchedule, Interrupt, SimulationError
from llmsim.core.events import Event, Timeout
from llmsim.core.process import Process
from llmsim.core.sim import Sim
from llmsim.parallel.backends import (
    CancelToken,
    ExecutionBackend,
    FactoryValidationError,
    TransportError,
)
from llmsim.parallel.offload import (
    NonStrictOffloadWarning,
    OffloadEvent,
    OffloadPool,
)
from llmsim.parallel.pdes import (
    LookaheadError,
    ShardedSim,
    ShardError,
    ShardPorts,
    TopologyError,
)
from llmsim.parallel.replicate import (
    Experiment,
    ReplicationError,
    ReplicationResult,
    run_replications,
)
from llmsim.rand.streams import SeedStream, SeedTree
from llmsim.resources.container import Container
from llmsim.resources.resource import (
    PreemptiveResource,
    PriorityResource,
    Resource,
)
from llmsim.resources.store import FilterStore, PriorityStore, Store
from llmsim.rt import RealtimeDriftError

__all__ = [
    # Core engine.
    "Sim",
    "Event",
    "Timeout",
    "Process",
    # Errors.
    "Interrupt",
    "SimulationError",
    "EmptySchedule",
    # Condition composition.
    "Condition",
    "AllOf",
    "AnyOf",
    # Resources.
    "Resource",
    "PriorityResource",
    "PreemptiveResource",
    "Container",
    "Store",
    "PriorityStore",
    "FilterStore",
    # Parallel replications (Phase 2).
    "Experiment",
    "ReplicationResult",
    "ReplicationError",
    "run_replications",
    "ExecutionBackend",
    "CancelToken",
    "FactoryValidationError",
    "TransportError",
    # Deterministic randomness (Phase 2).
    "SeedTree",
    "SeedStream",
    # Single-run conservative PDES (Phase 3).
    "ShardedSim",
    "ShardPorts",
    "ShardError",
    "TopologyError",
    "LookaheadError",
    # Compute offload (Phase 4).
    "OffloadPool",
    "OffloadEvent",
    "NonStrictOffloadWarning",
    # Real-time mode (Phase 4).
    "rt",
    "RealtimeDriftError",
]
