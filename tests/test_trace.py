"""Structured tracing: deterministic, stable, zero records when off (G9)."""

from collections.abc import Generator
from typing import Any

from llmsim.core.events import Event
from llmsim.core.sim import Sim
from llmsim.trace import TraceRecord, disable_trace, trace


def _model(sim: Sim) -> Generator[Event[Any], Any, None]:
    for step in range(5):
        yield sim.delay(1.0, value=step)


def test_trace_disabled_by_default_emits_no_records() -> None:
    sim = Sim()
    assert sim._trace is None
    sim.spawn(_model)
    sim.run()  # no tracer attached, nothing recorded, no crash


def test_trace_records_processed_events() -> None:
    sim = Sim()
    tracer = trace(sim)
    sim.spawn(_model)
    sim.run()
    assert isinstance(tracer.records[0], TraceRecord)
    # Every Timeout carrying a step value is recorded in processing order.
    timeout_payloads = [
        record.payload for record in tracer.records if record.kind == "Timeout"
    ]
    assert timeout_payloads == [0, 1, 2, 3, 4]


def test_trace_is_deterministic_across_runs() -> None:
    first = Sim()
    first_tracer = trace(first)
    first.spawn(_model)
    first.run()

    second = Sim()
    second_tracer = trace(second)
    second.spawn(_model)
    second.run()

    assert first_tracer.records == second_tracer.records


def _condition_model(sim: Sim) -> Generator[Event[Any], Any, None]:
    # Exercises a ConditionValue payload, whose members carry per-run Event
    # identity -- the canonicalized trace must still be equal across runs.
    for _ in range(3):
        first = sim.delay(1.0, value="a")
        second = sim.delay(2.0, value="b")
        yield first & second


def test_trace_of_a_condition_model_is_stable_across_runs() -> None:
    first = Sim()
    first_tracer = trace(first)
    first.spawn(_condition_model)
    first.run()

    second = Sim()
    second_tracer = trace(second)
    second.spawn(_condition_model)
    second.run()

    assert first_tracer.records == second_tracer.records
    # The condition payloads were canonicalized to their member values, not the
    # per-run Event objects.
    condition_payloads = [
        record.payload for record in first_tracer.records if record.kind == "Condition"
    ]
    assert condition_payloads == [("a", "b"), ("a", "b"), ("a", "b")]


def test_disable_trace_restores_default_path() -> None:
    sim = Sim()
    tracer = trace(sim)
    disable_trace(sim)
    assert sim._trace is None
    sim.spawn(_model)
    sim.run()
    assert tracer.records == []


def test_tracer_clear() -> None:
    sim = Sim()
    tracer = trace(sim)
    sim.spawn(_model)
    sim.run()
    assert tracer.records
    tracer.clear()
    assert tracer.records == []
