"""Ported from SimPy 3's ``tests/test_timeout.py`` (adapted to the llmsim API)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim import Event, Sim

Proc = Generator[Any, Any, Any]


def test_discrete_time_steps(sim: Sim, log: list[Any]) -> None:
    """A process advancing by unit delays observes discrete time steps."""

    def pem(sim: Sim, log: list[Any]) -> Proc:
        while True:
            log.append(sim.now)
            yield sim.delay(1)

    sim.spawn(pem, log)
    sim.run(until=3)
    assert log == [0, 1, 2]


def test_negative_timeout(sim: Sim) -> None:
    """Negative delays are rejected."""

    def pem(sim: Sim) -> Proc:
        yield sim.delay(-1)

    sim.spawn(pem)
    # Divergence: llmsim's message is lower-cased ("negative delay") vs SimPy 3's
    # "Negative delay"; the behavior (ValueError on a negative delay) is identical.
    with pytest.raises(ValueError, match="negative delay"):
        sim.run()


def test_timeout_value(sim: Sim) -> None:
    """A delay yields back the value it was given."""

    def pem(sim: Sim) -> Proc:
        value = yield sim.delay(1, "ohai")
        assert value == "ohai"

    sim.spawn(pem)
    sim.run()


def test_shared_timeout(sim: Sim, log: list[Any]) -> None:
    """Several processes may wait on the same timeout event."""

    def child(sim: Sim, timeout: Event[Any], index: int, log: list[Any]) -> Proc:
        yield timeout
        log.append((index, sim.now))

    timeout = sim.delay(1)
    for index in range(3):
        sim.spawn(child, timeout, index, log)
    sim.run()
    assert log == [(0, 1), (1, 1), (2, 1)]


def test_triggered_timeout(sim: Sim) -> None:
    """A process may wait on a timeout that already fired."""

    def process(sim: Sim) -> Proc:
        def child(sim: Sim, event: Event[Any]) -> Proc:
            value = yield event
            return value

        event = sim.delay(1, "i was already done")
        yield sim.delay(2)
        value = yield sim.spawn(child, event)
        assert value == "i was already done"

    sim.run(sim.spawn(process))
