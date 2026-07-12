"""The generic ``Event[T]`` type and event scheduling primitives.

An event carries a value of type ``T`` on success, tracks its scheduled
``(time, priority, eid)`` sort key, and fans out to registered callbacks when
it is processed.
"""

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from llmsim.core.conditions import Condition
    from llmsim.core.sim import Sim

T = TypeVar("T")

#: A callback receives the processed event as its single argument.
EventCallback = Callable[["Event[Any]"], None]

#: Scheduling priority for interrupts and process initialization: they must be
#: handled before any normally-scheduled event at the same time.
URGENT = 0
#: Default scheduling priority for ordinary events.
NORMAL = 1


class _Pending:
    """Type of the unique :data:`PENDING` sentinel (an untriggered value)."""

    __slots__ = ()

    def __repr__(self) -> str:
        """Render as ``PENDING`` in event descriptions."""
        return "PENDING"


#: Sentinel for an event whose value is not yet available. An event is
#: *triggered* exactly when its value is no longer this object.
PENDING = _Pending()


class Event(Generic[T]):
    """Something that may happen at a point in simulation time.

    An event moves through three states: it *may* happen (:attr:`triggered` is
    ``False``), it is *going to* happen (:attr:`triggered` is ``True`` once
    :meth:`succeed`, :meth:`fail`, or :meth:`trigger` schedules it), and it
    *has* happened (:attr:`processed` is ``True`` after the ``Sim`` invokes its
    callbacks).

    Every event belongs to exactly one :class:`~llmsim.core.sim.Sim` and, with
    it, to exactly one thread. A failed event whose exception is never defused
    crashes the simulation when processed, so faults are never silently lost.

    ``Event`` is generic in the value it yields on success. Because
    :meth:`__await__` yields ``self`` exactly once, ``await event`` (in an
    ``async def`` process) and ``yield event`` (in a generator process) resolve
    through the very same scheduling path.
    """

    __slots__ = ("_sim", "callbacks", "_value", "_ok", "defused")

    def __init__(self, sim: "Sim") -> None:
        """Create an untriggered event owned by *sim*."""
        self._sim = sim
        #: Callbacks invoked, in order, when the event is processed. Set to
        #: ``None`` once processed to reject further registration.
        self.callbacks: list[EventCallback] | None = []
        self._value: Any = PENDING
        self._ok = False
        #: ``True`` once a failed event's exception has been handled, so the
        #: ``Sim`` will not re-raise it. An explicit slot rather than SimPy 3's
        #: dynamic attribute (clean-break decision 4).
        self.defused = False

    def __repr__(self) -> str:
        """Return the event description with its identity."""
        return f"<{self._desc()} object at {id(self):#x}>"

    def _desc(self) -> str:
        """Return a human-readable description, e.g. ``Event()``."""
        return f"{type(self).__name__}()"

    @property
    def sim(self) -> "Sim":
        """The :class:`~llmsim.core.sim.Sim` this event belongs to."""
        return self._sim

    @property
    def triggered(self) -> bool:
        """``True`` once the event has a value and is scheduled for processing."""
        return self._value is not PENDING

    @property
    def processed(self) -> bool:
        """``True`` once the event's callbacks have been invoked."""
        return self.callbacks is None

    @property
    def ok(self) -> bool:
        """Whether the event succeeded.

        Raises:
            AttributeError: if accessed before the event is triggered.
        """
        if self._value is PENDING:
            raise AttributeError(f"{self} is not yet triggered")
        return self._ok

    @property
    def value(self) -> T:
        """The event's success value (or the exception, if it failed).

        Raises:
            AttributeError: if accessed before the event is triggered.
        """
        if self._value is PENDING:
            raise AttributeError(f"value of {self} is not yet available")
        return self._value  # type: ignore[no-any-return]

    def trigger(self, event: "Event[T]") -> None:
        """Adopt *event*'s outcome and schedule this event for processing.

        Usable directly as a callback so one event's completion can drive a
        chain of dependent events.
        """
        self._ok = event._ok
        self._value = event._value
        self._sim.schedule(self)

    def succeed(self, value: T | None = None) -> "Event[T]":
        """Mark the event successful with *value* and schedule it.

        Returns:
            The event itself, for call chaining.

        Raises:
            RuntimeError: if the event has already been triggered.
        """
        if self._value is not PENDING:
            raise RuntimeError(f"{self} has already been triggered")
        self._ok = True
        self._value = value
        self._sim.schedule(self)
        return self

    def fail(self, exception: BaseException) -> "Event[T]":
        """Mark the event failed with *exception* and schedule it.

        Returns:
            The event itself, for call chaining.

        Raises:
            ValueError: if *exception* is not a ``BaseException`` instance.
            RuntimeError: if the event has already been triggered.
        """
        if self._value is not PENDING:
            raise RuntimeError(f"{self} has already been triggered")
        # Defensive guard against untyped callers passing a non-exception.
        if not isinstance(exception, BaseException):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ValueError(f"{exception!r} is not an exception")
        self._ok = False
        self._value = exception
        self._sim.schedule(self)
        return self

    def __await__(self) -> Generator["Event[T]", Any, T]:
        """Yield ``self`` exactly once, then return the resolved value.

        This is the single hook that lets an ``async def`` process ``await`` an
        event through the same driver a generator process reaches by ``yield``.
        The value sent back in is the event's resolved value, supplied by the
        driver's ``send``.
        """
        value: T = yield self
        return value

    def __and__(self, other: "Event[Any]") -> "Condition":
        """Return a condition triggered once both events are processed."""
        from llmsim.core.conditions import Condition

        return Condition(self._sim, Condition.all_events, [self, other])

    def __or__(self, other: "Event[Any]") -> "Condition":
        """Return a condition triggered once either event is processed."""
        from llmsim.core.conditions import Condition

        return Condition(self._sim, Condition.any_events, [self, other])


class Timeout(Event[T]):
    """An event that triggers automatically after a fixed *delay* elapses.

    Constructing a timeout schedules it immediately; a process waits for the
    delay by yielding (or awaiting) it. This is what
    :meth:`~llmsim.core.sim.Sim.delay` returns.
    """

    __slots__ = ("_delay",)

    def __init__(self, sim: "Sim", delay: float, value: T | None = None) -> None:
        """Schedule a timeout that fires *delay* time units from now.

        Raises:
            ValueError: if *delay* is negative.
        """
        if delay < 0:
            raise ValueError(f"negative delay {delay}")
        # Initialization is inlined rather than delegated to Event.__init__ so
        # the timeout is born already successful and self-scheduled -- the hot
        # path constructs these in the millions.
        self._sim = sim
        self.callbacks = []
        self._value = value
        self._ok = True
        self.defused = False
        self._delay = delay
        sim.schedule(self, NORMAL, delay)

    def _desc(self) -> str:
        """Return ``Timeout(delay[, value=...])``."""
        suffix = "" if self._value is None else f", value={self._value}"
        return f"{type(self).__name__}({self._delay}{suffix})"
