"""The conservative synchronization barrier.

Computes the global safe window each round so every shard may process its due
events without risk of receiving an earlier-timestamped message.

The horizon is progress-safe (Phase 3 requirements, superseding the literal
formula in the design document): each shard reports
``bound_i = next_i + L_i`` where ``next_i`` folds undelivered inbox messages
into the next-work time, and ``H = min_i bound_i``. Messages with
``timestamp < H`` are delivered before the window opens; events execute only
strictly below the window horizon; with all lookaheads positive, ``H``
strictly increases every round with pending work, so the minimum pending item
is always executed or delivered within finitely many rounds.

Two drivers run the identical round structure: :func:`run_sequential` on the
calling thread (the reference oracle) and :func:`run_threaded` with one
thread per shard meeting at barriers. Bitwise trace equivalence between the
two is the phase's central correctness claim — the threads and barriers must
add no observable nondeterminism.
"""

import heapq
import sys
import threading
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from llmsim.core.sim import INFINITY, Sim
from llmsim.parallel.pdes.channel import Inbox, LookaheadError, Mailbox, Message
from llmsim.parallel.pdes.shard import ShardError, TopologyError, _EndpointRegistry

if TYPE_CHECKING:
    from llmsim.parallel.pdes.shard import ShardedSim

#: One pending, undelivered message: its normative sort key, then the
#: message and its destination inbox. Keys are unique (per-channel sequence),
#: so heap comparisons never reach the non-comparable tail.
_PendingEntry = tuple[float, int, int, Message, Inbox]


class _ShardRuntime:
    """One shard's state as the synchronizer sees it.

    Owned by the shard's executing thread (or the caller thread in
    sequential mode); the only cross-thread structures it touches are its
    inbound mailboxes, and only at window edges.
    """

    __slots__ = ("shard_index", "sim", "min_lookahead", "_owned", "_pending")

    def __init__(
        self,
        shard_index: int,
        sim: Sim,
        min_lookahead: float,
        owned: list[tuple[Mailbox, Inbox]],
    ) -> None:
        self.shard_index = shard_index
        self.sim = sim
        #: min lookahead over outgoing channels; +inf for a pure sink.
        self.min_lookahead = min_lookahead
        self._owned = owned
        #: Drained-but-undelivered messages as a heap in normative order --
        #: the key is computed once per message, the minimum is O(1) per
        #: round, and delivery pops in sorted order without re-sorting.
        self._pending: list[_PendingEntry] = []

    def absorb(self) -> None:
        """Drain inbound mailboxes into the local pending heap (quiescent)."""
        for mailbox, inbox in self._owned:
            for message in mailbox.drain():
                heapq.heappush(
                    self._pending,
                    (
                        message.timestamp,
                        message.channel_id,
                        message.sequence,
                        message,
                        inbox,
                    ),
                )

    def bound(self) -> tuple[float, float]:
        """Report ``(next_i, next_i + L_i)`` for the horizon computation.

        Called with every shard quiescent at the round boundary: absorbs the
        inbound mailboxes first, so undelivered messages fold into ``next_i``
        (the progress-safe horizon from the requirements).
        """
        self.absorb()
        next_time = self.sim.peek()
        if self._pending:
            next_time = min(next_time, self._pending[0][0])
        return next_time, next_time + self.min_lookahead

    def deliver_below(self, horizon: float) -> None:
        """Deliver pending messages with ``timestamp < horizon``, in order."""
        pending = self._pending
        while pending and pending[0][0] < horizon:
            _, _, _, message, inbox = heapq.heappop(pending)
            inbox.deliver(message)

    def execute_window(self, horizon: float) -> None:
        """Run local events with ``time`` strictly below *horizon*.

        The per-event hot loop: the heap is inspected through a local
        reference rather than ``peek()`` to avoid a method call and a
        redundant emptiness branch per executed event.
        """
        sim = self.sim
        queue = sim._queue
        step = sim.step
        while queue and queue[0][0] < horizon:
            step()


def _build_runtimes(
    topology: "ShardedSim",
    sims: list[Sim],
    registry: _EndpointRegistry,
) -> list[_ShardRuntime]:
    """Validate wiring and assemble each shard's runtime (single-threaded).

    Called by both drivers after every builder has finished: channel-id
    assignment and mailbox binding happen here, before any event executes.
    """
    owned = registry.validate_and_bind()
    runtimes: list[_ShardRuntime] = []
    for shard_index in range(topology.shard_count):
        lookaheads = registry.outgoing_lookaheads(shard_index)
        runtimes.append(
            _ShardRuntime(
                shard_index,
                sims[shard_index],
                min(lookaheads, default=INFINITY),
                owned.get(shard_index, []),
            )
        )
    return runtimes


class _RoundDecision:
    """The coordinator's per-round verdict, shared with shard threads."""

    __slots__ = ("stop", "window")

    def __init__(self) -> None:
        self.stop = False
        self.window = 0.0


def _decide(
    bounds: list[tuple[float, float]], until: float, previous_horizon: float
) -> tuple[bool, float, float]:
    """Compute one round's (stop, window, horizon) from shard bounds.

    The single decision rule both drivers share: stop once no shard has work
    below *until*; otherwise the executable window is ``min(H, until)``.
    Raises if the horizon ever fails to advance — the progress property is
    an internal invariant, not a hope.
    """
    next_min = min(next_time for next_time, _ in bounds)
    horizon = min(bound for _, bound in bounds)
    if next_min >= until:
        return True, until, horizon
    if horizon <= previous_horizon:
        raise RuntimeError(
            f"safe-window horizon failed to advance ({horizon} after "
            f"{previous_horizon}); this is a synchronizer bug -- with "
            f"positive lookaheads H must strictly increase every round"
        )
    return False, min(horizon, until), horizon


