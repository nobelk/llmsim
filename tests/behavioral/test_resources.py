"""Ported from SimPy 3's ``tests/test_resources.py`` (adapted to llmsim)."""

from collections.abc import Generator
from typing import Any, cast

import pytest

from llmsim import (
    Container,
    FilterStore,
    Interrupt,
    PreemptiveResource,
    PriorityResource,
    PriorityStore,
    Process,
    Resource,
    Sim,
    Store,
)
from llmsim.resources import Preempted, PriorityItem
from llmsim.resources.resource import SortedQueue

Proc = Generator[Any, Any, Any]


#
# Resource
#
def test_resource(sim: Sim, log: list[Any]) -> None:
    """A resource limits concurrent users; releases wake the next waiter."""

    def pem(sim: Sim, name: str, resource: Resource, log: list[Any]) -> Proc:
        req = resource.request()
        yield req
        assert resource.count == 1
        yield sim.delay(1)
        resource.release(req)
        log.append((name, sim.now))

    resource = Resource(sim, capacity=1)
    assert resource.capacity == 1
    assert resource.count == 0
    sim.spawn(pem, "a", resource, log)
    sim.spawn(pem, "b", resource, log)
    sim.run()
    assert log == [("a", 1), ("b", 2)]


def test_resource_capacity(sim: Sim) -> None:
    """A resource capacity must be positive."""
    with pytest.raises(ValueError, match="capacity must be > 0"):
        Resource(sim, 0)


def test_resource_context_manager(sim: Sim, log: list[Any]) -> None:
    """A request works as a context manager, releasing on exit."""

    def pem(sim: Sim, name: str, resource: Resource, log: list[Any]) -> Proc:
        with resource.request() as request:
            yield request
            yield sim.delay(1)
        log.append((name, sim.now))

    resource = Resource(sim, capacity=1)
    sim.spawn(pem, "a", resource, log)
    sim.spawn(pem, "b", resource, log)
    sim.run()
    assert log == [("a", 1), ("b", 2)]


def test_resource_slots(sim: Sim, log: list[Any]) -> None:
    """A multi-slot resource admits ``capacity`` users at a time."""

    def pem(sim: Sim, name: str, resource: Resource, log: list[Any]) -> Proc:
        with resource.request() as req:
            yield req
            log.append((name, sim.now))
            yield sim.delay(1)

    resource = Resource(sim, capacity=3)
    for i in range(9):
        sim.spawn(pem, str(i), resource, log)
    sim.run()
    assert log == [
        ("0", 0),
        ("1", 0),
        ("2", 0),
        ("3", 1),
        ("4", 1),
        ("5", 1),
        ("6", 2),
        ("7", 2),
        ("8", 2),
    ]


def test_resource_continue_after_interrupt(sim: Sim) -> None:
    """An interrupted waiter may keep waiting for the resource afterwards."""

    def pem(sim: Sim, res: Resource) -> Proc:
        with res.request() as req:
            yield req
            yield sim.delay(1)

    def victim(sim: Sim, res: Resource) -> Proc:
        evt = res.request()
        try:
            yield evt
            pytest.fail("Should not have gotten the resource.")
        except Interrupt:
            yield evt
            res.release(evt)
            assert sim.now == 1

    def interruptor(sim: Sim, proc: Process[Any]) -> Proc:
        proc.interrupt()
        return
        yield

    res = Resource(sim, 1)
    sim.spawn(pem, res)
    proc = sim.spawn(victim, res)
    sim.spawn(interruptor, proc)
    sim.run()


def test_resource_release_after_interrupt(sim: Sim) -> None:
    """An interrupted waiter that abandons the request must still release it."""

    def blocker(sim: Sim, res: Resource) -> Proc:
        with res.request() as req:
            yield req
            yield sim.delay(1)

    def victim(sim: Sim, res: Resource) -> Proc:
        evt = res.request()
        try:
            yield evt
            pytest.fail("Should not have gotten the resource.")
        except Interrupt:
            res.release(evt)
            assert sim.now == 0

    def interruptor(sim: Sim, proc: Process[Any]) -> Proc:
        proc.interrupt()
        return
        yield

    res = Resource(sim, 1)
    sim.spawn(blocker, res)
    victim_proc = sim.spawn(victim, res)
    sim.spawn(interruptor, victim_proc)
    sim.run()


