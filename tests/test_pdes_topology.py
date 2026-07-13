"""ShardedSim topology: validation, seeding, sequential reference (3.2)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim.core.events import Event
from llmsim.core.sim import Sim
from llmsim.parallel.pdes import ShardedSim, ShardPorts, TopologyError
from llmsim.parallel.pdes.channel import LookaheadError
from llmsim.rand.streams import shard_seed
from llmsim.trace import Tracer, trace

_MASTER = 20260712


def _producer_consumer(
    master_seed: int = _MASTER,
) -> tuple[ShardedSim, list[tuple[float, int]], dict[int, Tracer]]:
    """A two-shard pipeline: shard 0 sends ten parts to shard 1."""
    topo = ShardedSim(2, master_seed=master_seed)
    received: list[tuple[float, int]] = []
    tracers: dict[int, Tracer] = {}

    @topo.shard(0)
    def build_producer(sim: Sim, ports: ShardPorts) -> None:
        tracers[0] = trace(sim)
        out = ports.out("a_to_b", lookahead=1.0)

        def producer(sim: Sim) -> Generator[Event[Any], Any, None]:
            for part in range(10):
                yield sim.delay(0.7)
                out.send(part, delay=1.0)

        sim.spawn(producer)

    @topo.shard(1)
    def build_consumer(sim: Sim, ports: ShardPorts) -> None:
        tracers[1] = trace(sim)
        inbox = ports.inbox("a_to_b")

        def consumer(sim: Sim) -> Generator[Event[Any], Any, None]:
            while True:
                part = yield inbox.get()
                received.append((sim.now, part))

        sim.spawn(consumer)

    return topo, received, tracers


# --- Construction-time validation. ---------------------------------------------


def test_shard_count_must_be_positive() -> None:
    with pytest.raises(TopologyError, match="shards"):
        ShardedSim(0, master_seed=_MASTER)


def test_master_seed_is_required_and_int() -> None:
    with pytest.raises(TypeError):
        ShardedSim(2)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="master_seed"):
        ShardedSim(2, master_seed="7")  # type: ignore[arg-type]


def test_duplicate_builder_rejected() -> None:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        pass

    with pytest.raises(TopologyError, match="already has a builder"):

        @topo.shard(0)
        def build_b(sim: Sim, ports: ShardPorts) -> None:
            pass


def test_out_of_range_shard_index_rejected() -> None:
    topo = ShardedSim(2, master_seed=_MASTER)
    with pytest.raises(TopologyError, match="out of range"):
        topo.shard(2)


def test_missing_builder_rejected_at_run() -> None:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        pass

    with pytest.raises(TopologyError, match=r"shard\(s\) \[1\] have no builder"):
        topo.run(until=1.0, mode="sequential")


def _one_sided_topology(declare: str) -> ShardedSim:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        if declare == "out":
            ports.out("dangling", lookahead=1.0)

    @topo.shard(1)
    def build_b(sim: Sim, ports: ShardPorts) -> None:
        if declare == "inbox":
            ports.inbox("dangling")

    return topo


def test_sender_without_receiver_rejected() -> None:
    with pytest.raises(TopologyError, match="no receiver"):
        _one_sided_topology("out").run(until=1.0, mode="sequential")


def test_receiver_without_sender_rejected() -> None:
    with pytest.raises(TopologyError, match="no sender"):
        _one_sided_topology("inbox").run(until=1.0, mode="sequential")


def test_self_channel_rejected() -> None:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        ports.out("loop", lookahead=1.0)
        ports.inbox("loop")

    @topo.shard(1)
    def build_b(sim: Sim, ports: ShardPorts) -> None:
        pass

    with pytest.raises(TopologyError, match="itself"):
        topo.run(until=1.0, mode="sequential")


@pytest.mark.parametrize("mode", ["sequential", "threads"])
def test_duplicate_channel_sender_rejected(mode: str) -> None:
    """Construction-time validation raises the same error in both modes."""
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        ports.out("dup", lookahead=1.0)

    @topo.shard(1)
    def build_b(sim: Sim, ports: ShardPorts) -> None:
        ports.out("dup", lookahead=1.0)

    with pytest.raises(TopologyError, match="already has a sender"):
        topo.run(until=1.0, mode=mode)  # type: ignore[arg-type]


def test_bad_lookahead_raises_unwrapped_in_threaded_mode() -> None:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        ports.out("bad", lookahead=-1.0)

    @topo.shard(1)
    def build_b(sim: Sim, ports: ShardPorts) -> None:
        ports.inbox("bad")

    with pytest.raises(LookaheadError, match="lookahead must be > 0"):
        topo.run(until=1.0, mode="threads")


def test_non_positive_lookahead_rejected_via_ports() -> None:
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        ports.out("bad", lookahead=0.0)

    @topo.shard(1)
    def build_b(sim: Sim, ports: ShardPorts) -> None:
        ports.inbox("bad")

    with pytest.raises(LookaheadError, match="lookahead must be > 0"):
        topo.run(until=1.0, mode="sequential")


# --- Sequential reference runner: the oracle. -----------------------------------


def test_sequential_pipeline_delivers_in_order() -> None:
    topo, received, _ = _producer_consumer()
    topo.run(until=100.0, mode="sequential")
    assert [part for _, part in received] == list(range(10))
    # Part k is sent at 0.7 * (k + 1) and arrives one lookahead later.
    for k, (arrival, _) in enumerate(received):
        assert arrival == pytest.approx(0.7 * (k + 1) + 1.0)


def test_sequential_same_seed_same_trace() -> None:
    first_topo, first_received, first_tracers = _producer_consumer()
    first_topo.run(until=100.0, mode="sequential")
    second_topo, second_received, second_tracers = _producer_consumer()
    second_topo.run(until=100.0, mode="sequential")
    assert first_received == second_received
    assert first_tracers[0].records == second_tracers[0].records
    assert first_tracers[1].records == second_tracers[1].records


def test_until_bounds_execution() -> None:
    topo, received, _ = _producer_consumer()
    # Part 0 arrives at 1.7, part 1 at 2.4; until=2.4 excludes events at 2.4.
    topo.run(until=2.4, mode="sequential")
    assert [part for _, part in received] == [0]


def test_shard_streams_use_domain_separated_path() -> None:
    seeds: dict[int, float] = {}
    topo = ShardedSim(2, master_seed=_MASTER)

    @topo.shard(0)
    def build_a(sim: Sim, ports: ShardPorts) -> None:
        seeds[0] = sim.rng.random()

    @topo.shard(1)
    def build_b(sim: Sim, ports: ShardPorts) -> None:
        seeds[1] = sim.rng.random()

    topo.run(until=1.0, mode="sequential")
    import random

    assert seeds[0] == random.Random(shard_seed(_MASTER, 0)).random()
    assert seeds[1] == random.Random(shard_seed(_MASTER, 1)).random()
