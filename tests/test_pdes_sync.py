"""Safe-window synchronizer: threaded == sequential, progress, fail-fast (3.3)."""

import sys
import warnings
from collections.abc import Generator
from typing import Any

import pytest

from llmsim.core.events import Event
from llmsim.core.sim import Sim
from llmsim.parallel.pdes import RunMode, ShardedSim, ShardError, ShardPorts
from llmsim.trace import Tracer, trace
from tests.test_pdes_equivalence import assert_shard_traces_equal

_MASTER = 20260712


def _pipeline(
    shards: int = 2,
) -> tuple[ShardedSim, list[tuple[float, int]], dict[int, Tracer]]:
    """A chain: shard 0 produces, each shard relays to the next, last collects."""
    topo = ShardedSim(shards, master_seed=_MASTER)
    received: list[tuple[float, int]] = []
    tracers: dict[int, Tracer] = {}

    @topo.shard(0)
    def build_head(sim: Sim, ports: ShardPorts) -> None:
        tracers[0] = trace(sim)
        out = ports.out("link_0", lookahead=1.0)

        def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
            for part in range(12):
                yield sim.delay(sim.rng.expovariate(1.0))
                out.send(part, delay=1.0 + sim.rng.random())

        sim.spawn(producer)

    def _make_relay(shard_index: int) -> None:
        @topo.shard(shard_index)
        def build_relay(sim: Sim, ports: ShardPorts) -> None:
            tracers[shard_index] = trace(sim)
            inbox = ports.inbox(f"link_{shard_index - 1}")
            out = ports.out(f"link_{shard_index}", lookahead=1.0)

            def relay(sim: Sim) -> Generator[Event[Any], Any, None]:
                while True:
                    part = yield inbox.get()
                    yield sim.delay(0.25)
                    out.send(part, delay=1.0)

            sim.spawn(relay)

    for shard_index in range(1, shards - 1):
        _make_relay(shard_index)

    @topo.shard(shards - 1)
    def build_tail(sim: Sim, ports: ShardPorts) -> None:
        tracers[shards - 1] = trace(sim)
        inbox = ports.inbox(f"link_{shards - 2}")

        def collector(sim: Sim) -> Generator[Event[Any], Any, None]:
            while True:
                part = yield inbox.get()
                received.append((sim.now, part))

        sim.spawn(collector)

    return topo, received, tracers


def _ping_pong() -> tuple[ShardedSim, list[tuple[float, str, int]]]:
    """Two shards bouncing a token: every horizon involves finite lookahead."""
    topo = ShardedSim(2, master_seed=_MASTER)
    log: list[tuple[float, str, int]] = []

    @topo.shard(0)
    def build_left(sim: Sim, ports: ShardPorts) -> None:
        out = ports.out("ping", lookahead=1.0)
        inbox = ports.inbox("pong")

        def player(sim: Sim) -> Generator[Event[Any], Any, None]:
            out.send(0, delay=1.0)
            while True:
                count = yield inbox.get()
                log.append((sim.now, "left", count))
                if count >= 9:
                    return
                out.send(count + 1, delay=1.0)

        sim.spawn(player)

    @topo.shard(1)
    def build_right(sim: Sim, ports: ShardPorts) -> None:
        inbox = ports.inbox("ping")
        out = ports.out("pong", lookahead=1.0)

        def player(sim: Sim) -> Generator[Event[Any], Any, None]:
            while True:
                count = yield inbox.get()
                log.append((sim.now, "right", count))
                out.send(count + 1, delay=1.0)

        sim.spawn(player)

    return topo, log


# --- Threaded execution is bitwise-equal to the sequential reference. ----------


@pytest.mark.parametrize("shards", [2, 4])
def test_threaded_traces_equal_sequential_reference(shards: int) -> None:
    sequential_topo, sequential_received, sequential_tracers = _pipeline(shards)
    sequential_topo.run(until=60.0, mode="sequential")

    threaded_topo, threaded_received, threaded_tracers = _pipeline(shards)
    threaded_topo.run(until=60.0)

    assert threaded_received == sequential_received
    assert sequential_received  # the model actually did something
    assert_shard_traces_equal(threaded_tracers, sequential_tracers)


def test_ping_pong_threaded_equals_sequential() -> None:
    sequential_topo, sequential_log = _ping_pong()
    sequential_topo.run(until=100.0, mode="sequential")
    threaded_topo, threaded_log = _ping_pong()
    threaded_topo.run(until=100.0)
    assert threaded_log == sequential_log
    assert len(sequential_log) == 10


