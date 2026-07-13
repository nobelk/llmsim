"""Model partitioning into shards.

Splits one model into logical processes, each an independent ``Sim`` owned by a
single worker, and defines how a shard advances its local clock within the
current safe window.

The user-facing entry point is :class:`ShardedSim`::

    topo = ShardedSim(shards=2, master_seed=42)

    @topo.shard(0)
    def build_station_a(sim, ports):
        out = ports.out("a_to_b", lookahead=4.0)
        def producer(sim):
            while True:
                yield sim.delay(1.0)
                out.send("part", delay=4.0)
        sim.spawn(producer)

    @topo.shard(1)
    def build_station_b(sim, ports):
        inbox = ports.inbox("a_to_b")
        def consumer(sim):
            while True:
                part = yield inbox.get()
        sim.spawn(consumer)

    topo.run(until=100.0)                    # thread-per-shard
    topo.run(until=100.0, mode="sequential")  # the reference oracle

Builders execute at ``run()`` time — in threaded mode each builder runs on
its shard's own thread, so ``Sim``'s debug owner-thread guard holds inside
shards. Endpoint wiring is validated after every builder has declared its
ports, before any event executes; channel ids are assigned in sorted-name
order so they are deterministic regardless of build interleaving.
"""

import threading
from collections.abc import Callable
from typing import Any, Literal

from llmsim.core.sim import Sim
from llmsim.parallel.pdes.channel import Channel, Inbox, Mailbox
from llmsim.rand.streams import SeedTree

#: A shard builder: receives the shard's ``Sim`` and its ``ShardPorts``.
Builder = Callable[[Sim, "ShardPorts"], Any]

#: Execution modes accepted by :meth:`ShardedSim.run`.
RunMode = Literal["threads", "sequential"]


class TopologyError(ValueError):
    """The sharded topology is mis-wired.

    Raised at construction/validation time — duplicate or missing shard
    builders, channel names without exactly one sender and one receiver,
    endpoints declared on the wrong shard, or a channel from a shard to
    itself. Never raised mid-run: a topology that validates runs.
    """


class ShardError(RuntimeError):
    """One shard failed during a run (fail-fast contract).

    Names the failing shard index and chains the original exception as
    ``__cause__``; all other shard threads are cancelled and joined before
    this is raised, mirroring the Phase 2 replication failure contract.
    """


class ShardPorts:
    """A shard builder's window onto the topology's channels.

    Handed to each builder as its second argument; every endpoint the shard
    uses must be declared through it, which is what makes construction-time
    wiring validation possible.
    """

    __slots__ = ("_shard_index", "_sim", "_registry")

    def __init__(
        self, shard_index: int, sim: Sim, registry: "_EndpointRegistry"
    ) -> None:
        """Bind the ports view to one shard's *sim* and the shared registry."""
        self._shard_index = shard_index
        self._sim = sim
        self._registry = registry

    def out(self, name: str, *, lookahead: float) -> Channel:
        """Declare this shard as the sender of channel *name*."""
        channel = Channel(name=name, lookahead=lookahead, sim=self._sim)
        self._registry.declare_out(self._shard_index, name, channel)
        return channel

    def inbox(self, name: str) -> Inbox:
        """Declare this shard as the receiver of channel *name*."""
        inbox = Inbox(sim=self._sim, name=name)
        self._registry.declare_in(self._shard_index, name, inbox)
        return inbox


class _EndpointRegistry:
    """Collects endpoint declarations from concurrently-running builders.

    The lock only guards declaration bookkeeping during the build phase;
    validation and binding happen single-threaded after all builders finish,
    with channel ids assigned in sorted-name order for determinism.
    """

    __slots__ = ("_lock", "_outs", "_ins")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: name -> (shard_index, Channel)
        self._outs: dict[str, tuple[int, Channel]] = {}
        #: name -> (shard_index, Inbox, Mailbox)
        self._ins: dict[str, tuple[int, Inbox, Mailbox]] = {}

    def declare_out(self, shard_index: int, name: str, channel: Channel) -> None:
        with self._lock:
            if name in self._outs:
                raise TopologyError(
                    f"channel {name!r} already has a sender on shard "
                    f"{self._outs[name][0]}; each channel connects exactly one "
                    f"ports.out(...) to one ports.inbox(...)"
                )
            self._outs[name] = (shard_index, channel)

    def declare_in(self, shard_index: int, name: str, inbox: Inbox) -> None:
        with self._lock:
            if name in self._ins:
                raise TopologyError(
                    f"channel {name!r} already has a receiver on shard "
                    f"{self._ins[name][0]}; each channel connects exactly one "
                    f"ports.out(...) to one ports.inbox(...)"
                )
            self._ins[name] = (shard_index, inbox, Mailbox())

    def validate_and_bind(self) -> dict[int, list[tuple[Mailbox, Inbox]]]:
        """Check the wiring, assign channel ids, and bind senders.

        Returns each shard's owned ``(mailbox, inbox)`` pairs. Runs
        single-threaded after every builder has finished.
        """
        unmatched_outs = sorted(set(self._outs) - set(self._ins))
        if unmatched_outs:
            raise TopologyError(
                f"channel(s) {unmatched_outs} have a sender but no receiver; "
                f"declare ports.inbox(name) on the destination shard"
            )
        unmatched_ins = sorted(set(self._ins) - set(self._outs))
        if unmatched_ins:
            raise TopologyError(
                f"channel(s) {unmatched_ins} have a receiver but no sender; "
                f"declare ports.out(name, lookahead=...) on the source shard"
            )
        owned: dict[int, list[tuple[Mailbox, Inbox]]] = {}
        for channel_id, name in enumerate(sorted(self._outs)):
            out_shard, channel = self._outs[name]
            in_shard, inbox, mailbox = self._ins[name]
            if out_shard == in_shard:
                raise TopologyError(
                    f"channel {name!r} connects shard {out_shard} to itself; "
                    f"use ordinary local events within a shard"
                )
            channel.bind(channel_id=channel_id, mailbox=mailbox)
            owned.setdefault(in_shard, []).append((mailbox, inbox))
        return owned

    def outgoing_lookaheads(self, shard_index: int) -> list[float]:
        """Return the lookaheads of *shard_index*'s outgoing channels."""
        return [
            channel.lookahead
            for owner, channel in self._outs.values()
            if owner == shard_index
        ]