def test_resource_immediate_requests(sim: Sim) -> None:
    """Re-requesting immediately after release yields to already-waiting procs."""

    def child(sim: Sim, res: Resource) -> Proc:
        result = []
        for _ in range(3):
            with res.request() as req:
                yield req
                result.append(sim.now)
                yield sim.delay(1)
        return result

    def parent(sim: Sim) -> Proc:
        res = Resource(sim, 1)
        child_a = sim.spawn(child, res)
        child_b = sim.spawn(child, res)
        a_acquire_times = yield child_a
        b_acquire_times = yield child_b
        assert a_acquire_times == [0, 2, 4]
        assert b_acquire_times == [1, 3, 5]

    sim.spawn(parent)
    sim.run()


def test_resource_cm_exception(sim: Sim, log: list[Any]) -> None:
    """A resource is released even if the holding process raises."""

    def process(sim: Sim, resource: Resource, log: list[Any], raise_: bool) -> Proc:
        with resource.request() as req:
            yield req
            yield sim.delay(1)
            log.append(sim.now)
            if raise_:
                with pytest.raises(ValueError, match="Foo"):
                    raise ValueError("Foo")

    resource = Resource(sim, 1)
    sim.spawn(process, resource, log, True)
    sim.spawn(process, resource, log, False)
    sim.run()
    assert log == [1, 2]


def test_resource_with_condition(sim: Sim) -> None:
    """A request can be composed with a timeout in a condition."""

    def process(sim: Sim, resource: Resource) -> Proc:
        with resource.request() as res_event:
            result = yield res_event | sim.delay(1)
            assert res_event in result

    resource = Resource(sim, 1)
    sim.spawn(process, resource)
    sim.run()


def test_resource_with_priority_queue(sim: Sim) -> None:
    """A priority resource grants queued requests by ascending priority."""

    def process(
        sim: Sim,
        delay: float,
        resource: PriorityResource,
        priority: int,
        res_time: float,
    ) -> Proc:
        yield sim.delay(delay)
        req = resource.request(priority=priority)
        yield req
        assert sim.now == res_time
        yield sim.delay(5)
        resource.release(req)

    resource = PriorityResource(sim, capacity=1)
    sim.spawn(process, 0, resource, 2, 0)
    sim.spawn(process, 2, resource, 3, 10)
    sim.spawn(process, 2, resource, 3, 15)
    sim.spawn(process, 4, resource, 1, 5)
    sim.run()


def test_sorted_queue_maxlen(sim: Sim) -> None:
    """A bounded priority queue rejects concurrent requests past its limit."""
    resource = PriorityResource(sim, capacity=1)
    cast(SortedQueue, resource.put_queue).maxlen = 1

    def process(sim: Sim, resource: PriorityResource) -> Proc:
        resource.request(priority=1)
        resource.request(priority=1)
        # Divergence: llmsim's message is "cannot append request: queue is full"
        # vs SimPy 3's "Cannot append event. Queue is full."; both RuntimeError.
        with pytest.raises(RuntimeError, match="queue is full"):
            resource.request(priority=1)
        yield sim.delay(0)

    sim.spawn(process, resource)
    sim.run()


def test_get_users(sim: Sim) -> None:
    """A resource exposes its current users and its pending queue."""

    def process(sim: Sim, resource: Resource) -> Proc:
        with resource.request() as req:
            yield req
            yield sim.delay(1)

    resource = Resource(sim, 1)
    procs = [sim.spawn(process, resource) for _ in range(3)]
    sim.run(until=1)
    assert [evt.proc for evt in resource.users] == procs[0:1]
    assert [evt.proc for evt in resource.queue] == procs[1:]

    sim.run(until=2)
    assert [evt.proc for evt in resource.users] == procs[1:2]
    assert [evt.proc for evt in resource.queue] == procs[2:]


