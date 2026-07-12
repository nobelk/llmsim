"""Condition composition: AllOf/AnyOf, & / | sugar, ExceptionGroup (G4)."""

from collections.abc import Generator
from typing import Any

from llmsim.core.conditions import AllOf, AnyOf, Condition, ConditionValue
from llmsim.core.events import Event
from llmsim.core.sim import Sim


def test_all_of_waits_for_every_event() -> None:
    sim = Sim()
    result: list[ConditionValue] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        first = sim.delay(3.0, value="a")
        second = sim.delay(7.0, value="b")
        value = yield AllOf(sim, [first, second])
        result.append(value)

    sim.spawn(waiter)
    sim.run()
    assert sim.now == 7.0  # completes only when the later one fires
    assert len(result) == 1
    assert list(result[0].values()) == ["a", "b"]


def test_any_of_completes_on_first_event() -> None:
    sim = Sim()
    finished_at: list[float] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        soon = sim.delay(2.0, value="soon")
        late = sim.delay(9.0, value="late")
        value = yield AnyOf(sim, [soon, late])
        finished_at.append(sim.now)
        assert soon in value
        assert late not in value

    sim.spawn(waiter)
    sim.run()
    assert finished_at == [2.0]


def test_and_operator_is_all_of() -> None:
    sim = Sim()
    seen: list[float] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0) & sim.delay(4.0)
        seen.append(sim.now)

    sim.spawn(waiter)
    sim.run()
    assert seen == [4.0]


def test_or_operator_is_any_of() -> None:
    sim = Sim()
    seen: list[float] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0) | sim.delay(4.0)
        seen.append(sim.now)

    sim.spawn(waiter)
    sim.run()
    assert seen == [1.0]


def test_empty_condition_succeeds_immediately() -> None:
    sim = Sim()
    condition = AllOf(sim, [])
    assert condition.triggered
    assert isinstance(condition.value, ConditionValue)
    assert list(condition.value.keys()) == []


def test_condition_value_dict_like_access() -> None:
    sim = Sim()
    captured: list[ConditionValue] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        first = sim.delay(1.0, value=10)
        second = sim.delay(2.0, value=20)
        value = yield AllOf(sim, [first, second])
        captured.append(value)

    sim.spawn(waiter)
    sim.run()
    value = captured[0]
    assert value == value.todict()
    assert len(list(value.items())) == 2


def test_single_member_failure_forwards_its_exception() -> None:
    sim = Sim()
    caught: list[BaseException] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        ok = sim.delay(5.0)
        bad: Event[None] = Event(sim)
        bad.fail(ValueError("boom"))
        try:
            yield AllOf(sim, [ok, bad])
        except ValueError as exc:
            caught.append(exc)

    sim.spawn(waiter)
    sim.run()
    assert len(caught) == 1
    assert str(caught[0]) == "boom"


def test_multiple_simultaneous_failures_aggregate_into_exception_group() -> None:
    """Clean-break divergence: concurrent failures surface as an ExceptionGroup."""
    sim = Sim()
    caught: list[BaseException] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        first: Event[None] = Event(sim)
        second: Event[None] = Event(sim)
        # Both fail at the same simulation instant.
        first.fail(ValueError("first"))
        second.fail(KeyError("second"))
        try:
            yield AllOf(sim, [first, second])
        except BaseException as exc:  # noqa: BLE001
            caught.append(exc)

    sim.spawn(waiter)
    sim.run()
    assert len(caught) == 1
    group = caught[0]
    assert isinstance(group, ExceptionGroup)
    messages = {str(exc) for exc in group.exceptions}
    assert messages == {"first", "'second'"}


def test_nested_conditions() -> None:
    sim = Sim()
    seen: list[float] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        inner = sim.delay(1.0) & sim.delay(2.0)
        outer = inner | sim.delay(9.0)
        yield outer
        seen.append(sim.now)

    sim.spawn(waiter)
    sim.run()
    assert seen == [2.0]  # the inner AllOf resolves first


def test_condition_uses_all_events_and_any_events_predicates() -> None:
    events: tuple[Event[Any], ...] = ()
    assert Condition.all_events(events, 0) is True
    assert Condition.any_events(events, 0) is True
    two: tuple[Event[Any], ...] = (Event(Sim()), Event(Sim()))
    assert Condition.all_events(two, 1) is False
    assert Condition.all_events(two, 2) is True
    assert Condition.any_events(two, 1) is True
