"""Strict-mode ``sim.offload`` scoring showcase (roadmap 5.4b).

The Phase 4 showcase: the agentic model's per-think-step **routing score** is a
CPU-heavy pure function (:func:`~examples.agentic_workflow.policies.score_request`)
evaluated on the offload worker pool via ``sim.offload(..., strict=True)``. In
strict mode the result is delivered at a *deterministic* completion slot
(``now + SCORING_SLOT``) regardless of which backend actually computes it, so the
run is bitwise-identical whether the pool is ``"inline"`` (the reference) or a
real worker pool -- the property the trace-equivalence test asserts.

Wall-clock worker latency never leaks into the simulated trace; that is strict
mode's core promise (``specs/roadmap.md`` 4.1).
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from examples.agentic_workflow.kpis import AgenticConfig, AgenticKPIs
from examples.agentic_workflow.model import _simulate
from examples.agentic_workflow.policies import score_request
from llmsim import Event, OffloadPool, Sim
from llmsim.parallel.offload import OffloadBackendName
from llmsim.rand.streams import SeedStream
from llmsim.trace import TraceRecord, trace

#: Strict-mode completion slot for each offloaded score. Fixed and positive, so
#: the score is delivered at a deterministic time on every backend.
SCORING_SLOT = 0.1


def _offloaded_scorer(
    sim: Sim, token_length: int, task_id: int, step: int
) -> Generator[Event[Any], Any, float]:
    """Score a think step on the worker pool, delivered at a strict slot."""
    score: float = yield sim.offload(
        score_request, token_length, task_id, step, delay=SCORING_SLOT, strict=True
    )
    return score


def _run(sim: Sim, config: AgenticConfig, backend: OffloadBackendName) -> AgenticKPIs:
    """Run the agentic model with the offloaded scorer on *backend*."""
    with OffloadPool(sim, backend=backend):
        return _simulate(sim, config, scorer=_offloaded_scorer)


def run_agentic_offload(stream: SeedStream, config: AgenticConfig) -> AgenticKPIs:
    """Run the offloaded-scoring model from a seed stream (the factory).

    Uses the ``"inline"`` pool -- the deterministic reference, and the resolution
    ``"auto"`` takes inside an ``Experiment`` worker (the nested-pool rule) -- so
    it is a drop-in ``Experiment`` factory.

    Args:
        stream: The replication's seed stream; ``stream.rng()`` seeds the run.
        config: The scenario to simulate.

    Returns:
        The run's headline KPIs.
    """
    return _run(Sim(rng=stream.rng()), config, "inline")


def run_offload_showcase(
    seed: int, config: AgenticConfig, *, backend: OffloadBackendName = "inline"
) -> AgenticKPIs:
    """Run the offloaded-scoring model from a bare seed on a chosen backend."""
    return _run(Sim(seed=seed), config, backend)


def run_offload_traced(
    seed: int, config: AgenticConfig, *, backend: OffloadBackendName
) -> tuple[AgenticKPIs, list[TraceRecord]]:
    """Run the offloaded model, returning its KPIs and full event trace.

    The trace-equivalence test runs this on ``"inline"`` and on a real worker
    pool and asserts the records are bitwise-identical.
    """
    sim = Sim(seed=seed)
    with OffloadPool(sim, backend=backend):
        tracer = trace(sim)
        kpis = _simulate(sim, config, scorer=_offloaded_scorer)
    return kpis, tracer.records
