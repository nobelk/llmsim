"""The ``Sim`` event loop.

Owns the future-event set (a ``heapq`` ordered by ``(time, priority, eid)``),
advances simulation time, and dispatches due events to their callbacks. A
``Sim`` and everything attached to it belong to exactly one thread; there are
no locks on this hot path.
"""

import heapq
import os
import random
import threading
from collections.abc import Callable, Coroutine, Generator, Iterable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, cast, overload

from llmsim.core.errors import EmptySchedule, SimulationError, copy_with_cause
from llmsim.core.events import NORMAL, URGENT, Event, Timeout
from llmsim.core.process import Process

if TYPE_CHECKING:
    from llmsim.core.conditions import AllOf, AnyOf
    from llmsim.trace import TraceSink

T = TypeVar("T")

#: Convenience alias for the time of an exhausted schedule.
INFINITY = float("inf")

#: What :meth:`Sim.spawn` accepts: a process function, or an already-created
#: generator or coroutine.
ProcessSpec = Callable[..., Any] | Generator[Any, Any, Any] | Coroutine[Any, Any, Any]

#: One entry in the future-event set. The tuple sort makes ordering fully
#: deterministic: earliest ``time`` first, ``priority`` breaking time ties, and
#: the monotonic ``eid`` breaking priority ties by insertion order. No key
#: depends on wall-clock time or hash order (determinism decision).
_ScheduledEvent = tuple[float, int, int, Event[Any]]


class OffloadHandler(Protocol):
    """The seam an offload pool plugs into a :class:`Sim` (Phase 4.1).

    The core defines only this protocol -- it never imports
    ``llmsim.parallel`` -- so the dependency points from the pool to the
    engine, keeping the sequential core stdlib-only and lock-free. The
    concrete implementation is ``llmsim.parallel.offload.OffloadPool``,
    which assigns itself to ``sim._offload`` at construction.
    """

    def submit(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        delay: float | None,
        strict: bool,
    ) -> Event[Any]:
        """Dispatch one payload and return its completion event."""
        ...

    def poll(self) -> None:
        """Deliver any completed non-strict results (called between steps)."""
        ...

    def drain(self) -> bool:
        """Block for outstanding non-strict work when the schedule empties.

        Returns ``True`` when at least one delivery was scheduled (so the run
        loop continues), ``False`` when nothing is outstanding.
        """
        ...


class _StopSimulation(SimulationError):  # noqa: N818 -- internal control signal
    """Internal signal that :meth:`Sim.run` should stop at an *until* event."""

    @classmethod
    def callback(cls, event: Event[Any]) -> None:
        """Stop the run, forwarding *event*'s value or re-raising its failure."""
        if event._ok:
            raise cls(event._value)
        raise event._value


