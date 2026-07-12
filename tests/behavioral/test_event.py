"""Ported from SimPy 3's ``tests/test_event.py`` (adapted to the llmsim API)."""

import re
from collections.abc import Generator
from typing import Any

import pytest

from llmsim import Event, Sim

Proc = Generator[Any, Any, Any]


def test_succeed(sim: Sim) -> None:
    """A process resumes with the value a manually triggered event carries."""

    def child(sim: Sim, event: Event[Any]) -> Proc:
        value = yield event
        assert value == "ohai"
        assert sim.now == 5

    def parent(sim: Sim) -> Proc:
        event = sim.event()
        sim.spawn(child, event)
        yield sim.delay(5)
        event.succeed("ohai")

    sim.spawn(parent)
    sim.run()


def test_fail(sim: Sim) -> None:
    """A failed event raises its exception into the waiting process."""

    def child(sim: Sim, event: Event[Any]) -> Proc:
        with pytest.raises(ValueError, match="ohai"):
            yield event
        assert sim.now == 5

    def parent(sim: Sim) -> Proc:
        event = sim.event()
        sim.spawn(child, event)
        yield sim.delay(5)
        event.fail(ValueError("ohai"))

    sim.spawn(parent)
    sim.run()


def test_names(sim: Sim) -> None:
    """Event, Timeout, Condition, and Process reprs are stable and descriptive."""

    def pem(sim: Sim) -> Proc:
        return
        yield

    assert re.match(r"<Event\(\) object at 0x.*>", str(sim.event()))
    assert re.match(r"<Timeout\(1\) object at 0x.*>", str(sim.delay(1)))
    assert re.match(
        r"<Timeout\(1, value=2\) object at 0x.*>", str(sim.delay(1, value=2))
    )
    assert re.match(
        r"<Condition\(all_events, \(<Event\(\) object at 0x.*>, "
        r"<Event\(\) object at 0x.*>\)\) object at 0x.*>",
        str(sim.event() & sim.event()),
    )
    assert re.match(r"<Process\(pem\) object at 0x.*>", str(sim.spawn(pem)))


def test_value(sim: Sim) -> None:
    """A triggered event exposes its value."""
    event = sim.delay(0, "I am the value")
    sim.run()
    assert event.value == "I am the value"


def test_unavailable_value(sim: Sim) -> None:
    """An untriggered event's value is not accessible."""
    event = sim.event()
    with pytest.raises(AttributeError, match=r".* is not yet available$"):
        _ = event.value


def test_triggered(sim: Sim) -> None:
    """A process waiting on an already-triggered event resumes with its value."""

    def pem(sim: Sim, event: Event[Any]) -> Proc:
        value = yield event
        return value

    event: Event[str] = sim.event()
    event.succeed("i was already done")
    result = sim.run(sim.spawn(pem, event))
    assert result == "i was already done"


def test_callback_modification(sim: Sim) -> None:
    """Callbacks are cleared before invocation to prevent concurrent modification."""

    def callback(event: Event[Any]) -> None:
        assert event.callbacks is None

    event = sim.event()
    assert event.callbacks is not None
    event.callbacks.append(callback)
    event.succeed()
    sim.run(until=event)


def test_condition_callback_removal(sim: Sim) -> None:
    """A triggered condition removes its check callback from its members."""
    a, b = sim.event(), sim.event()
    a.succeed()
    sim.run(until=a | b)
    assert not a.callbacks
    assert not b.callbacks


def test_condition_nested_callback_removal(sim: Sim) -> None:
    """Check callbacks are removed even from nested condition members."""
    a, b, c = sim.event(), sim.event(), sim.event()
    b_and_c = b & c
    a_or_b_and_c = a | b_and_c
    a.succeed()
    sim.run(until=a_or_b_and_c)
    assert not a.callbacks
    assert not b.callbacks
    assert not c.callbacks
    assert b_and_c.callbacks is not None
    for callback in b_and_c.callbacks:
        assert callback.__name__ != "_check"
    assert not a_or_b_and_c.callbacks