def test_threaded_same_seed_same_result_across_runs() -> None:
    first_topo, first_received, _ = _pipeline(2)
    first_topo.run(until=60.0)
    second_topo, second_received, _ = _pipeline(2)
    second_topo.run(until=60.0)
    assert first_received == second_received


# --- Progress: the no-livelock case from the spec. -----------------------------


def _no_livelock_topology() -> tuple[ShardedSim, list[float]]:
    """A message with no earlier local event anywhere: the livelock trap.

    The design doc's literal horizon formula (`H = min(bounds, undelivered
    timestamps)` + deliver-strictly-below-H) never delivers this message;
    the progress-safe horizon must.
    """
    topo = ShardedSim(2, master_seed=_MASTER)
    received: list[float] = []

    @topo.shard(0)
    def build_sender(sim: Sim, ports: ShardPorts) -> None:
        out = ports.out("only", lookahead=1.0)

        def one_shot(sim: Sim) -> Generator[Event[Any], Any, None]:
            out.send("wake", delay=1.0)
            return
            yield  # pragma: no cover -- makes this a generator

        sim.spawn(one_shot)

    @topo.shard(1)
    def build_receiver(sim: Sim, ports: ShardPorts) -> None:
        inbox = ports.inbox("only")

        def waiter(sim: Sim) -> Generator[Event[Any], Any, None]:
            yield inbox.get()
            received.append(sim.now)

        sim.spawn(waiter)

    return topo, received


@pytest.mark.parametrize("mode", ["sequential", "threads"])
def test_undelivered_message_with_no_earlier_local_event_progresses(
    mode: RunMode,
) -> None:
    topo, received = _no_livelock_topology()
    topo.run(until=10.0, mode=mode)  # must terminate, not livelock
    assert received == [1.0]


# --- Termination and until-boundary. --------------------------------------------


@pytest.mark.parametrize("mode", ["sequential", "threads"])
def test_until_is_exclusive(mode: RunMode) -> None:
    topo, received, _ = _pipeline(2)
    topo.run(until=0.001, mode=mode)
    assert received == []


@pytest.mark.parametrize("mode", ["sequential", "threads"])
def test_empty_shard_topology_terminates(mode: RunMode) -> None:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        pass

    @topo.shard(1)
    def build_b(sim: Sim, ports: ShardPorts) -> None:
        pass

    topo.run(until=10.0, mode=mode)


def test_single_shard_topology_runs() -> None:
    topo = ShardedSim(1, master_seed=_MASTER)
    ticks: list[float] = []

    @topo.shard(0)
    def build_only(sim: Sim, ports: ShardPorts) -> None:
        def ticker(sim: Sim) -> Generator[Event[Any], Any, None]:
            for _ in range(3):
                yield sim.delay(1.0)
                ticks.append(sim.now)

        sim.spawn(ticker)

    topo.run(until=10.0)
    assert ticks == [1.0, 2.0, 3.0]


# --- Fail-fast: a failing shard names itself and joins everyone. ----------------


@pytest.mark.parametrize("mode", ["sequential", "threads"])
def test_failing_shard_raises_named_error(mode: RunMode) -> None:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_ok(sim: Sim, ports: ShardPorts) -> None:
        def ticker(sim: Sim) -> Generator[Event[Any], Any, None]:
            while True:
                yield sim.delay(1.0)

        sim.spawn(ticker)

    @topo.shard(1)
    def build_broken(sim: Sim, ports: ShardPorts) -> None:
        def bomb(sim: Sim) -> Generator[Event[Any], Any, None]:
            yield sim.delay(2.5)
            raise ValueError("model blew up")

        sim.spawn(bomb)

    if mode == "sequential":
        with pytest.raises(ValueError, match="model blew up"):
            topo.run(until=10.0, mode="sequential")
    else:
        with pytest.raises(ShardError, match="shard 1") as excinfo:
            topo.run(until=10.0)
        assert isinstance(excinfo.value.__cause__, ValueError)


# --- GIL-build warning. -----------------------------------------------------------


def test_gil_build_warns_prominently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: True)
    topo, _, _ = _pipeline(2)
    with pytest.warns(RuntimeWarning, match="not be faster"):
        topo.run(until=5.0)


def test_free_threaded_build_does_not_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "_is_gil_enabled", lambda: False)
    topo, _, _ = _pipeline(2)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        topo.run(until=5.0)