class Sim:
    """A single-threaded discrete-event simulation.

    ``Sim`` owns the event schedule, the current simulation time, and a
    reproducible random stream. It and every event, process, and resource
    attached to it belong to exactly one thread; parallelism comes from running
    many independent ``Sim`` instances, never from locking one (share-nothing
    architecture).

    Args:
        initial_time: The simulation clock's starting value.
        seed: Seed for :attr:`rng`. Ignored when *rng* is given. This is the
            single seam the Phase 2 seed tree injects a derived stream into.
        rng: An explicit :class:`random.Random` to adopt as :attr:`rng`.
        debug: When ``True`` (or when ``LLMSIM_DEBUG=1`` is set in the
            environment), every :meth:`schedule` asserts it runs on the thread
            that created the ``Sim``, catching accidental cross-thread sharing.
    """

    __slots__ = (
        "_now",
        "_queue",
        "_eid",
        "_active_process",
        "_owner_thread",
        "_trace",
        "_offload",
        "rng",
    )

    def __init__(
        self,
        initial_time: float = 0,
        *,
        seed: int | None = None,
        rng: random.Random | None = None,
        debug: bool = False,
    ) -> None:
        """Initialize an empty schedule at *initial_time*."""
        self._now = initial_time
        self._queue: list[_ScheduledEvent] = []
        # A plain integer counter owned by this single-threaded Sim -- no
        # itertools.count(), whose atomicity is undocumented on free-threaded
        # builds (design decision 4.7).
        self._eid = 0
        self._active_process: Process[Any] | None = None
        #: The reproducible random stream. Models that draw only from ``rng``
        #: are replication-safe for free.
        self.rng: random.Random = rng if rng is not None else random.Random(seed)
        #: Owning thread ident when debug mode is on, else ``None`` -- the guard
        #: read in :meth:`schedule` is a single ``is not None`` on the hot path.
        self._owner_thread: int | None = (
            threading.get_ident()
            if debug or os.environ.get("LLMSIM_DEBUG") == "1"
            else None
        )
        self._trace: TraceSink | None = None
        #: The attached offload pool, or ``None``. Like ``_trace``, the hot
        #: path pays a single ``is not None`` check when no pool is attached.
        self._offload: OffloadHandler | None = None

    @property
    def now(self) -> float:
        """The current simulation time."""
        return self._now

    @property
    def debug(self) -> bool:
        """Whether debug mode is on (``debug=True`` or ``LLMSIM_DEBUG=1``).

        Core owns this question; features that must "flag loudly in debug
        mode" (a non-strict offload, for example) ask here instead of
        inferring it from the thread-ownership guard.
        """
        return self._owner_thread is not None

    @property
    def active_process(self) -> "Process[Any] | None":
        """The process whose event is currently being resumed, if any."""
        return self._active_process

    def schedule(
        self, event: Event[Any], priority: int = NORMAL, delay: float = 0
    ) -> None:
        """Insert *event* into the schedule at ``now + delay`` with *priority*.

        Raises:
            RuntimeError: in debug mode, if called from a thread other than the
                one that constructed this ``Sim``.
        """
        if self._owner_thread is not None:
            current = threading.get_ident()
            if current != self._owner_thread:
                raise RuntimeError(
                    f"Sim owned by thread {self._owner_thread} was used from "
                    f"thread {current}; a Sim and its events belong to exactly "
                    f"one thread (set debug=False to disable this check)"
                )
        eid = self._eid
        self._eid = eid + 1
        heapq.heappush(self._queue, (self._now + delay, priority, eid, event))

    def peek(self) -> float:
        """Return the time of the next scheduled event, or ``INFINITY``."""
        return self._queue[0][0] if self._queue else INFINITY

    def step(self) -> None:
        """Process the next scheduled event, advancing the clock to its time.

        Raises:
            EmptySchedule: if no events remain to process.
        """
        if not self._queue:
            raise EmptySchedule("no scheduled events left")
        self._now, priority, eid, event = heapq.heappop(self._queue)

        # Detach callbacks before invoking them so a callback that re-triggers
        # the event cannot corrupt the list mid-iteration. A queued event always
        # carries a callback list (only triggered events are ever scheduled).
        callbacks, event.callbacks = event.callbacks, None
        for callback in callbacks:  # type: ignore[union-attr]
            callback(event)

        if self._trace is not None:
            self._trace(self._now, eid, type(event).__name__, priority, event)

        if not event._ok and not event.defused:
            # An unhandled failure crashes the simulation. Raise a fresh copy so
            # the traceback points here, not into the process that produced it.
            raise copy_with_cause(event._value)

    @overload
    def delay(self, delay: float) -> Timeout[None]: ...

    @overload
    def delay(self, delay: float, value: T) -> Timeout[T]: ...

    def delay(self, delay: float, value: Any = None) -> Timeout[Any]:
        """Return a :class:`~llmsim.core.events.Timeout` that fires after *delay*.

        With no *value* the timeout resolves to ``None``; otherwise it resolves
        to *value*.
        """
        return Timeout(self, delay, value)

    def event(self) -> Event[Any]:
        """Return a fresh, untriggered :class:`~llmsim.core.events.Event`."""
        return Event(self)

    def all_of(self, events: "Iterable[Event[Any]]") -> "AllOf":
        """Return a condition triggered once every event in *events* succeeds."""
        from llmsim.core.conditions import AllOf

        return AllOf(self, events)

    def any_of(self, events: "Iterable[Event[Any]]") -> "AnyOf":
        """Return a condition triggered once any event in *events* succeeds."""
        from llmsim.core.conditions import AnyOf

        return AnyOf(self, events)

    def spawn(self, process: ProcessSpec, *args: Any, **kwargs: Any) -> "Process[Any]":
        """Start a new process and return its :class:`~llmsim.core.process.Process`.

        *process* may be:

        - a process function -- called as ``process(sim, *args, **kwargs)`` so
          the ``Sim`` is injected as its first argument (design ergonomics); or
        - an already-created generator or coroutine, used as-is.

        Both a ``def ... : yield`` generator and an ``async def`` coroutine are
        accepted; the same unified driver advances either.
        """
        if callable(process):
            runnable = process(self, *args, **kwargs)
        else:
            runnable = process
        return Process(self, runnable)

    def offload(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        delay: float | None = None,
        strict: bool = True,
        **kwargs: Any,
    ) -> Event[T]:
        """Run ``fn(*args, **kwargs)`` on the attached offload pool.

        Returns an event that a process waits on like any other. In strict
        mode (the default) the result is delivered exactly at the
        deterministic completion slot ``now + delay``, regardless of how long
        the computation takes on the wall clock; with ``strict=False`` it is
        delivered as soon as it is available (nondeterministic ordering), no
        earlier than ``now + delay`` when *delay* is given.

        Args:
            fn: An importable module-level callable (validated at submission);
                its positional and keyword arguments follow, except the
                reserved keywords *delay* and *strict*.
            delay: The completion-slot offset, a pure function of model state
                (required in strict mode); under ``strict=False``, an
                earliest-delivery lower bound.
            strict: Whether delivery is pinned to the deterministic slot.

        Raises:
            SimulationError: if no offload pool is attached to this ``Sim``.
            ValueError: if *delay* is negative, or omitted in strict mode.
        """
        if self._offload is None:
            raise SimulationError(
                "no offload pool attached to this Sim; construct "
                "llmsim.OffloadPool(sim, backend=...) before calling "
                "sim.offload()"
            )
        return cast(
            "Event[T]",
            self._offload.submit(fn, args, kwargs, delay=delay, strict=strict),
        )

    def run(self, until: "float | Event[Any] | None" = None) -> Any:
        """Advance the simulation until *until* is reached.

        Args:
            until: ``None`` runs until the schedule empties. A number runs until
                the clock reaches that time. An :class:`~llmsim.core.events.Event`
                runs until that event is processed and returns its value.

        Raises:
            ValueError: if *until* is a time at or before :attr:`now`.
            RuntimeError: if *until* is an event that can never trigger because
                the schedule emptied first.
        """
        if until is not None:
            if not isinstance(until, Event):
                at = float(until)
                if at <= self._now:
                    raise ValueError(
                        f"until(={at}) must be greater than the current "
                        f"simulation time ({self._now})"
                    )
                stop: Event[Any] = Event(self)
                stop._ok = True
                stop._value = None
                self.schedule(stop, URGENT, at - self._now)
                until = stop
            elif until.callbacks is None:
                return until._value
            assert until.callbacks is not None
            until.callbacks.append(_StopSimulation.callback)

        # Bind the pool once: attaching one mid-run is unsupported (documented
        # on OffloadPool), and the bare loop below stays branch-free without it.
        offload = self._offload
        try:
            if offload is None:
                while True:
                    self.step()
            else:
                while True:
                    try:
                        self.step()
                    except EmptySchedule:
                        # Outstanding non-strict offloads may still deliver:
                        # drain() blocks wall-clock for them and schedules
                        # their deliveries, so a result is never dropped.
                        if not offload.drain():
                            raise
                        continue
                    offload.poll()
        except _StopSimulation as stopped:
            return stopped.args[0]
        except EmptySchedule:
            if until is not None:
                raise RuntimeError(
                    f'no scheduled events left but the "until" event was not '
                    f"triggered: {until}"
                ) from None
            return None
