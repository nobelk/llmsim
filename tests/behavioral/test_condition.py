"""Ported from SimPy 3's ``tests/test_condition.py`` (adapted to llmsim)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim import Sim

Proc = Generator[Any, Any, Any]


def test_operator_and(sim: Sim) -> None:
    """``&`` chains into an all-events condition over every operand."""

    def process(sim: Sim) -> Proc:
        timeout = [sim.delay(delay, value=delay) for delay in range(3)]
        results = yield timeout[0] & timeout[1] & timeout[2]
        assert results == {timeout[0]: 0, timeout[1]: 1, timeout[2]: 2}

    sim.spawn(process)
    sim.run()


def test_operator_and_blocked(sim: Sim) -> None:
    """An all-events condition stays untriggered while a member is pending."""

    def process(sim: Sim) -> Proc:
        timeout = sim.delay(1)
        event = sim.event()
        yield sim.delay(1)
        condition = timeout & event
        assert not condition.triggered

    sim.spawn(process)
    sim.run()


def test_operator_or(sim: Sim) -> None:
    """``|`` chains into an any-events condition."""

    def process(sim: Sim) -> Proc:
        timeout = [sim.delay(delay, value=delay) for delay in range(3)]
        results = yield timeout[0] | timeout[1] | timeout[2]
        assert results == {timeout[0]: 0}

    sim.spawn(process)
    sim.run()


def test_operator_nested_and(sim: Sim) -> None:
    """Nested and/or conditions resolve at the right time with the right value."""

    def process(sim: Sim) -> Proc:
        timeout = [sim.delay(delay, value=delay) for delay in range(3)]
        results = yield (timeout[0] & timeout[2]) | timeout[1]
        assert results == {timeout[0]: 0, timeout[1]: 1}
        assert sim.now == 1

    sim.spawn(process)
    sim.run()


def test_operator_nested_or(sim: Sim) -> None:
    """An or nested inside an and yields all events triggered by completion."""

    def process(sim: Sim) -> Proc:
        timeout = [sim.delay(delay, value=delay) for delay in range(3)]
        results = yield (timeout[0] | timeout[1]) & timeout[2]
        assert results == {timeout[0]: 0, timeout[1]: 1, timeout[2]: 2}
        assert sim.now == 2

    sim.spawn(process)
    sim.run()


def test_nested_cond_with_error(sim: Sim) -> None:
    """A failing member fails the enclosing condition."""

    def explode(sim: Sim) -> Proc:
        yield sim.delay(1)
        raise ValueError("Onoes!")

    def process(sim: Sim) -> Proc:
        with pytest.raises(ValueError, match="Onoes!"):
            yield sim.spawn(explode) & sim.delay(1)

    sim.spawn(process)
    sim.run()


def test_cond_with_error(sim: Sim) -> None:
    """A member that fails first fails an any-events condition."""

    def explode(sim: Sim, delay: float) -> Proc:
        yield sim.delay(delay)
        raise ValueError(f"Onoes, failed after {delay}!")

    def process(sim: Sim) -> Proc:
        with pytest.raises(ValueError, match="Onoes, failed after 0!"):
            yield sim.spawn(explode, 0) | sim.delay(1)

    sim.spawn(process)
    sim.run()


def test_cond_with_nested_error(sim: Sim) -> None:
    """A failing member fails a nested and/or condition."""

    def explode(sim: Sim, delay: float) -> Proc:
        yield sim.delay(delay)
        raise ValueError(f"Onoes, failed after {delay}!")

    def process(sim: Sim) -> Proc:
        with pytest.raises(ValueError, match="Onoes, failed after 0!"):
            yield sim.spawn(explode, 0) & sim.delay(1) | sim.delay(1)

    sim.spawn(process)
    sim.run()


def test_cond_with_uncaught_error(sim: Sim) -> None:
    """A failure after a condition triggers is not absorbed and crashes the sim."""

    def explode(sim: Sim, delay: float) -> Proc:
        yield sim.delay(delay)
        raise ValueError(f"Onoes, failed after {delay}!")

    def process(sim: Sim) -> Proc:
        yield sim.delay(1) | sim.spawn(explode, 2)

    sim.spawn(process)
    with pytest.raises(ValueError, match="Onoes, failed after"):
        sim.run()
    assert sim.now == 2


def test_iand_with_and_cond(sim: Sim) -> None:
    """``&=`` on an and-condition produces a new, extended condition."""

    def process(sim: Sim) -> Proc:
        cond = sim.delay(1, value=1) & sim.delay(2, value=2)
        orig = cond
        cond &= sim.delay(0, value=0)
        assert cond is not orig
        results = yield cond
        assert list(results.values()) == [1, 2, 0]

    sim.spawn(process)
    sim.run()


def test_iand_with_or_cond(sim: Sim) -> None:
    """``&=`` on an or-condition wraps it in a new and-condition."""

    def process(sim: Sim) -> Proc:
        cond = sim.delay(1, value=1) | sim.delay(2, value=2)
        orig = cond
        cond &= sim.delay(0, value=0)
        assert cond is not orig
        results = yield cond
        assert list(results.values()) == [1, 0]

    sim.spawn(process)
    sim.run()


def test_ior_with_or_cond(sim: Sim) -> None:
    """``|=`` on an or-condition produces a new, extended condition."""

    def process(sim: Sim) -> Proc:
        cond = sim.delay(1, value=1) | sim.delay(2, value=2)
        orig = cond
        cond |= sim.delay(0, value=0)
        assert cond is not orig
        results = yield cond
        assert list(results.values()) == [0]

    sim.spawn(process)
    sim.run()


def test_ior_with_and_cond(sim: Sim) -> None:
    """``|=`` on an and-condition wraps it in a new or-condition."""

    def process(sim: Sim) -> Proc:
        cond = sim.delay(1, value=1) & sim.delay(2, value=2)
        orig = cond
        cond |= sim.delay(0, value=0)
        assert cond is not orig
        results = yield cond
        assert list(results.values()) == [0]

    sim.spawn(process)
    sim.run()


def test_immutable_results(sim: Sim) -> None:
    """A condition's result is frozen once it triggers."""

    def process(sim: Sim) -> Proc:
        timeout = [sim.delay(delay, value=delay) for delay in range(3)]
        condition = timeout[0] | (timeout[1] & timeout[2])
        results = yield condition
        assert results == {timeout[0]: 0}
        yield sim.delay(2)
        assert results == {timeout[0]: 0}

    sim.spawn(process)
    sim.run()


