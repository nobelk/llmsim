"""Ported from SimPy 3's ``tests/test_interrupts.py`` (adapted to llmsim)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim import Interrupt, Process, Sim

Proc = Generator[Any, Any, Any]


def test_interruption(sim: Sim) -> None:
    """A process can be interrupted while waiting for another event."""

    def interruptee(sim: Sim) -> Proc:
        with pytest.raises(Interrupt, match="interrupt!"):
            yield sim.delay(10)

    def interruptor(sim: Sim) -> Proc:
        child_process = sim.spawn(interruptee)
        yield sim.delay(5)
        child_process.interrupt("interrupt!")

    sim.spawn(interruptor)
    sim.run()


def test_concurrent_interrupts(sim: Sim, log: list[Any]) -> None:
    """Concurrent interrupts are delivered in the order they were scheduled."""

    def fox(sim: Sim, log: list[Any]) -> Proc:
        while True:
            try:
                yield sim.delay(10)
            except Interrupt as interrupt:
                log.append((sim.now, interrupt.cause))

    def farmer(sim: Sim, name: str, fox: Process[Any]) -> Proc:
        fox.interrupt(name)
        yield sim.delay(1)

    fantastic_mr_fox = sim.spawn(fox, log)
    for name in ("boggis", "bunce", "beans"):
        sim.spawn(farmer, name, fantastic_mr_fox)

    sim.run(20)
    assert log == [(0, "boggis"), (0, "bunce"), (0, "beans")]


def test_concurrent_interrupts_and_events(sim: Sim, log: list[Any]) -> None:
    """An interrupt reaches a process even if its awaited event fired concurrently."""

    def fox(sim: Sim, coup: Any, log: list[Any]) -> Proc:
        while True:
            try:
                yield coup
                log.append(f"coup completed at {sim.now}")
            except Interrupt:
                log.append(f"coup interrupted at {sim.now}")
            else:
                return

    def master_plan(sim: Sim, fox: Process[Any], coup: Any) -> Proc:
        yield sim.delay(1)
        coup.succeed()
        fox.interrupt()

    coup = sim.event()
    fantastic_mr_fox = sim.spawn(fox, coup, log)
    sim.spawn(master_plan, fantastic_mr_fox, coup)

    sim.run(5)
    assert log == ["coup interrupted at 1", "coup completed at 1"]


def test_init_interrupt(sim: Sim) -> None:
    """An interrupt is delivered after the process-initialization event."""

    def child(sim: Sim) -> Proc:
        try:
            yield sim.delay(10)
            pytest.fail("Should have been interrupted.")
        except Interrupt:
            assert sim.now == 0

    def root(sim: Sim) -> Proc:
        child_proc = sim.spawn(child)
        child_proc.interrupt()
        yield sim.delay(1)

    sim.spawn(root)
    sim.run()


def test_interrupt_terminated_process(sim: Sim) -> None:
    """A terminated process cannot be interrupted."""

    def child(sim: Sim) -> Proc:
        yield sim.delay(1)

    def parent(sim: Sim) -> Proc:
        child_proc = sim.spawn(child)
        yield sim.delay(2)
        with pytest.raises(RuntimeError, match="has terminated and cannot be"):
            child_proc.interrupt()
        yield sim.delay(1)

    sim.spawn(parent)
    sim.run()


def test_multiple_interrupts(sim: Sim) -> None:
    """Interrupts on a process that dies handling the first are discarded."""

    def child(sim: Sim) -> Proc:
        try:
            yield sim.delay(1)
        except Interrupt as interrupt:
            return interrupt.cause

    def parent(sim: Sim) -> Proc:
        child_proc = sim.spawn(child)
        yield sim.delay(0)
        child_proc.interrupt(1)
        child_proc.interrupt(2)
        result = yield child_proc
        assert result == 1

    sim.spawn(parent)
    sim.run()


def test_interrupt_self(sim: Sim) -> None:
    """A process may not interrupt itself."""

    def pem(sim: Sim) -> Proc:
        active = sim.active_process
        assert active is not None
        with pytest.raises(RuntimeError):
            active.interrupt()
        yield sim.delay(0)

    sim.spawn(pem)
    sim.run()


def test_immediate_interrupt(sim: Sim, log: list[Any]) -> None:
    """A process is interruptable before it has advanced at all."""

    def child(sim: Sim, log: list[Any]) -> Proc:
        try:
            yield sim.event()
        except Interrupt:
            log.append(sim.now)

    def parent(sim: Sim, log: list[Any]) -> Proc:
        child_proc = sim.spawn(child, log)
        child_proc.interrupt()
        return
        yield

    sim.spawn(parent, log)
    sim.run()
    assert log == [0]


def test_interrupt_event(sim: Sim) -> None:
    """A process may be interrupted while waiting for a plain event."""

    def child(sim: Sim) -> Proc:
        try:
            yield sim.event()
        except Interrupt:
            assert sim.now == 5

    def parent(sim: Sim) -> Proc:
        child_proc = sim.spawn(child)
        yield sim.delay(5)
        child_proc.interrupt()

    sim.spawn(parent)
    sim.run()


def test_concurrent_behaviour(sim: Sim) -> None:
    """Multiple queued interrupts each surface at the process's next resume."""

    def proc_a(sim: Sim) -> Proc:
        timeouts = [sim.delay(0) for _ in range(2)]
        while timeouts:
            with pytest.raises(Interrupt):
                yield timeouts.pop(0)

    def proc_b(sim: Sim, proc_a: Process[Any]) -> Proc:
        for _ in range(2):
            proc_a.interrupt()
        return
        yield

    started = sim.spawn(proc_a)
    sim.spawn(proc_b, started)
    sim.run()
