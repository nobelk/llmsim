"""LLM agentic workflow -- the core sequential model (roadmap 5.3).

A *simulation of* an LLM-serving system: tasks arrive at an orchestrator, and
each becomes an agent process that alternates **think** steps (inference requests
queued at shared, batching LLM-server ``Resource``s with token-length-dependent
service times) and **act** steps (tool calls with stochastic latency, failures,
and bounded retries). There is never a real LLM or network call -- every service
time is drawn from ``sim.rng`` (``specs/mission.md`` §Out of scope; the no-network
rule is enforced by test).

Bounded agent concurrency is a finite-capacity ``Resource``; the shared inference
queue is a ``Store`` that batching servers drain. A ``scorer`` seam lets the
offload showcase (roadmap 5.4b) insert a CPU-heavy routing score through
``sim.offload`` without duplicating the model; the core model leaves it unset.

Everything stochastic draws from ``sim.rng``, so the run is a deterministic
function of ``(seed, config)``.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from examples.agentic_workflow.kpis import (
    AgenticAccumulator,
    AgenticConfig,
    AgenticKPIs,
)
from llmsim import Event, Resource, Sim, Store
from llmsim.rand.streams import SeedStream

#: A think-step scoring hook: given ``(sim, token_length, task_id, step)`` it
#: yields (e.g. an offload event) and returns a routing score. The core model
#: leaves this ``None``; the offload showcase supplies an offloaded scorer.
Scorer = Callable[[Sim, int, int, int], Generator[Event[Any], Any, float]]


class _InferenceRequest:
    """One queued inference request: its token length and completion handle."""

    __slots__ = ("token_length", "done", "key")

    def __init__(
        self, token_length: int, done: Event[Any], key: tuple[int, int]
    ) -> None:
        self.token_length = token_length
        #: Resolved by a server when the request's batch finishes.
        self.done = done
        #: ``(task_id, step)`` -- a stable identity unique within a run, so a
        #: traced payload compares equal across two runs (the basis of the
        #: offload trace-equivalence test).
        self.key = key

    def __eq__(self, other: object) -> bool:
        """Equal iff the ``(task_id, step)`` keys match."""
        return isinstance(other, _InferenceRequest) and other.key == self.key

    def __hash__(self) -> int:
        """Hash by the stable ``(task_id, step)`` key."""
        return hash(self.key)


class _Task:
    """One task: its identity and arrival time."""

    __slots__ = ("task_id", "created")

    def __init__(self, task_id: int, created: float) -> None:
        self.task_id = task_id
        self.created = created


class _World:
    """Shared, single-thread simulation state for one agentic-workflow run."""

    __slots__ = ("config", "inference_queue", "agent_slots", "accumulator", "scorer")

    def __init__(self, sim: Sim, config: AgenticConfig, scorer: Scorer | None) -> None:
        self.config = config
        self.inference_queue: Store[_InferenceRequest] = Store(sim)
        self.agent_slots = Resource(sim, capacity=config.agent_concurrency)
        self.accumulator = AgenticAccumulator()
        self.scorer = scorer


def _server(sim: Sim, world: _World) -> Generator[Event[Any], Any, None]:
    """Drain the shared inference queue, serving deterministic token batches."""
    queue = world.inference_queue
    config = world.config
    while True:
        batch: list[_InferenceRequest] = [(yield queue.get())]
        # Greedily absorb whatever is already buffered, up to the batch size.
        # Under load the queue backs up and batches grow; under light load a
        # batch is just the one request -- both deterministically.
        while len(batch) < config.batch_size and queue.items:
            batch.append((yield queue.get()))
        longest = max(request.token_length for request in batch)
        service = config.inference_base + config.inference_per_token * longest
        yield sim.delay(service)
        world.accumulator.record_batch(len(batch))
        for request in batch:
            request.done.succeed(service)


def _act(sim: Sim, world: _World) -> Generator[Event[Any], Any, tuple[float, bool]]:
    """Run one tool call with bounded retries; return ``(cost, succeeded)``.

    A failing call retries up to ``max_retries`` times, then surfaces the
    failure to the caller (which aborts the task).
    """
    config = world.config
    rng = sim.rng
    cost = 0.0
    for _attempt in range(config.max_retries + 1):
        yield sim.delay(rng.expovariate(1.0 / config.tool_latency_mean))
        cost += config.tool_cost
        if rng.random() >= config.tool_failure_prob:
            return cost, True
    return cost, False


def _agent(sim: Sim, world: _World, task: _Task) -> Generator[Event[Any], Any, None]:
    """Run one task's think/act loop under the bounded agent-concurrency pool."""
    config = world.config
    rng = sim.rng
    with world.agent_slots.request() as slot:
        yield slot
        cost = 0.0
        failed = False
        for step in range(config.steps_per_task):
            tokens = rng.randint(config.min_tokens, config.max_tokens)
            if world.scorer is not None:
                cost += yield from world.scorer(sim, tokens, task.task_id, step)
            request = _InferenceRequest(tokens, sim.event(), (task.task_id, step))
            yield world.inference_queue.put(request)
            world.accumulator.record_enqueue(len(world.inference_queue.items))
            yield request.done
            cost += config.token_cost * tokens
            act_cost, succeeded = yield from _act(sim, world)
            cost += act_cost
            if not succeeded:
                failed = True
                break
    world.accumulator.record_task(sim.now - task.created, round(cost, 9), failed=failed)


def _task_source(sim: Sim, world: _World) -> Generator[Event[Any], Any, None]:
    """Generate Poisson task arrivals until the horizon."""
    config = world.config
    rng = sim.rng
    task_id = 0
    while True:
        yield sim.delay(rng.expovariate(config.arrival_rate))
        if sim.now >= config.duration:
            return
        sim.spawn(_agent, world, _Task(task_id, sim.now))
        task_id += 1


def _simulate(
    sim: Sim, config: AgenticConfig, scorer: Scorer | None = None
) -> AgenticKPIs:
    """Build and run one agentic-workflow simulation, returning its KPIs."""
    world = _World(sim, config, scorer)
    for _ in range(config.num_servers):
        sim.spawn(_server, world)
    sim.spawn(_task_source, world)
    sim.run(until=config.duration)
    return world.accumulator.finalize(makespan=sim.now)


def run_agentic_workflow(stream: SeedStream, config: AgenticConfig) -> AgenticKPIs:
    """Run the agentic-workflow model from a replication seed stream (the factory).

    Importable and closure-free so ``Experiment`` can submit it to any backend
    as an ``(importable callable, seed spec, config)`` reference
    (``specs/tech-stack.md`` §5).

    Args:
        stream: The replication's seed stream; ``stream.rng()`` seeds the run.
        config: The scenario to simulate.

    Returns:
        The run's headline KPIs.
    """
    return _simulate(Sim(rng=stream.rng()), config)


def run_sequential(seed: int, config: AgenticConfig) -> AgenticKPIs:
    """Run the agentic-workflow model from a bare integer seed.

    The single-run entry point (behavioral tests, the offload reference oracle):
    same seed and config give identical KPIs on any build.

    Args:
        seed: Master seed for the run's single random stream.
        config: The scenario to simulate.

    Returns:
        The run's headline KPIs.
    """
    return _simulate(Sim(seed=seed), config)