#
# PreemptiveResource
#
def test_preemptive_resource(sim: Sim) -> None:
    """A higher-priority request preempts a lower-priority holder."""

    def proc_a(sim: Sim, resource: PreemptiveResource, prio: int) -> Proc:
        try:
            with resource.request(priority=prio) as req:
                yield req
                pytest.fail("Should have received an interrupt/preemption.")
        except Interrupt:
            pass

    def proc_b(sim: Sim, resource: PreemptiveResource, prio: int) -> Proc:
        with resource.request(priority=prio) as req:
            yield req

    resource = PreemptiveResource(sim, 1)
    sim.spawn(proc_a, resource, 1)
    sim.spawn(proc_b, resource, 0)
    sim.run()


def test_preemptive_resource_timeout_0(sim: Sim) -> None:
    """Preemption works even when the holder yields a zero-delay timeout."""

    def proc_a(sim: Sim, resource: PreemptiveResource, prio: int) -> Proc:
        with resource.request(priority=prio) as req:
            try:
                yield req
                yield sim.delay(1)
                pytest.fail("Should have received an interrupt/preemption.")
            except Interrupt:
                pass
        yield sim.event()

    def proc_b(sim: Sim, resource: PreemptiveResource, prio: int) -> Proc:
        with resource.request(priority=prio) as req:
            yield req

    resource = PreemptiveResource(sim, 1)
    sim.spawn(proc_a, resource, 1)
    sim.spawn(proc_b, resource, 0)
    sim.run()


def test_mixed_preemption(sim: Sim, log: list[Any]) -> None:
    """Preemption respects priority, arrival time, and the preempt flag."""

    def p(
        sim: Sim,
        index: int,
        res: PreemptiveResource,
        delay: float,
        prio: int,
        preempt: bool,
        log: list[Any],
    ) -> Proc:
        yield sim.delay(delay)
        with res.request(priority=prio, preempt=preempt) as req:
            try:
                yield req
                yield sim.delay(2)
                log.append((sim.now, index))
            except Interrupt as interrupt:
                assert isinstance(interrupt.cause, Preempted)
                log.append(
                    (sim.now, index, (interrupt.cause.by, interrupt.cause.usage_since))
                )

    res = PreemptiveResource(sim, 1)
    sim.spawn(p, 0, res, 0, 2, True, log)
    sim.spawn(p, 1, res, 0, 2, True, log)
    sim.spawn(p, 2, res, 1, 1, False, log)
    p3 = sim.spawn(p, 3, res, 3, 0, True, log)
    sim.spawn(p, 4, res, 4, 3, True, log)
    sim.run()
    assert log == [
        (2, 0),
        (3, 2, (p3, 2)),
        (5, 3),
        (7, 1),
        (9, 4),
    ]


#
# Container
#
def test_container(sim: Sim, log: list[Any]) -> None:
    """Container puts and gets block until the level can satisfy them."""

    def putter(sim: Sim, buf: Container, log: list[Any]) -> Proc:
        yield sim.delay(1)
        while True:
            yield buf.put(2)
            log.append(("p", sim.now))
            yield sim.delay(1)

    def getter(sim: Sim, buf: Container, log: list[Any]) -> Proc:
        yield buf.get(1)
        log.append(("g", sim.now))
        yield sim.delay(1)
        yield buf.get(1)
        log.append(("g", sim.now))

    buf = Container(sim, init=0, capacity=2)
    sim.spawn(putter, buf, log)
    sim.spawn(getter, buf, log)
    sim.run(until=5)
    assert log == [("p", 1), ("g", 1), ("g", 2), ("p", 2)]


def test_container_get_queued(sim: Sim) -> None:
    """Container put/get queues track their waiting processes."""

    def proc(sim: Sim, wait: float, container: Container, what: str) -> Proc:
        yield sim.delay(wait)
        with getattr(container, what)(1) as req:
            yield req

    container = Container(sim, 1)
    p0 = sim.spawn(proc, 0, container, "get")
    sim.spawn(proc, 1, container, "put")
    sim.spawn(proc, 1, container, "put")
    p3 = sim.spawn(proc, 1, container, "put")

    sim.run(until=1)
    assert [ev.proc for ev in container.put_queue] == []
    assert [ev.proc for ev in container.get_queue] == [p0]

    sim.run(until=2)
    assert [ev.proc for ev in container.put_queue] == [p3]
    assert [ev.proc for ev in container.get_queue] == []


