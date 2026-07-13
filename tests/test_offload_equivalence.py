"""Offload trace equivalence: adversarial ties and latency jitter (4.1)."""

from collections.abc import Callable
from typing import Any

import pytest

from llmsim import OffloadPool, Sim
from llmsim.parallel.backends import BackendName
from llmsim.parallel.offload import OffloadBackendName
from llmsim.trace import TraceRecord, trace
from tests.parallel_support import (
    OFFLOAD_WORKER_COUNTS,
    POOLED_BACKENDS,
    Gen,
    offload_jitter_square,
    offload_square,
)

_MASTER = 20260712


def run_adversarial_model(
    backend: OffloadBackendName,
    max_workers: int | None,
    payload: Callable[[float], float],
) -> list[TraceRecord]:
    """Pile events onto one ``(time, priority)`` and return the trace.

    Everything interesting happens at t=5: an offload slot submitted at t=0,
    two slots submitted at t=2, plain timeouts from two processes, a
    zero-delay timeout scheduled *at* t=5, and a condition joining two of the
    offloads. Only the deterministic ``eid`` tie-breaker orders them, so any
    completion-order leak diverges the trace immediately.
    """
    sim = Sim(seed=_MASTER)
    outcomes: list[tuple[str, float, Any]] = []

    def early_submitter(sim: Sim) -> Gen:
        slot_event = sim.offload(payload, 2.0, delay=5.0)
        yield sim.delay(5.0)
        value = yield slot_event
        outcomes.append(("early", sim.now, value))

    def late_submitter(sim: Sim) -> Gen:
        yield sim.delay(2.0)
        first = sim.offload(payload, 3.0, delay=3.0)
        second = sim.offload(payload, 4.0, delay=3.0)
        both = yield first & second
        outcomes.append(("late", sim.now, tuple(both.values())))

    def bystander(sim: Sim) -> Gen:
        yield sim.delay(5.0)
        yield sim.delay(0.0)
        outcomes.append(("bystander", sim.now, None))

    with OffloadPool(sim, backend=backend, max_workers=max_workers):
        tracer = trace(sim)
        sim.spawn(early_submitter)
        sim.spawn(late_submitter)
        sim.spawn(bystander)
        sim.run()

    assert sorted((name, when) for name, when, _ in outcomes) == [
        ("bystander", 5.0),
        ("early", 5.0),
        ("late", 5.0),
    ]
    return tracer.records


@pytest.fixture(scope="module")
def adversarial_reference() -> list[TraceRecord]:
    """The inline sequential trace of the adversarial tie model."""
    return run_adversarial_model("inline", None, offload_square)


class TestAdversarialTies:
    """Slot events tied with local events keep the sequential order."""

    @pytest.mark.parametrize("backend", POOLED_BACKENDS)
    @pytest.mark.parametrize("max_workers", OFFLOAD_WORKER_COUNTS)
    def test_ties_are_bitwise_stable_on_every_backend_and_worker_count(
        self,
        backend: BackendName,
        max_workers: int,
        adversarial_reference: list[TraceRecord],
    ) -> None:
        records = run_adversarial_model(backend, max_workers, offload_square)
        assert records == adversarial_reference, (
            f"{backend}@{max_workers} diverged from the sequential reference"
        )


class TestLatencyJitter:
    """Randomized worker latency never changes the strict-mode trace."""

    @pytest.mark.parametrize("backend", POOLED_BACKENDS)
    def test_jittered_payload_trace_equals_plain_reference(
        self, backend: BackendName, adversarial_reference: list[TraceRecord]
    ) -> None:
        records = run_adversarial_model(backend, 4, offload_jitter_square)
        assert records == adversarial_reference, (
            f"wall-clock jitter leaked into the {backend} trace"
        )

    def test_repeated_runs_are_bitwise_identical(self) -> None:
        first = run_adversarial_model("threads", 2, offload_jitter_square)
        second = run_adversarial_model("threads", 2, offload_jitter_square)
        assert first == second
