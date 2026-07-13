"""Trace-equivalence suite: grid conveyor, horizon boundary, ownership (3.4)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim.core.events import Event
from llmsim.core.sim import Sim
from llmsim.parallel.pdes import ShardedSim, ShardError, ShardPorts
from llmsim.resources.resource import Resource
from llmsim.trace import Tracer, trace

_MASTER = 20260712

_ROWS = 16
_COLS = 6
_ITEMS = 12
_SEGMENT_TRANSIT = 1.0
_ARRIVAL_MEAN = 2.0


def make_grid_topology(
    shards: int,
) -> tuple[ShardedSim, dict[str, float], dict[int, Tracer]]:
    """The sharded grid conveyor: row bands, transit time as lookahead.

    The canonical benchmark model partitioned for PDES: items traverse row 0
    left-to-right then descend the last column. Row bands map to shards;
    an item crossing a band boundary becomes a channel message carrying
    ``(item id, entered_at)`` — plain data — with the segment transit time
    (1.0) as the natural lookahead.
    """
    assert _ROWS % shards == 0
    band_height = _ROWS // shards
    topo = ShardedSim(shards, master_seed=_MASTER)
    kpis: dict[str, float] = {"delivered": 0.0, "total_transit": 0.0}
    tracers: dict[int, Tracer] = {}

    def band_rows(shard_index: int) -> range:
        return range(shard_index * band_height, (shard_index + 1) * band_height)

    def band_route(shard_index: int) -> list[tuple[int, int]]:
        route: list[tuple[int, int]] = []
        for row in band_rows(shard_index):
            if row == 0:
                route.extend((0, col) for col in range(_COLS))
            else:
                route.append((row, _COLS - 1))
        return route

    def make_builder(shard_index: int) -> None:
        is_first = shard_index == 0
        is_last = shard_index == shards - 1
        route = band_route(shard_index)

        @topo.shard(shard_index)
        def build_band(sim: Sim, ports: ShardPorts) -> None:
            tracers[shard_index] = trace(sim)
            segments = {cell: Resource(sim, capacity=1) for cell in route}
            out = (
                None
                if is_last
                else ports.out(f"band_{shard_index}", lookahead=_SEGMENT_TRANSIT)
            )

            def walker(
                sim: Sim, item_id: int, entered_at: float
            ) -> Generator[Event[Any], Any, None]:
                for cell in route:
                    with segments[cell].request() as slot:
                        yield slot
                        yield sim.delay(_SEGMENT_TRANSIT)
                if out is not None:
                    out.send((item_id, entered_at), delay=_SEGMENT_TRANSIT)
                else:
                    kpis["delivered"] += 1.0
                    kpis["total_transit"] += sim.now - entered_at

            if is_first:

                def feeder(sim: Sim) -> Generator[Event[Any], Any, None]:
                    for item_id in range(_ITEMS):
                        yield sim.delay(sim.rng.expovariate(1.0 / _ARRIVAL_MEAN))
                        sim.spawn(walker, item_id, sim.now)

                sim.spawn(feeder)
            else:
                inbox = ports.inbox(f"band_{shard_index - 1}")

                def receiver(sim: Sim) -> Generator[Event[Any], Any, None]:
                    while True:
                        item_id, entered_at = yield inbox.get()
                        sim.spawn(walker, item_id, entered_at)

                sim.spawn(receiver)

    for shard_index in range(shards):
        make_builder(shard_index)
    return topo, kpis, tracers


def assert_shard_traces_equal(
    left: dict[int, Tracer], right: dict[int, Tracer]
) -> None:
    """Assert bitwise per-shard trace equality with a per-shard message."""
    assert left.keys() == right.keys()
    for shard_index in sorted(left):
        assert left[shard_index].records == right[shard_index].records, (
            f"shard {shard_index} trace diverged"
        )


@pytest.mark.parametrize("shards", [1, 2, 4, 8])
def test_grid_conveyor_threaded_equals_sequential_bitwise(shards: int) -> None:
    sequential_topo, sequential_kpis, sequential_tracers = make_grid_topology(shards)
    sequential_topo.run(until=400.0, mode="sequential")

    threaded_topo, threaded_kpis, threaded_tracers = make_grid_topology(shards)
    threaded_topo.run(until=400.0)

    assert sequential_kpis["delivered"] == _ITEMS  # the model completed
    assert threaded_kpis == sequential_kpis
    assert_shard_traces_equal(threaded_tracers, sequential_tracers)


@pytest.mark.parametrize("shards", [2, 4])
def test_grid_conveyor_repeated_threaded_runs_identical(shards: int) -> None:
    first_topo, first_kpis, first_tracers = make_grid_topology(shards)
    first_topo.run(until=400.0)
    second_topo, second_kpis, second_tracers = make_grid_topology(shards)
    second_topo.run(until=400.0)
    assert first_kpis == second_kpis
    assert_shard_traces_equal(first_tracers, second_tracers)


# --- The adversarial horizon-boundary model. -------------------------------------


def make_horizon_boundary_topology() -> tuple[
    ShardedSim, list[tuple[float, str, Any]], dict[int, Tracer]
]:
    """Messages land exactly at the horizon and tie with local events.

    Shard A ticks at integer times and sends with delay exactly equal to the
    lookahead, so every message timestamp coincides with a horizon value and
    with shard B's own integer-time local ticks — the strict ``< H`` deferral
    and deterministic tie-breaking are both exercised every single round.
    """
    topo = ShardedSim(2, master_seed=_MASTER)
    log: list[tuple[float, str, Any]] = []
    tracers: dict[int, Tracer] = {}

    @topo.shard(0)
    def build_sender(sim: Sim, ports: ShardPorts) -> None:
        tracers[0] = trace(sim)
        out = ports.out("edge", lookahead=1.0)

        def ticker(sim: Sim) -> Generator[Event[Any], Any, None]:
            for tick in range(8):
                yield sim.delay(1.0)
                out.send(tick, delay=1.0)  # timestamp == a future horizon

        sim.spawn(ticker)

    @topo.shard(1)
    def build_receiver(sim: Sim, ports: ShardPorts) -> None:
        tracers[1] = trace(sim)
        inbox = ports.inbox("edge")

        def local_ticker(sim: Sim) -> Generator[Event[Any], Any, None]:
            for _ in range(10):
                yield sim.delay(1.0)  # local events tie with delivery times
                log.append((sim.now, "local", None))

        def receiver(sim: Sim) -> Generator[Event[Any], Any, None]:
            while True:
                tick = yield inbox.get()
                log.append((sim.now, "message", tick))

        sim.spawn(local_ticker)
        sim.spawn(receiver)

    return topo, log, tracers


def test_horizon_boundary_threaded_equals_sequential() -> None:
    sequential_topo, sequential_log, sequential_tracers = (
        make_horizon_boundary_topology()
    )
    sequential_topo.run(until=50.0, mode="sequential")
    threaded_topo, threaded_log, threaded_tracers = make_horizon_boundary_topology()
    threaded_topo.run(until=50.0)

    assert threaded_log == sequential_log
    assert_shard_traces_equal(threaded_tracers, sequential_tracers)
    # Every message arrived, at its exact stamped time (tick k sent at k+1,
    # arriving k+2), interleaved deterministically with the local ties.
    messages = [
        (when, tick) for when, kind, tick in sequential_log if kind == "message"
    ]
    assert messages == [(float(tick + 2), tick) for tick in range(8)]


def test_message_and_local_tie_order_is_stable() -> None:
    """At equal timestamps the interleaving is fixed by deterministic keys."""
    first_topo, first_log, _ = make_horizon_boundary_topology()
    first_topo.run(until=50.0)
    second_topo, second_log, _ = make_horizon_boundary_topology()
    second_topo.run(until=50.0)
    assert first_log == second_log
    tie_times = {when for when, kind, _ in first_log if kind == "message"}
    local_times = {when for when, kind, _ in first_log if kind == "local"}
    assert tie_times & local_times  # genuine ties exist at shared timestamps


# --- Ownership violations: caught by the debug-mode owner-thread guard. ----------


def test_foreign_resource_touch_trips_debug_guard() -> None:
    """A shard requesting another shard's Resource fails loudly, not silently."""
    topo = ShardedSim(2, master_seed=_MASTER, debug=True)
    shared: dict[str, Resource] = {}

    @topo.shard(0)
    def build_owner(sim: Sim, ports: ShardPorts) -> None:
        ports.out("unused", lookahead=1.0)
        shared["resource"] = Resource(sim, capacity=1)

        def keep_alive(sim: Sim) -> Generator[Event[Any], Any, None]:
            yield sim.delay(5.0)

        sim.spawn(keep_alive)

    @topo.shard(1)
    def build_intruder(sim: Sim, ports: ShardPorts) -> None:
        ports.inbox("unused")

        def intruder(sim: Sim) -> Generator[Event[Any], Any, None]:
            yield sim.delay(1.0)
            shared["resource"].request()  # foreign Sim: cross-thread schedule

        sim.spawn(intruder)

    with pytest.raises(ShardError, match="shard 1") as excinfo:
        topo.run(until=10.0)
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert "one thread" in str(excinfo.value.__cause__)