def run_sequential(topology: "ShardedSim", until: float) -> None:
    """Run the window algorithm on the calling thread (the oracle).

    Identical rounds to :func:`run_threaded` — build every shard, validate
    wiring, then loop {absorb+bounds, decide, deliver, execute} in shard
    index order until no work remains below *until*.
    """
    registry = _EndpointRegistry()
    sims = [
        topology._build_shard(shard_index, registry)
        for shard_index in range(topology.shard_count)
    ]
    runtimes = _build_runtimes(topology, sims, registry)

    previous_horizon = -INFINITY
    while True:
        bounds = [runtime.bound() for runtime in runtimes]
        stop, window, horizon = _decide(bounds, until, previous_horizon)
        if stop:
            return
        previous_horizon = horizon
        for runtime in runtimes:
            runtime.deliver_below(window)
        for runtime in runtimes:
            runtime.execute_window(window)


def run_threaded(
    topology: "ShardedSim",
    until: float,
    *,
    jitter: Callable[[], None] | None = None,
) -> None:
    """Run one thread per shard under the barrier synchronizer.

    Round structure (all threads meet at each barrier):

    1. every shard absorbs its mailboxes and reports its bound;
    2. the coordinator (the calling thread) decides stop/window;
    3. shards deliver messages below the window and execute it.

    A failing shard aborts the barrier, every thread is joined, and a
    :class:`ShardError` naming the lowest failing shard is raised with the
    original exception chained (fail-fast). On a GIL build a prominent
    ``RuntimeWarning`` notes the run is correct but not faster than
    sequential. *jitter*, when provided, is called by every shard thread
    around window edges — the soak suite injects randomized sleeps through
    it to shake out schedule-dependent bugs.
    """
    if sys._is_gil_enabled():
        warnings.warn(
            "ShardedSim.run(mode='threads') on a GIL build executes shards "
            "as time-sliced threads: results are correct but the run will "
            "not be faster than sequential. Use a free-threaded (3.14t) "
            "build for PDES speedup",
            RuntimeWarning,
            stacklevel=3,
        )

    shard_count = topology.shard_count
    registry = _EndpointRegistry()
    sims: list[Sim | None] = [None] * shard_count
    runtimes: list[_ShardRuntime | None] = [None] * shard_count
    bounds: list[tuple[float, float]] = [(0.0, 0.0)] * shard_count
    decision = _RoundDecision()
    errors: dict[int, BaseException] = {}
    errors_lock = threading.Lock()
    barrier = threading.Barrier(shard_count + 1)

    def shard_thread(shard_index: int) -> None:
        try:
            sims[shard_index] = topology._build_shard(shard_index, registry)
            barrier.wait()  # built: coordinator may validate + bind
            barrier.wait()  # runtimes ready
            runtime = runtimes[shard_index]
            assert runtime is not None
            while True:
                if jitter is not None:
                    jitter()
                bounds[shard_index] = runtime.bound()
                barrier.wait()  # bounds reported
                barrier.wait()  # decision ready
                if decision.stop:
                    return
                runtime.deliver_below(decision.window)
                runtime.execute_window(decision.window)
                if jitter is not None:
                    jitter()
                # Window-complete barrier: no shard may report next-round
                # bounds while another is still executing (and sending) --
                # a bound computed against a not-yet-quiescent topology can
                # miss in-flight messages, regress the horizon, or terminate
                # the run with mail still buffered.
                barrier.wait()
        except threading.BrokenBarrierError:
            return  # another thread failed; its error is already recorded
        except BaseException as error:  # noqa: BLE001 -- fail-fast boundary
            with errors_lock:
                errors[shard_index] = error
            barrier.abort()

    threads = [
        threading.Thread(
            target=shard_thread, args=(shard_index,), name=f"llmsim-shard-{shard_index}"
        )
        for shard_index in range(shard_count)
    ]
    for thread in threads:
        thread.start()

    coordinator_error: BaseException | None = None
    try:
        barrier.wait()  # all shards built
        # Every slot is filled: the "all shards built" barrier above cannot
        # be passed by a shard that failed to construct its Sim.
        runtimes[:] = _build_runtimes(topology, cast("list[Sim]", sims), registry)
        barrier.wait()  # runtimes ready
        previous_horizon = -INFINITY
        while True:
            barrier.wait()  # bounds reported
            stop, window, horizon = _decide(bounds, until, previous_horizon)
            previous_horizon = horizon
            decision.stop = stop
            decision.window = window
            barrier.wait()  # decision ready
            if stop:
                return
            barrier.wait()  # window complete (see shard_thread)
    except threading.BrokenBarrierError:
        pass  # a shard failed; fall through to join + raise
    except BaseException as error:  # noqa: BLE001 -- release waiting shards
        coordinator_error = error
        barrier.abort()
    finally:
        for thread in threads:
            thread.join()
        if coordinator_error is not None:
            raise coordinator_error
        if errors:
            failing_shard = min(errors)
            failure = errors[failing_shard]
            if isinstance(failure, (TopologyError, LookaheadError)):
                # Construction-time validation errors are mode-independent
                # contract: raise them unwrapped, exactly as sequential
                # mode does, so callers handle miswiring uniformly.
                raise failure
            raise ShardError(
                f"shard {failing_shard} failed with {type(failure).__name__}: {failure}"
            ) from failure
