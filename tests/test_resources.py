"""Resource, PriorityResource, PreemptiveResource behavior (G7)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim.core.errors import Interrupt
from llmsim.core.events import Event
from llmsim.core.process import Process
from llmsim.core.sim import Sim
from llmsim.resources.resource import (
    Preempted,
    PreemptiveResource,
    PriorityResource,
    Resource,
)


def test_capacity_limits_concurrent_users() -> None:
    sim = Sim()
    resource = Resource(sim, capacity=2)
    concurrent: list[int] = []

    def user(sim: Sim) -> Generator[Event[Any], Any, None]:
        with resource.request() as slot:
            yield slot
            concurrent.append(resource.count)
            yield sim.delay(1.0)

    for _ in range(5):
        sim.spawn(user)
    sim.run()
    assert max(concurrent) == 2


def test_requests_are_granted_fifo() -> None:
    sim = Sim()
    resource = Resource(sim, capacity=1)
    order: list[int] = []

    def user(sim: Sim, index: int) -> Generator[Event[Any], Any, None]:
        with resource.request() as slot:
            yield slot
            order.append(index)
            yield sim.delay(1.0)

    for index in range(4):
        sim.spawn(user, index)
    sim.run()
    assert order == [0, 1, 2, 3]


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError, match="capacity"):
        Resource(Sim(), capacity=0)


def test_context_manager_releases_on_normal_exit() -> None:
    sim = Sim()
    resource = Resource(sim, capacity=1)

    def user(sim: Sim) -> Generator[Event[Any], Any, None]:
        with resource.request() as slot:
            yield slot
            yield sim.delay(1.0)

    sim.spawn(user)
    sim.run()
    assert resource.count == 0
    assert resource.queue == []


def test_context_manager_releases_on_error_exit() -> None:
    sim = Sim()
    resource = Resource(sim, capacity=1)

    def failing(sim: Sim) -> Generator[Event[Any], Any, None]:
        with resource.request() as slot:
            yield slot
            raise RuntimeError("boom")

    def observer(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(5.0)
        assert resource.count == 0

    sim.spawn(failing)
    sim.spawn(observer)
    with pytest.raises(RuntimeError, match="boom"):
        sim.run()


def test_priority_resource_orders_by_priority() -> None:
    sim = Sim()
    resource = PriorityResource(sim, capacity=1)
    order: list[str] = []

    def holder(sim: Sim) -> Generator[Event[Any], Any, None]:
        with resource.request(priority=0) as slot:
            yield slot
            yield sim.delay(5.0)

    def low(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(1.0)  # arrive after holder took the slot
        with resource.request(priority=10) as slot:
            yield slot
            order.append("low")
            yield sim.delay(1.0)

    def high(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(2.0)  # arrives later than low but ranks higher
        with resource.request(priority=1) as slot:
            yield slot
            order.append("high")
            yield sim.delay(1.0)

    sim.spawn(holder)
    sim.spawn(low)
    sim.spawn(high)
    sim.run()
    assert order == ["high", "low"]


def test_preemption_wakes_the_preempted_process() -> None:
    sim = Sim()
    resource = PreemptiveResource(sim, capacity=1)
    events: list[Any] = []

    def victim(sim: Sim) -> Generator[Event[Any], Any, None]:
        with resource.request(priority=10) as slot:
            yield slot
            events.append(("acquired", sim.now))
            try:
                yield sim.delay(100.0)
                events.append(("finished", sim.now))
            except Interrupt as interrupt:
                events.append(("preempted", sim.now, interrupt.cause))

    def preemptor(sim: Sim) -> Generator[Event[Any], Any, None]:
        yield sim.delay(5.0)
        with resource.request(priority=0) as slot:
            yield slot
            events.append(("preemptor-in", sim.now))
            yield sim.delay(1.0)

    sim.spawn(victim)
    sim.spawn(preemptor)
    sim.run()
    assert ("acquired", 0) in events
    preempted = [event for event in events if event[0] == "preempted"]
    assert len(preempted) == 1
    assert preempted[0][1] == 5.0
    assert isinstance(preempted[0][2], Preempted)


def test_interrupted_request_before_grant_is_dequeued() -> None:
    """A waiter interrupted before its request triggers leaks no capacity."""
    sim = Sim()
    resource = Resource(sim, capacity=1)
    granted: list[str] = []

    def holder(sim: Sim) -> Generator[Event[Any], Any, None]:
        with resource.request() as slot:
            yield slot
            granted.append("holder")
            yield sim.delay(100.0)

    def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
        with resource.request() as slot:
            try:
                yield slot
                granted.append("waiter")
            except Interrupt:
                granted.append("waiter-interrupted")

    def canceller(sim: Sim, target: Process[Any]) -> Generator[Event[Any], Any, None]:
        yield sim.delay(5.0)
        target.interrupt()

    sim.spawn(holder)
    waiter_process = sim.spawn(waiter)
    sim.spawn(canceller, waiter_process)
    sim.run()

    assert granted == ["holder", "waiter-interrupted"]
    # The abandoned waiter left the queue and never consumed a slot.
    assert resource.queue == []
    assert resource.count == 0