def test_sim_owned_payload_trips_debug_guard_when_touched() -> None:
    """Sending a Sim-owned object as a payload is caught when misused."""
    topo = ShardedSim(2, master_seed=_MASTER, debug=True)

    @topo.shard(0)
    def build_sender(sim: Sim, ports: ShardPorts) -> None:
        out = ports.out("events", lookahead=1.0)

        def sender(sim: Sim) -> Generator[Event[Any], Any, None]:
            yield sim.delay(1.0)
            out.send(sim.event(), delay=1.0)  # a live, shard-0-owned Event

        sim.spawn(sender)

    @topo.shard(1)
    def build_toucher(sim: Sim, ports: ShardPorts) -> None:
        inbox = ports.inbox("events")

        def toucher(sim: Sim) -> Generator[Event[Any], Any, None]:
            foreign_event = yield inbox.get()
            foreign_event.succeed()  # schedules on shard 0's Sim -> guard

        sim.spawn(toucher)

    with pytest.raises(ShardError, match="shard 1") as excinfo:
        topo.run(until=10.0)
    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert "one thread" in str(excinfo.value.__cause__)


@pytest.mark.parametrize("mode", ["sequential", "threads"])
def test_awaiting_foreign_event_rejected_at_the_yield(mode: str) -> None:
    """Yielding another shard's event is rejected deterministically.

    The debug schedule-guard cannot catch this class reliably — the foreign
    event's state is read cross-thread and one interleaving resumes the
    process locally and silently — so the process driver rejects the yield
    itself, in both modes, debug or not.
    """
    topo = ShardedSim(2, master_seed=_MASTER)
    shared: dict[str, Event[Any]] = {}

    @topo.shard(0)
    def build_owner(sim: Sim, ports: ShardPorts) -> None:
        ports.out("unused", lookahead=1.0)
        shared["event"] = sim.event()

        def triggerer(sim: Sim) -> Generator[Event[Any], Any, None]:
            yield sim.delay(50.0)
            shared["event"].succeed("value")

        sim.spawn(triggerer)

    @topo.shard(1)
    def build_awaiter(sim: Sim, ports: ShardPorts) -> None:
        ports.inbox("unused")

        def awaiter(sim: Sim) -> Generator[Event[Any], Any, None]:
            yield sim.delay(1.0)
            yield shared["event"]  # awaits a foreign shard's event

        sim.spawn(awaiter)

    if mode == "sequential":
        with pytest.raises(RuntimeError, match="own simulation"):
            topo.run(until=100.0, mode="sequential")
    else:
        with pytest.raises(ShardError, match="shard 1") as excinfo:
            topo.run(until=100.0)
        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert "own simulation" in str(excinfo.value.__cause__)
