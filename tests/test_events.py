"""Event lifecycle, callbacks, trigger guards, and the await protocol (G1)."""

import pytest

from llmsim.core.events import PENDING, Event, Timeout
from llmsim.core.sim import Sim


def test_event_starts_untriggered() -> None:
    sim = Sim()
    event: Event[int] = Event(sim)
    assert not event.triggered
    assert not event.processed
    assert event._value is PENDING


def test_ok_and_value_raise_before_trigger() -> None:
    sim = Sim()
    event: Event[int] = Event(sim)
    with pytest.raises(AttributeError):
        _ = event.ok
    with pytest.raises(AttributeError):
        _ = event.value


def test_succeed_sets_value_and_schedules() -> None:
    sim = Sim()
    event: Event[str] = Event(sim)
    assert event.succeed("done") is event
    assert event.triggered
    assert event.ok
    assert event.value == "done"


def test_double_trigger_guard() -> None:
    sim = Sim()
    event: Event[int] = Event(sim)
    event.succeed(1)
    with pytest.raises(RuntimeError, match="already been triggered"):
        event.succeed(2)
    with pytest.raises(RuntimeError, match="already been triggered"):
        event.fail(ValueError("x"))


def test_fail_rejects_non_exception() -> None:
    sim = Sim()
    event: Event[int] = Event(sim)
    with pytest.raises(ValueError, match="not an exception"):
        event.fail("not an exception")  # type: ignore[arg-type]


def test_callbacks_fire_in_registration_order() -> None:
    sim = Sim()
    event: Event[int] = Event(sim)
    order: list[int] = []
    event.callbacks.append(lambda _e: order.append(1))  # type: ignore[union-attr]
    event.callbacks.append(lambda _e: order.append(2))  # type: ignore[union-attr]
    event.callbacks.append(lambda _e: order.append(3))  # type: ignore[union-attr]
    event.succeed()
    sim.run()
    assert order == [1, 2, 3]
    assert event.processed


def test_await_yields_self_exactly_once() -> None:
    sim = Sim()
    event: Event[int] = Event(sim)
    event.succeed(42)
    iterator = event.__await__()
    yielded = next(iterator)
    assert yielded is event
    with pytest.raises(StopIteration) as caught:
        iterator.send(event.value)
    assert caught.value.value == 42


def test_timeout_is_scheduled_on_construction() -> None:
    sim = Sim()
    timeout = Timeout(sim, 5.0, value="late")
    assert timeout.triggered  # timeouts are born successful
    assert sim.peek() == 5.0
    sim.run()
    assert sim.now == 5.0
    assert timeout.value == "late"


def test_timeout_rejects_negative_delay() -> None:
    sim = Sim()
    with pytest.raises(ValueError, match="negative delay"):
        Timeout(sim, -1.0)


def test_trigger_adopts_other_event_outcome() -> None:
    sim = Sim()
    source: Event[int] = Event(sim)
    source.succeed(7)
    follower: Event[int] = Event(sim)
    follower.trigger(source)
    sim.run()
    assert follower.ok
    assert follower.value == 7