class ShardedSim:
    """One large model partitioned into channel-connected shards.

    Args:
        shards: Number of shards; each gets its own ``Sim`` and (in threaded
            mode) its own thread.
        master_seed: The explicit study seed (required, keyword-only). Shard
            *i*'s ``Sim`` adopts the domain-separated stream
            ``SeedTree(master_seed).shard_rng(i)``.
        debug: Construct shard ``Sim``s with the owner-thread debug guard on
            (also enabled globally by ``LLMSIM_DEBUG=1``).
    """

    __slots__ = ("shard_count", "debug", "_tree", "_builders")

    def __init__(self, shards: int, *, master_seed: int, debug: bool = False) -> None:
        """Declare a topology of *shards* empty shards."""
        if shards < 1:
            raise TopologyError(f"shards must be >= 1, got {shards}")
        #: Number of shards in the topology.
        self.shard_count = shards
        #: Whether shard Sims run with the owner-thread debug guard.
        self.debug = debug
        self._tree = SeedTree(master_seed)
        self._builders: dict[int, Builder] = {}

    @property
    def master_seed(self) -> int:
        """The explicit study seed all shard streams derive from."""
        return self._tree.master_seed

    def shard(self, shard_index: int) -> Callable[[Builder], Builder]:
        """Register the builder for *shard_index* (decorator)."""
        if not 0 <= shard_index < self.shard_count:
            raise TopologyError(
                f"shard index {shard_index} out of range for a "
                f"{self.shard_count}-shard topology"
            )
        if shard_index in self._builders:
            raise TopologyError(
                f"shard {shard_index} already has a builder "
                f"({self._builders[shard_index].__qualname__})"
            )

        def register(builder: Builder) -> Builder:
            self._builders[shard_index] = builder
            return builder

        return register

    def run(self, until: float, *, mode: RunMode = "threads") -> None:
        """Run the topology until every event below *until* has executed.

        ``mode="threads"`` runs one thread per shard under the safe-window
        synchronizer; ``mode="sequential"`` runs the identical window
        algorithm on the calling thread — the reference oracle, bitwise
        trace-equal to the threaded mode for the same master seed. Events at
        exactly *until* (and later) are not executed, matching
        ``Sim.run(until=...)``.
        """
        missing = sorted(set(range(self.shard_count)) - set(self._builders))
        if missing:
            raise TopologyError(
                f"shard(s) {missing} have no builder; register one with "
                f"@topo.shard(i) for every index before run()"
            )
        if until <= 0:
            raise ValueError(f"until must be > 0, got {until}")
        # Deferred import: sync consumes this module's registry/error types
        # at module level, so importing it eagerly here would be a cycle.
        from llmsim.parallel.pdes import sync

        if mode == "sequential":
            sync.run_sequential(self, until)
        elif mode == "threads":
            sync.run_threaded(self, until)
        else:
            raise ValueError(
                f"unknown mode {mode!r}; expected 'threads' or 'sequential'"
            )

    def _build_shard(self, shard_index: int, registry: _EndpointRegistry) -> Sim:
        """Construct shard *shard_index*'s Sim and run its builder.

        Called on the shard's owning thread in threaded mode (so the debug
        owner-thread guard binds to that thread), or on the caller thread in
        sequential mode.
        """
        sim = Sim(rng=self._tree.shard_rng(shard_index), debug=self.debug)
        ports = ShardPorts(shard_index, sim, registry)
        self._builders[shard_index](sim, ports)
        return sim

    def __repr__(self) -> str:
        """Show the topology shape for debugging."""
        return (
            f"ShardedSim(shards={self.shard_count}, "
            f"master_seed={self.master_seed}, "
            f"builders={sorted(self._builders)})"
        )
