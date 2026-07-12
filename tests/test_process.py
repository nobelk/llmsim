"""Process driver: generators, coroutines, interrupts, return values (G3)."""

import inspect
from collections.abc import Generator
from typing import Any

import pytest

from llmsim.core.errors import Interrupt
from llmsim.core.events import Event
from llmsim.core.process import Process
from llmsim.core.sim import Sim


def _gen_process(sim: Sim, log: list[Any]) -> Generator[Event[Any], Any, str]:
    log.append(("start", sim.now))
    yield sim.delay(5.0)
    log.append(("mid", sim.now))
    yield sim.delay(5.0)
    log.append(("end", sim.now))
    return "done"


async def _coro_process(sim: Sim, log: list[Any]) -> str:
    log.append(("start", sim.now))
    await sim.delay(5.0)
    log.append(("mid", sim.now))
    await sim.delay(5.0)
    log.append(("end", sim.now))
    return "done"


def test_generator_process_runs() -> None:
    sim = Sim()
    log: list[Any] = []
    sim.spawn(_gen_process, log)
    sim.run()
    assert log == [("start", 0), ("mid", 5.0), ("end", 10.0)]


def test_coroutine_process_runs() -> None:
    sim = Sim()
    log: list[Any] = []
    sim.spawn(_coro_process, log)
    sim.run()
    assert log == [("start", 0), ("mid", 5.0), ("end", 10.0)]


def test_generator_and_coroutine_produce_identical_logs() -> None:
    gen_sim = Sim()
    gen_log: list[Any] = []
    gen_sim.spawn(_gen_process, gen_log)
    gen_sim.run()

    coro_sim = Sim()
    coro_log: list[Any] = []
    coro_sim.spawn(_coro_process, coro_log)
    coro_sim.run()

    assert gen_log == coro_log


def test_mixed_generator_and_coroutine_in_one_run() -> None:
    sim = Sim()
    log: list[Any] = []
    sim.spawn(_gen_process, log)
    sim.spawn(_coro_process, log)
    sim.run()
    # Both start at 0, hit mid at 5, end at 10 -- interleaved but time-consistent.
    assert log.count(("start", 0)) == 2
    assert log.count(("mid", 5.0)) == 2
    assert log.count(("end", 10.0)) == 2


def test_unified_driver_is_a_single_send_throw_path() -> None:
    """White-box: one resume/error-resume path drives generators and coroutines.

    Guards the unified-driver key decision against silent drift into a separate
    coroutine loop or adapter (validation.md).
    """
    source = inspect.getsource(Process._resume)
    # Exactly one send and one throw call -- not one pair per process type.
    assert source.count(".send(") == 1
    assert source.count(".throw(") == 1
    # No parallel coroutine-specific driver method exists on Process.
    resume_like = [
        name
        for name in dir(Process)
        if "resume" in name.lower() or "drive" in name.lower()
    ]
    assert resume_like == ["_resume"]


def test_process_is_an_event_carrying_its_return_value() -> None:
    sim = Sim()
    collected: list[Any] = []

    def child(sim: Sim) -> Generator[Event[Any], Any, int]:
        yield sim.delay(1.0)
        return 99

    def parent(sim: Sim) -> Generator[Event[Any], Any, None]:
        child_process = sim.spawn(child)
        result = yield child_process
        collected.append(result)

    sim.spawn(parent)
    sim.run()
    assert collected == [99]


def test_interrupt_is_thrown_into_the_target() -> None:
    sim = Sim()
    log: list[Any] = []

    def victim(sim: Sim) -> Generator[Event[Any], Any, None]:
        try:
            yield sim.delay(10.0)
            log.append("not interrupted")
        except Interrupt as interrupt:
            log.append(("interrupted", sim.now, interrupt.cause))

    def attacker(sim: Sim, target: Process[Any]) -> Generator[Event[Any], Any, None]:
        yield sim.delay(5.0)
        target.interrupt("stop")

    target = sim.spawn(victim)
    sim.spawn(attacker, target)
    sim.run()
    assert log == [("interrupted", 5.0, "stop")]


def test_interrupt_leaves_no_stale_resume_on_the_abandoned_target() -> None:
    """The interrupted process does not double-resume when its old target fires."""
    sim = Sim()
    resumes: list[float] = []

    def victim(sim: Sim) -> Generator[Event[Any], Any, None]:
        while True:
            try:
                yield sim.delay(10.0)
                resumes.append(sim.now)
            except Interrupt:
                resumes.append(-1.0)
                return

    def attacker(sim: Sim, target: Process[Any]) -> Generator[Event[Any], Any, None]:
        yield sim.delay(5.0)
        target.interrupt()

    target = sim.spawn(victim)
    sim.spawn(attacker, target)
    sim.run()
    # Only the interrupt resumes it; the abandoned 10.0 timeout does not.
    assert resumes == [-1.0]


def test_cannot_interrupt_a_terminated_process() -> None:
    sim = Sim()

    def quick(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0)

    process = sim.spawn(quick)
    sim.run()
    with pytest.raises(RuntimeError, match="terminated"):
        process.interrupt()


def test_process_cannot_interrupt_itself() -> None:
    sim = Sim()

    def selfish(sim: Sim) -> Generator[Event[Any], Any, None]:
        process = sim.active_process
        assert process is not None
        process.interrupt()
        yield sim.delay(1.0)

    sim.spawn(selfish)
    with pytest.raises(RuntimeError, match="interrupt itself"):
        sim.run()


def test_spawn_accepts_an_already_created_generator() -> None:
    sim = Sim()
    log: list[Any] = []
    sim.spawn(_gen_process(sim, log))  # generator object, not the function
    sim.run()
    assert log == [("start", 0), ("mid", 5.0), ("end", 10.0)]


def test_spawn_rejects_a_non_process() -> None:
    sim = Sim()
    with pytest.raises(ValueError, match="not a generator or coroutine"):
        sim.spawn(42)  # type: ignore[arg-type]


class _KeywordOnlyError(Exception):
    """A custom exception whose constructor cannot be replayed from ``args``."""

    def __init__(self, message: str, *, code: int) -> None:
        super().__init__(message)
        self.code = code


def test_non_replayable_exception_propagates_unchanged() -> None:
    """A domain exception with a keyword-only constructor is not masked."""
    sim = Sim()

    def failing(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0)
        raise _KeywordOnlyError("boom", code=7)

    caught: list[BaseException] = []

    def parent(sim: Sim) -> Generator[Event[Any], Any, None]:
        try:
            yield sim.spawn(failing)
        except _KeywordOnlyError as error:
            caught.append(error)

    sim.spawn(parent)
    sim.run()
    assert len(caught) == 1
    assert isinstance(caught[0], _KeywordOnlyError)
    assert caught[0].code == 7
