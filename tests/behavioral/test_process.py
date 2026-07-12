"""Ported from SimPy 3's ``tests/test_process.py`` (adapted to the llmsim API)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim import Interrupt, Process, Sim

Proc = Generator[Any, Any, Any]


def test_start_non_process(sim: Sim) -> None:
    """A plain function (not a generator/coroutine) cannot be a process."""

    def foo(sim: Sim) -> None:
        pass

    # Divergence: llmsim's spawn calls the function (injecting sim), so the
    # error names the returned non-runnable; SimPy 3 checks the passed object.
    with pytest.raises(ValueError, match="not a generator or coroutine"):
        sim.spawn(foo)


def test_get_state(sim: Sim) -> None:
    """A process is alive until its body terminates."""

    def pem_a(sim: Sim) -> Proc:
        yield sim.delay(3)

    def pem_b(sim: Sim, pem_a: Process[Any]) -> Proc:
        yield sim.delay(1)
        assert pem_a.is_alive
        yield sim.delay(3)
        assert not pem_a.is_alive

    proc_a = sim.spawn(pem_a)
    sim.spawn(pem_b, proc_a)
    sim.run()


def test_target(sim: Sim) -> None:
    """A process's ``target`` is the event it is currently waiting on."""

    def pem(sim: Sim, event: Any) -> Proc:
        yield event

    event = sim.delay(5)
    proc = sim.spawn(pem, event)
    while sim.peek() < 5:
        sim.step()
    assert proc.target is event
    proc.interrupt()


def test_wait_for_proc(sim: Sim) -> None:
    """A process can wait until another process finishes."""

    def finisher(sim: Sim) -> Proc:
        yield sim.delay(5)

    def waiter(sim: Sim) -> Proc:
        proc = sim.spawn(finisher)
        yield proc
        assert sim.now == 5

    sim.spawn(waiter)
    sim.run()


def test_return_value(sim: Sim) -> None:
    """Processes propagate their return value to a waiting process."""

    def child(sim: Sim) -> Proc:
        yield sim.delay(1)
        return sim.now

    def parent(sim: Sim) -> Proc:
        result1 = yield sim.spawn(child)
        result2 = yield sim.spawn(child)
        assert [result1, result2] == [1, 2]

    sim.spawn(parent)
    sim.run()


def test_child_exception(sim: Sim) -> None:
    """A child may return an exception as an ordinary value."""

    def child(sim: Sim) -> Proc:
        yield sim.delay(1)
        return RuntimeError("Onoes!")

    def parent(sim: Sim) -> Proc:
        result = yield sim.spawn(child)
        assert isinstance(result, Exception)

    sim.spawn(parent)
    sim.run()


def test_interrupted_join(sim: Sim) -> None:
    """An interrupt removes a process from its target's callbacks."""

    def interruptor(sim: Sim, process: Process[Any]) -> Proc:
        yield sim.delay(1)
        process.interrupt()

    def child(sim: Sim) -> Proc:
        yield sim.delay(2)

    def parent(sim: Sim) -> Proc:
        child_proc = sim.spawn(child)
        try:
            yield child_proc
            pytest.fail("Did not receive an interrupt.")
        except Interrupt:
            assert sim.now == 1
            assert child_proc.is_alive
            yield sim.delay(5)
            assert sim.now == 6

    parent_proc = sim.spawn(parent)
    sim.spawn(interruptor, parent_proc)
    sim.run()


def test_interrupted_join_and_rejoin(sim: Sim) -> None:
    """After an interrupt, a process may wait on its target again."""

    def interruptor(sim: Sim, process: Process[Any]) -> Proc:
        yield sim.delay(1)
        process.interrupt()

    def child(sim: Sim) -> Proc:
        yield sim.delay(2)

    def parent(sim: Sim) -> Proc:
        child_proc = sim.spawn(child)
        try:
            yield child_proc
            pytest.fail("Did not receive an interrupt.")
        except Interrupt:
            assert sim.now == 1
            assert child_proc.is_alive
            yield child_proc
            assert sim.now == 2

    parent_proc = sim.spawn(parent)
    sim.spawn(interruptor, parent_proc)
    sim.run()


def test_error_and_interrupted_join(sim: Sim) -> None:
    """An interrupt unregisters the victim from a failing process it awaited."""

    def child_a(sim: Sim, process: Process[Any]) -> Proc:
        process.interrupt()
        return
        yield

    def child_b(sim: Sim) -> Proc:
        raise AttributeError("spam")
        yield

    def parent(sim: Sim) -> Proc:
        active = sim.active_process
        assert active is not None
        sim.spawn(child_a, active)
        b = sim.spawn(child_b)
        try:
            yield b
        except Interrupt:
            pass
        yield sim.delay(0)

    sim.spawn(parent)
    with pytest.raises(AttributeError):
        sim.run()
