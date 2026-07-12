"""Ported from SimPy 3's ``tests/test_environment.py`` (adapted to llmsim)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim import Event, Sim

Proc = Generator[Any, Any, Any]


def test_event_queue_empty(sim: Sim, log: list[Any]) -> None:
    """The simulation stops once no events remain, before ``until``."""

    def pem(sim: Sim, log: list[Any]) -> Proc:
        while sim.now < 2:
            log.append(sim.now)
            yield sim.delay(1)

    sim.spawn(pem, log)
    sim.run(10)
    assert log == [0, 1]


def test_run_negative_until(sim: Sim) -> None:
    """A run-until time must be in the future."""
    with pytest.raises(
        ValueError, match="must be greater than the current simulation time"
    ):
        sim.run(-3)


def test_run_resume(sim: Sim) -> None:
    """A stopped simulation can be resumed with a later ``until``."""
    events = [sim.delay(t) for t in (5, 10, 15)]

    assert sim.now == 0
    assert not any(event.processed for event in events)

    sim.run(until=10)
    assert sim.now == 10
    assert all(event.processed for event in events[:1])
    assert not any(event.processed for event in events[1:])

    sim.run(until=15)
    assert sim.now == 15
    assert all(event.processed for event in events[:2])
    assert not any(event.processed for event in events[2:])

    sim.run()
    assert sim.now == 15
    assert all(event.processed for event in events)


def test_run_until_value(sim: Sim) -> None:
    """Anything convertible to a float is a valid ``until`` time."""
    # ``run`` coerces its time via ``float(until)``, so a float-convertible
    # string works at runtime though the typed API advertises only numbers.
    sim.run(until="3.141592")  # type: ignore[arg-type]
    assert sim.now == 3.141592


def test_run_with_processed_event(sim: Sim) -> None:
    """An already-processed event passed as ``until`` returns its value."""
    timeout = sim.delay(1, value="spam")
    assert sim.run(until=timeout) == "spam"
    assert sim.now == 1
    assert sim.run(until=timeout) == "spam"
    assert sim.now == 1


def test_run_with_untriggered_event(sim: Sim) -> None:
    """An ``until`` event that can never trigger raises."""
    with pytest.raises(RuntimeError) as excinfo:
        sim.run(until=sim.event())
    assert 'the "until" event was not triggered' in str(excinfo.value)


def test_run_all_until_callbacks(sim: Sim) -> None:
    """A run stops the instant the ``until`` event is triggered.

    The simulation halts when the ``until`` event is *triggered* -- as its
    callbacks are about to be invoked -- so the consumer processes waiting on
    that same event have not yet observed it when ``run`` returns. This matches
    SimPy 3's behavior exactly (a newer SimPy 4 changed it); the spec pins the
    SimPy 3 contract, so the counters remain at 0 across every resumption.
    """

    class System:
        def __init__(self, sim: Sim) -> None:
            self.sim = sim
            self.counter = 0
            self.periodic_event: Event[Any] = sim.event()

        def periodic(self) -> Proc:
            for _ in range(3):
                yield self.sim.delay(1)
                event, self.periodic_event = self.periodic_event, self.sim.event()
                event.succeed(self.counter)

        def consumer(self) -> Proc:
            while True:
                yield self.periodic_event
                self.counter += 1

    system = System(sim)
    sim.spawn(system.periodic())
    for _ in range(5):
        sim.spawn(system.consumer())

    for expected_now in (1, 2, 3):
        period_counter = sim.run(until=system.periodic_event)
        assert sim.now == expected_now
        assert period_counter == 0
        assert system.counter == 0

    sim.run()
    assert sim.now == 3
    assert system.counter == 0