def test_initial_container_capacity(sim: Sim) -> None:
    """A container defaults to unlimited capacity."""
    container = Container(sim)
    assert container.capacity == float("inf")


def test_container_get_put_bounds(sim: Sim) -> None:
    """Container amounts must be positive."""
    container = Container(sim)
    with pytest.raises(ValueError, match=r"amount.*must be > 0"):
        container.get(-13)
    with pytest.raises(ValueError, match=r"amount.*must be > 0"):
        container.put(-13)


@pytest.mark.parametrize(
    ("error", "args"),
    [
        (None, [2, 1]),
        (None, [1, 1]),
        (None, [1, 0]),
        (ValueError, [1, 2]),
        (ValueError, [0]),
        (ValueError, [-1]),
        (ValueError, [1, -1]),
    ],
)
def test_container_init_capacity(
    sim: Sim, error: type[Exception] | None, args: list[float]
) -> None:
    """Container construction validates capacity and initial level."""
    if error:
        with pytest.raises(error):
            Container(sim, *args)
    else:
        Container(sim, *args)


#
# Store
#
def test_store(sim: Sim) -> None:
    """A store hands over the exact object that was put in."""

    def putter(sim: Sim, store: Store[Any], item: Any) -> Proc:
        yield store.put(item)

    def getter(sim: Sim, store: Store[Any], orig_item: Any) -> Proc:
        item = yield store.get()
        assert item is orig_item

    store: Store[Any] = Store(sim, capacity=2)
    item = object()
    sim.spawn(putter, store, item)
    sim.spawn(getter, store, item)
    sim.run()


@pytest.mark.parametrize("store_type", [Store, FilterStore])
def test_initial_store_capacity(sim: Sim, store_type: type[Store[Any]]) -> None:
    """Stores default to unlimited capacity."""
    store = store_type(sim)
    assert store.capacity == float("inf")


def test_store_capacity(sim: Sim) -> None:
    """A store bounded by capacity blocks puts once full."""
    with pytest.raises(ValueError, match="capacity must be > 0"):
        Store(sim, 0)
    with pytest.raises(ValueError, match="capacity must be > 0"):
        Store(sim, -1)

    capacity = 2
    store: Store[int] = Store(sim, capacity)
    sim.spawn(store.put(i) for i in range(capacity + 1))
    sim.run()
    assert len(store.items) == capacity


def test_store_cancel(sim: Sim) -> None:
    """A get abandoned via its context manager is cancelled cleanly."""
    store: Store[Any] = Store(sim, capacity=1)

    def acquire_implicit_cancel(sim: Sim) -> Proc:
        with store.get():
            yield sim.delay(1)

    sim.spawn(acquire_implicit_cancel)
    sim.run()


def test_priority_store_item_priority(sim: Sim) -> None:
    """A priority store retrieves its smallest items first."""
    pstore: PriorityStore[str] = PriorityStore(sim, 3)
    log: list[str] = []

    def getter(sim: Sim, wait: float) -> Proc:
        yield sim.delay(wait)
        item = yield pstore.get()
        log.append(item)

    sim.spawn(pstore.put(s) for s in "bcadefg")
    sim.spawn(getter, 1)
    sim.spawn(getter, 2)
    sim.spawn(getter, 3)
    sim.run()
    assert log == ["a", "b", "c"]


def test_priority_store_stable_order(sim: Sim) -> None:
    """Equal-priority items are retrieved in insertion order."""
    pstore: PriorityStore[PriorityItem] = PriorityStore(sim, 3)
    log: list[Any] = []

    def getter(sim: Sim, wait: float) -> Proc:
        yield sim.delay(wait)
        _, item = yield pstore.get()
        log.append(item)

    items = [object() for _ in range(3)]
    sim.spawn(pstore.put(PriorityItem(0, item)) for item in items)
    sim.spawn(getter, 1)
    sim.spawn(getter, 2)
    sim.spawn(getter, 3)
    sim.run()
    assert log == items


