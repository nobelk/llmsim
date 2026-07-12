"""Container over/underflow and Store/PriorityStore/FilterStore behavior (G8)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim.core.errors import Interrupt
from llmsim.core.events import Event
from llmsim.core.process import Process
from llmsim.core.sim import Sim
from llmsim.resources.container import Container
from llmsim.resources.store import (
    FilterStore,
    PriorityItem,
    PriorityStore,
    Store,
)


def test_container_get_blocks_until_enough_matter() -> None:
    sim = Sim()
    container = Container(sim, capacity=10, init=0)
    got_at: list[float] = []

    def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield container.get(5)
        got_at.append(sim.now)

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(3.0)
        yield container.put(5)

    sim.spawn(consumer)
    sim.spawn(producer)
    sim.run()
    assert got_at == [3.0]
    assert container.level == 0


def test_container_put_blocks_on_overflow() -> None:
    sim = Sim()
    container = Container(sim, capacity=10, init=10)
    put_at: list[float] = []

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield container.put(5)
        put_at.append(sim.now)

    def drainer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(4.0)
        yield container.get(5)

    sim.spawn(producer)
    sim.spawn(drainer)
    sim.run()
    assert put_at == [4.0]
    assert container.level == 10


def test_container_rejects_bad_construction() -> None:
    with pytest.raises(ValueError):
        Container(Sim(), capacity=0)
    with pytest.raises(ValueError):
        Container(Sim(), capacity=10, init=-1)
    with pytest.raises(ValueError):
        Container(Sim(), capacity=5, init=10)


def test_container_rejects_nonpositive_amounts() -> None:
    sim = Sim()
    container = Container(sim, capacity=10, init=5)
    with pytest.raises(ValueError):
        container.put(0)
    with pytest.raises(ValueError):
        container.get(-1)


def test_store_is_fifo() -> None:
    sim = Sim()
    store: Store[str] = Store(sim)
    received: list[str] = []

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        for item in ("a", "b", "c"):
            yield store.put(item)

    def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
        for _ in range(3):
            item = yield store.get()
            received.append(item)

    sim.spawn(producer)
    sim.spawn(consumer)
    sim.run()
    assert received == ["a", "b", "c"]


def test_store_get_blocks_until_item_available() -> None:
    sim = Sim()
    store: Store[int] = Store(sim)
    got_at: list[float] = []

    def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
        item = yield store.get()
        got_at.append(sim.now)
        assert item == 7

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(2.0)
        yield store.put(7)

    sim.spawn(consumer)
    sim.spawn(producer)
    sim.run()
    assert got_at == [2.0]


def test_store_capacity_blocks_puts() -> None:
    sim = Sim()
    store: Store[int] = Store(sim, capacity=1)
    put_order: list[int] = []

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        for item in (1, 2):
            yield store.put(item)
            put_order.append(item)

    def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(5.0)
        yield store.get()

    sim.spawn(producer)
    sim.spawn(consumer)
    sim.run()
    assert put_order == [1, 2]  # second put waited for the get at t=5


def test_priority_store_orders_by_priority() -> None:
    sim = Sim()
    store: PriorityStore[PriorityItem] = PriorityStore(sim)
    received: list[str] = []

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield store.put(PriorityItem(priority=3, item="low"))
        yield store.put(PriorityItem(priority=1, item="high"))
        yield store.put(PriorityItem(priority=2, item="mid"))

    def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0)
        for _ in range(3):
            item = yield store.get()
            received.append(item.item)

    sim.spawn(producer)
    sim.spawn(consumer)
    sim.run()
    assert received == ["high", "mid", "low"]


def test_filter_store_matches_predicate() -> None:
    sim = Sim()
    store: FilterStore[int] = FilterStore(sim)
    received: list[int] = []

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        for item in (1, 2, 3, 4):
            yield store.put(item)

    def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0)
        even = yield store.get(lambda item: item % 2 == 0)
        received.append(even)

    sim.spawn(producer)
    sim.spawn(consumer)
    sim.run()
    assert received == [2]


def test_filter_store_blocked_get_does_not_stall_a_later_satisfiable_get() -> None:
    """A get whose filter cannot yet match must not block a get that can."""
    sim = Sim()
    store: FilterStore[str] = FilterStore(sim)
    received: list[str] = []

    def wants_a(sim: Sim) -> Generator[Event[Any], Any, None]:
        item = yield store.get(lambda value: value == "a")
        received.append(item)

    def wants_b(sim: Sim) -> Generator[Event[Any], Any, None]:
        item = yield store.get(lambda value: value == "b")
        received.append(item)

    def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0)
        yield store.put("b")  # only satisfies the second waiter

    sim.spawn(wants_a)  # issued first, still waiting for an "a"
    sim.spawn(wants_b)
    sim.spawn(producer)
    sim.run()
    assert received == ["b"]  # the later get is served ahead of the blocked one


def test_interrupted_store_get_before_trigger_is_dequeued() -> None:
    """A store get interrupted before it triggers leaves the queue cleanly."""
    sim = Sim()
    store: Store[int] = Store(sim)
    outcome: list[str] = []

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        with store.get() as request:
            try:
                yield request
                outcome.append("got")
            except Interrupt:
                outcome.append("interrupted")

    def canceller(sim: Sim, target: Process[Any]) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0)
        target.interrupt()

    def late_producer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(5.0)
        yield store.put(1)

    waiter_process = sim.spawn(waiter)
    sim.spawn(canceller, waiter_process)
    sim.spawn(late_producer)
    sim.run()

    assert outcome == ["interrupted"]
    # The abandoned get left the queue; the later item stays in the store.
    assert store.get_queue == []
    assert store.items == [1]
