"""Event loop: ordering, peek/step, run(until=...), EmptySchedule (G2)."""

from collections.abc import Callable

import pytest

from llmsim.core.errors import EmptySchedule
from llmsim.core.events import NORMAL, URGENT, Event
from llmsim.core.sim import INFINITY, Sim


def _ready(sim: Sim, callback: Callable[[Event[object]], None]) -> Event[object]:
    """Return a successful, callback-bearing event for low-level loop tests."""
    event: Event[object] = Event(sim)
    event._ok = True
    event._value = None
    assert event.callbacks is not None
    event.callbacks.append(callback)
    return event


def _append(bucket: list[object], value: object) -> Callable[[Event[object]], None]:
    """Build a callback that records *value* into *bucket* when fired."""

    def callback(_event: Event[object]) -> None:
        bucket.append(value)

    return callback


def test_now_starts_at_initial_time() -> None:
    assert Sim().now == 0
    assert Sim(initial_time=100.0).now == 100.0


def test_peek_returns_infinity_when_empty() -> None:
    assert Sim().peek() == INFINITY


def test_events_process_in_time_order() -> None:
    sim = Sim()
    fired: list[object] = []
    for at in (3.0, 1.0, 2.0):
        sim.schedule(_ready(sim, _append(fired, at)), NORMAL, at)
    sim.run()
    assert fired == [1.0, 2.0, 3.0]


def test_eid_breaks_equal_time_and_priority_ties_by_insertion() -> None:
    sim = Sim()
    fired: list[object] = []
    for index in range(5):
        sim.schedule(_ready(sim, _append(fired, index)), NORMAL, 0)
    sim.run()
    assert fired == [0, 1, 2, 3, 4]


def test_priority_orders_within_the_same_time() -> None:
    sim = Sim()
    fired: list[object] = []
    sim.schedule(_ready(sim, _append(fired, "normal")), NORMAL, 0)
    sim.schedule(_ready(sim, _append(fired, "urgent")), URGENT, 0)
    sim.run()
    assert fired == ["urgent", "normal"]


def test_step_processes_one_event() -> None:
    sim = Sim()
    sim.delay(1.0)
    sim.delay(2.0)
    sim.step()
    assert sim.now == 1.0
    sim.step()
    assert sim.now == 2.0


def test_step_on_empty_raises() -> None:
    with pytest.raises(EmptySchedule):
        Sim().step()


def test_run_until_time() -> None:
    sim = Sim()
    sim.delay(5.0)
    sim.delay(15.0)
    sim.run(until=10.0)
    assert sim.now == 10.0


def test_run_until_time_must_be_in_future() -> None:
    sim = Sim()
    with pytest.raises(ValueError, match="must be greater"):
        sim.run(until=0)


def test_run_until_event_returns_its_value() -> None:
    sim = Sim()
    marker = sim.delay(3.0, value="reached")
    assert sim.run(until=marker) == "reached"
    assert sim.now == 3.0


def test_run_until_already_processed_event_returns_immediately() -> None:
    sim = Sim()
    marker = sim.delay(1.0, value="v")
    sim.run()
    assert sim.run(until=marker) == "v"


def test_run_until_unreachable_event_raises() -> None:
    sim = Sim()
    never: Event[None] = Event(sim)
    with pytest.raises(RuntimeError, match="not.*triggered"):
        sim.run(until=never)


def test_bare_run_drains_schedule_and_returns_none() -> None:
    sim = Sim()
    sim.delay(1.0)
    sim.delay(2.0)
    assert sim.run() is None
    assert sim.now == 2.0
