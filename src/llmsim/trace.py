"""Structured event tracing.

Opt-in hooks that emit a structured record per processed event for debugging,
visualization, and determinism auditing, without adding overhead when tracing
is off.

Tracing is off by default: a ``Sim`` holds a single ``None`` trace sink, and the
event loop's only cost when tracing is disabled is one ``is not None`` check per
processed event. Attaching a :class:`Tracer` records one :class:`TraceRecord`
per processed event, in processing order -- the canonical log the Phase 3
trace-equivalence tests will diff a sharded run against.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

from llmsim.core.conditions import ConditionValue

if TYPE_CHECKING:
    from llmsim.core.events import Event
    from llmsim.core.sim import Sim

#: The sink the event loop calls for each processed event:
#: ``(time, eid, kind, priority, event)``. ``None`` on a ``Sim`` means tracing
#: is disabled.
TraceSink = Callable[[float, int, str, int, "Event[Any]"], None]


def _canonical_payload(value: Any) -> Any:
    """Reduce an event's value to a run-stable, comparable form.

    Two deterministic runs of the same model must produce equal traces, but some
    engine-produced values carry per-run identity: a
    :class:`~llmsim.core.conditions.ConditionValue` holds the member ``Event``
    objects (identity-compared), and an exception instance compares unequal to
    an equivalent one from another run. Those are projected onto stable
    surrogates -- the condition's ordered member values and the exception's
    ``(type name, args)`` -- so the trace-equivalence use case holds for
    condition and failure events, not just plain timeouts. Ordinary values (a
    model must keep these reproducible to claim determinism) pass through.
    """
    if isinstance(value, BaseException):
        return (type(value).__name__, value.args)
    if isinstance(value, ConditionValue):
        return tuple(_canonical_payload(member) for member in value.values())
    return value


class TraceRecord(NamedTuple):
    """One processed event, in canonical, comparable form.

    Attributes:
        time: The simulation time at which the event was processed.
        eid: The event's monotonic schedule id (the deterministic tie-breaker).
        kind: The event class name (e.g. ``"Timeout"``, ``"Process"``).
        priority: The scheduling priority the event was processed at.
        payload: The event's resolved value (or its exception, if it failed).
    """

    time: float
    eid: int
    kind: str
    priority: int
    payload: Any


class Tracer:
    """Collects a :class:`TraceRecord` per processed event.

    Attach with :func:`trace`; read :attr:`records` after the run. Two runs of
    the same deterministic model produce equal record lists.
    """

    __slots__ = ("records",)

    def __init__(self) -> None:
        """Start with an empty log."""
        self.records: list[TraceRecord] = []

    def record(
        self, time: float, eid: int, kind: str, priority: int, event: "Event[Any]"
    ) -> None:
        """Append the record for a processed event (used as the ``Sim`` sink)."""
        payload = _canonical_payload(event._value)
        self.records.append(TraceRecord(time, eid, kind, priority, payload))

    def clear(self) -> None:
        """Discard all recorded events."""
        self.records.clear()


def trace(sim: "Sim") -> Tracer:
    """Attach a fresh :class:`Tracer` to *sim* and return it."""
    tracer = Tracer()
    sim._trace = tracer.record
    return tracer


def disable_trace(sim: "Sim") -> None:
    """Detach any tracer from *sim*, restoring the zero-overhead default path."""
    sim._trace = None