def test_filter_store(sim: Sim) -> None:
    """A filtered get triggers only once a matching item is available."""

    def pem(sim: Sim) -> Proc:
        store: FilterStore[str] = FilterStore(sim, capacity=2)
        get_event = store.get(lambda item: item == "b")
        yield store.put("a")
        assert not get_event.triggered
        yield store.put("b")
        assert get_event.triggered

    sim.spawn(pem)
    sim.run()


def test_filter_store_get_after_mismatch(sim: Sim) -> None:
    """A filtered get is retried against every item after a put, not just once."""

    def putter(sim: Sim, store: FilterStore[str]) -> Proc:
        yield store.put("spam")
        yield sim.delay(1)
        yield store.put("eggs")

    def getter(sim: Sim, store: FilterStore[str]) -> Proc:
        eggs = store.get(lambda i: i == "eggs")
        spam = store.get(lambda i: i == "spam")
        ret = yield spam | eggs
        assert spam in ret
        assert eggs not in ret
        assert sim.now == 0
        yield eggs
        assert sim.now == 1

    store: FilterStore[str] = FilterStore(sim, capacity=2)
    sim.spawn(getter, store)
    sim.spawn(putter, store)
    sim.run()


def test_filter_calls_best_case(sim: Sim) -> None:
    """The filter runs from the first item until it finds a match."""
    log: list[str] = []

    def log_filter(item: int) -> bool:
        log.append(f"check {item}")
        return True

    store: FilterStore[int] = FilterStore(sim)
    store.items = [1, 2, 3]

    def getter(sim: Sim, store: FilterStore[int]) -> Proc:
        log.append(f"get {(yield store.get(log_filter))}")
        log.append(f"get {(yield store.get(log_filter))}")
        log.append(f"get {(yield store.get(log_filter))}")

    sim.spawn(getter, store)
    sim.run()
    assert log == ["check 1", "get 1", "check 2", "get 2", "check 3", "get 3"]


def test_filter_calls_worst_case(sim: Sim) -> None:
    """The filter is retried over all items after each put until it matches."""
    log: list[str] = []
    store: FilterStore[int] = FilterStore(sim)

    def putter(sim: Sim, store: FilterStore[int]) -> Proc:
        for i in range(4):
            log.append(f"put {i}")
            yield store.put(i)

    def log_filter(item: int) -> bool:
        log.append(f"check {item}")
        return item >= 3

    def getter(sim: Sim, store: FilterStore[int]) -> Proc:
        log.append(f"get {(yield store.get(log_filter))}")

    sim.spawn(getter, store)
    sim.spawn(putter, store)
    sim.run()
    assert log == [
        "put 0", "check 0",
        "put 1", "check 0", "check 1",
        "put 2", "check 0", "check 1", "check 2",
        "put 3", "check 0", "check 1", "check 2", "check 3", "get 3",
    ]  # fmt: skip


def test_immediate_put_request(sim: Sim) -> None:
    """A put that can be satisfied at once does not enter the queue."""
    resource = Resource(sim, capacity=1)
    assert len(resource.users) == 0
    assert len(resource.queue) == 0

    request = resource.request()
    assert request.triggered
    assert len(resource.users) == 1
    assert len(resource.queue) == 0

    request = resource.request()
    assert not request.triggered
    assert len(resource.users) == 1
    assert len(resource.queue) == 1


def test_immediate_get_request(sim: Sim) -> None:
    """A get that can be satisfied at once does not enter the queue."""
    container = Container(sim)
    put = container.put(1)
    assert put.triggered
    assert container.level == 1
    assert len(container.put_queue) == 0

    get = container.get(1)
    assert get.triggered
    assert container.level == 0
    assert len(container.get_queue) == 0

    get = container.get(1)
    assert not get.triggered
    assert len(container.get_queue) == 1