def test_shared_and_condition(sim: Sim) -> None:
    """Two processes sharing nested and-conditions each see the right result."""
    timeout = [sim.delay(delay, value=delay) for delay in range(3)]
    c1 = timeout[0] & timeout[1]
    c2 = c1 & timeout[2]

    def p1(sim: Sim, condition: Any) -> Proc:
        results = yield condition
        assert results == {timeout[0]: 0, timeout[1]: 1}

    def p2(sim: Sim, condition: Any) -> Proc:
        results = yield condition
        assert results == {timeout[0]: 0, timeout[1]: 1, timeout[2]: 2}

    sim.spawn(p1, c1)
    sim.spawn(p2, c2)
    sim.run()


def test_shared_or_condition(sim: Sim) -> None:
    """Two processes sharing nested or-conditions each see the right result."""
    timeout = [sim.delay(delay, value=delay) for delay in range(3)]
    c1 = timeout[0] | timeout[1]
    c2 = c1 | timeout[2]

    def p1(sim: Sim, condition: Any) -> Proc:
        results = yield condition
        assert results == {timeout[0]: 0}

    def p2(sim: Sim, condition: Any) -> Proc:
        results = yield condition
        assert results == {timeout[0]: 0}

    sim.spawn(p1, c1)
    sim.spawn(p2, c2)
    sim.run()


def test_condition_value(sim: Sim) -> None:
    """A ConditionValue behaves like a read-only ordered mapping."""
    timeouts = [sim.delay(delay, value=delay) for delay in range(3)]

    def p(sim: Sim, timeouts: list[Any]) -> Proc:
        results = yield sim.all_of(timeouts)
        assert list(results) == timeouts
        assert list(results.keys()) == timeouts
        assert list(results.values()) == [0, 1, 2]
        assert list(results.items()) == list(zip(timeouts, [0, 1, 2], strict=True))
        assert timeouts[0] in results
        assert results[timeouts[0]] == 0
        assert results == results
        assert results == results.todict()

    sim.spawn(p, timeouts)
    sim.run()


def test_result_order(sim: Sim) -> None:
    """A condition's result order follows the order events were specified."""
    timeouts = list(reversed([sim.delay(delay) for delay in range(3)]))

    def p(sim: Sim, timeouts: list[Any]) -> Proc:
        results = yield sim.all_of(timeouts)
        assert list(results.keys()) == timeouts

    sim.spawn(p, timeouts)
    sim.run()


def test_nested_result_order(sim: Sim) -> None:
    """Result order follows specification order even through nesting."""
    timeouts = [sim.delay(delay) for delay in range(3)]
    condition = (timeouts[0] | timeouts[1]) & timeouts[2]

    def p(sim: Sim, timeouts: list[Any]) -> Proc:
        results = yield condition
        assert list(results.keys()) == timeouts

    sim.spawn(p, timeouts)
    sim.run()


def test_all_of_empty_list(sim: Sim) -> None:
    """An all-events condition over no events triggers immediately."""
    event = sim.all_of([])
    assert event.triggered


def test_any_of_empty_list(sim: Sim) -> None:
    """An any-events condition over no events triggers immediately."""
    event = sim.any_of([])
    assert event.triggered
