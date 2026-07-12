"""Ported from SimPy 3's ``tests/test_exceptions.py`` (adapted to llmsim).

The traceback-exact SimPy tests are ported as structural checks: llmsim does
not strip the driver frame from process tracebacks the way SimPy 3 does, so the
exact multi-line traceback text differs; the exception *chaining* it verifies is
preserved and asserted here instead (annotated divergences).
"""

import sys
import traceback
from collections.abc import Generator
from io import StringIO
from typing import Any

import pytest

from llmsim import Event, Sim

Proc = Generator[Any, Any, Any]


def test_error_forwarding(sim: Sim) -> None:
    """An exception raised in a child is forwarded to its waiting parent."""

    def child(sim: Sim) -> Proc:
        raise ValueError("Onoes!")
        yield sim.delay(1)

    def parent(sim: Sim) -> Proc:
        with pytest.raises(ValueError, match="Onoes!"):
            yield sim.spawn(child)

    sim.spawn(parent)
    sim.run()


def test_no_parent_process(sim: Sim) -> None:
    """With no process waiting on it, a child's exception crashes the sim."""

    def child(sim: Sim) -> Proc:
        raise ValueError("Onoes!")
        yield sim.delay(1)

    def parent(sim: Sim) -> Proc:
        sim.spawn(child)
        yield sim.delay(1)

    sim.spawn(parent)
    with pytest.raises(ValueError, match="Onoes!"):
        sim.run()


def test_crashing_child_traceback(sim: Sim) -> None:
    """A waiting parent sees the crashing child's frames in the traceback."""

    def panic(sim: Sim) -> Proc:
        yield sim.delay(1)
        raise RuntimeError("Oh noes, roflcopter incoming... BOOM!")

    def root(sim: Sim) -> Proc:
        try:
            yield sim.spawn(panic)
            pytest.fail("Hey, where's the roflcopter?")
        except RuntimeError:
            stacktrace = traceback.format_exc()
            # The waiting parent's frame and the crashing child's frame (via the
            # chained __cause__) are both present in the traceback.
            assert "yield sim.spawn(panic)" in stacktrace
            assert "raise RuntimeError" in stacktrace
            assert "Oh noes, roflcopter" in stacktrace

    sim.spawn(root)
    sim.run()


def test_exception_chaining(sim: Sim) -> None:
    """An unhandled failure chains through every process that awaited it.

    Divergence: SimPy 3 asserts the exact multi-line traceback (including its
    own ``core.py`` frames). llmsim asserts the equivalent property -- the same
    ``RuntimeError('foo')`` is linked by ``__cause__`` through each level.
    """

    def child(sim: Sim) -> Proc:
        yield sim.delay(1)
        raise RuntimeError("foo")

    def parent(sim: Sim) -> Proc:
        yield sim.spawn(child)

    def grandparent(sim: Sim) -> Proc:
        yield sim.spawn(parent)

    sim.spawn(grandparent)
    with pytest.raises(RuntimeError, match="foo") as excinfo:
        sim.run()

    depth = 0
    exc: BaseException | None = excinfo.value
    while exc is not None:
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "foo"
        depth += 1
        exc = exc.__cause__
    assert depth >= 3  # crash -> grandparent -> parent (-> child)


def test_invalid_event(sim: Sim) -> None:
    """Yielding a non-event fails the simulation."""

    def root(sim: Sim) -> Proc:
        yield None

    sim.spawn(root)
    # Divergence: llmsim's message is "yielded None, which is not an event" vs
    # SimPy 3's 'Invalid yield value "None"'; both raise RuntimeError.
    with pytest.raises(RuntimeError, match="yielded None"):
        sim.run()


def test_exception_handling(sim: Sim) -> None:
    """An undefused failed event crashes the simulation."""
    event = sim.event()
    event.fail(RuntimeError())
    with pytest.raises(RuntimeError):
        sim.run(until=1)


def test_callback_exception_handling(sim: Sim) -> None:
    """A callback may defuse a failed event by setting ``defused``."""

    def callback(event: Event[Any]) -> None:
        event.defused = True

    event = sim.event()
    assert event.callbacks is not None
    event.callbacks.append(callback)
    event.fail(RuntimeError())
    assert not event.defused, "event defused too early"
    sim.run(until=1)
    assert event.defused


def test_process_exception_handling(sim: Sim) -> None:
    """A process waiting on a failed event handles it and defuses it."""

    def pem(sim: Sim, event: Event[Any]) -> Proc:
        try:
            yield event
            pytest.fail("the event should fail")
        except RuntimeError:
            pass

    event = sim.event()
    sim.spawn(pem, event)
    event.fail(RuntimeError())
    assert not event.defused, "event defused too early"
    sim.run(until=1)
    assert event.defused


def test_process_exception_chaining(sim: Sim) -> None:
    """Each waiting process receives a private copy of a failed event's exception."""

    def process_a(sim: Sim, event: Event[Any]) -> Proc:
        try:
            yield event
        except RuntimeError:
            assert "process_b" not in traceback.format_exc()

    def process_b(sim: Sim, event: Event[Any]) -> Proc:
        try:
            yield event
        except RuntimeError:
            assert "process_a" not in traceback.format_exc()

    event = sim.event()
    event.fail(RuntimeError("foo"))
    sim.spawn(process_a, event)
    sim.spawn(process_b, event)
    sim.run()


def test_sys_excepthook(sim: Sim) -> None:
    """The default excepthook reports the full process chain of an unhandled fail."""

    def process_a(sim: Sim, event: Event[Any]) -> Proc:
        yield event

    def process_b(sim: Sim, proc_a: Any) -> Proc:
        yield proc_a

    event = sim.event()
    event.fail(RuntimeError("foo"))
    sim.spawn(process_b, sim.spawn(process_a, event))

    try:
        sim.run()
    except BaseException:  # noqa: BLE001
        stderr, sys.stderr = sys.stderr, StringIO()
        typ, value, tb = sys.exc_info()
        assert typ is not None and value is not None
        sys.excepthook(typ, value, tb)
        rendered = sys.stderr.getvalue()
        sys.stderr = stderr
        assert "process_a" in rendered
        assert "process_b" in rendered
