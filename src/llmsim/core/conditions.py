"""Composition of events into conditions (``AllOf`` / ``AnyOf``).

A :class:`Condition` triggers once a predicate over a set of member events is
satisfied. ``AllOf`` waits for every member; ``AnyOf`` for at least one. The
``&`` and ``|`` operators on :class:`~llmsim.core.events.Event` are sugar for
these. Conditions may be nested.
"""

from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, Any

from llmsim.core.events import PENDING, Event

if TYPE_CHECKING:
    from llmsim.core.sim import Sim

#: A predicate over ``(member events, processed count)`` deciding whether the
#: condition is met.
Evaluate = Callable[[tuple[Event[Any], ...], int], bool]


class ConditionValue:
    """The value of a triggered :class:`Condition`: its members and their values.

    Supports dict-like access -- ``value[event]``, ``event in value``,
    :meth:`keys`, :meth:`values`, :meth:`items`, :meth:`todict` -- over the
    member events that had occurred by the time the condition was processed,
    in their original order. Compares equal to a plain ``dict`` of the same
    event/value pairs.
    """

    __slots__ = ("events",)

    def __init__(self) -> None:
        """Start with no recorded events."""
        self.events: list[Event[Any]] = []

    def __getitem__(self, key: Event[Any]) -> Any:
        """Return the value of member *key*, or raise ``KeyError``."""
        if key not in self.events:
            raise KeyError(str(key))
        return key._value

    def __contains__(self, key: Event[Any]) -> bool:
        """Whether *key* is one of the triggered members."""
        return key in self.events

    def __eq__(self, other: object) -> bool:
        """Equal to another ``ConditionValue`` or to an equivalent ``dict``."""
        if isinstance(other, ConditionValue):
            return self.events == other.events
        return self.todict() == other

    def __hash__(self) -> int:
        """Hash by identity (mutable value objects are not value-hashable)."""
        return id(self)

    def __repr__(self) -> str:
        """Render as ``<ConditionValue {...}>``."""
        return f"<ConditionValue {self.todict()}>"

    def __iter__(self) -> Iterator[Event[Any]]:
        """Iterate the triggered member events."""
        return self.keys()

    def keys(self) -> Iterator[Event[Any]]:
        """Yield the triggered member events in order."""
        return iter(self.events)

    def values(self) -> Iterator[Any]:
        """Yield the triggered members' values in order."""
        return (event._value for event in self.events)

    def items(self) -> Iterator[tuple[Event[Any], Any]]:
        """Yield ``(event, value)`` pairs in order."""
        return ((event, event._value) for event in self.events)

    def todict(self) -> dict[Event[Any], Any]:
        """Return a plain ``dict`` of the triggered members and their values."""
        return {event: event._value for event in self.events}


class Condition(Event[ConditionValue]):
    """An event triggered once *evaluate* holds over its member *events*.

    The condition's value is a :class:`ConditionValue` giving access to the
    members that had triggered by the time it was processed. If any member
    fails, the condition fails too: with that member's exception, or -- when
    several members have already failed together -- with a single
    :exc:`ExceptionGroup` aggregating them (a deliberate clean-break divergence
    from SimPy 3, which forwards only the first failure).
    """

    __slots__ = ("_evaluate", "_events", "_count")

    def __init__(
        self, sim: "Sim", evaluate: Evaluate, events: Iterable[Event[Any]]
    ) -> None:
        """Watch *events*, triggering when *evaluate* returns ``True``.

        Raises:
            ValueError: if the members do not all belong to *sim*.
        """
        super().__init__(sim)
        self._evaluate = evaluate
        self._events = tuple(events)
        self._count = 0

        if not self._events:
            # With no members the predicate is vacuously decided now.
            self.succeed(ConditionValue())
            return

        for event in self._events:
            if event._sim is not self._sim:
                raise ValueError(
                    "events from different Sims cannot be combined into one condition"
                )

        for event in self._events:
            if event.callbacks is None:
                self._check(event)
            else:
                event.callbacks.append(self._check)

        assert self.callbacks is not None
        self.callbacks.append(self._build_value)

    def _desc(self) -> str:
        """Return ``Condition(<evaluate>, (events...))``."""
        return f"{type(self).__name__}({self._evaluate.__name__}, {self._events})"

    def _populate_value(self, value: ConditionValue) -> None:
        """Append processed members (recursing into nested conditions) to *value*."""
        for event in self._events:
            if isinstance(event, Condition):
                event._populate_value(value)
            elif event.callbacks is None:
                value.events.append(event)

    def _build_value(self, event: Event[Any]) -> None:
        """Build this condition's :class:`ConditionValue` once it is processed."""
        self._remove_check_callbacks()
        if event._ok:
            value = ConditionValue()
            self._populate_value(value)
            self._value = value

    def _remove_check_callbacks(self) -> None:
        """Detach ``_check`` from members, breaking cycles with untriggered ones."""
        for event in self._events:
            if event.callbacks is not None and self._check in event.callbacks:
                event.callbacks.remove(self._check)
            if isinstance(event, Condition):
                event._remove_check_callbacks()

    def _check(self, event: Event[Any]) -> None:
        """Re-evaluate the condition as member *event* is processed."""
        if self._value is not PENDING:
            return
        self._count += 1

        if not event._ok:
            # Aggregate every member that has already failed, so failures that
            # resolved together are reported together rather than the first one
            # winning the race (clean-break decision).
            failures = [
                member
                for member in self._events
                if member._value is not PENDING and not member._ok
            ]
            for member in failures:
                member.defused = True
            if len(failures) > 1:
                self.fail(
                    ExceptionGroup(
                        "condition members failed",
                        [member._value for member in failures],
                    )
                )
            else:
                self.fail(event._value)
        elif self._evaluate(self._events, self._count):
            # ``_build_value`` populates the ConditionValue when we are processed.
            self.succeed()

    @staticmethod
    def all_events(events: tuple[Event[Any], ...], count: int) -> bool:
        """Return ``True`` once every event has been processed."""
        return len(events) == count

    @staticmethod
    def any_events(events: tuple[Event[Any], ...], count: int) -> bool:
        """Return ``True`` once at least one event has been processed."""
        return count > 0 or len(events) == 0


class AllOf(Condition):
    """A condition triggered once all *events* have succeeded.

    Fails immediately if any member fails.
    """

    __slots__ = ()

    def __init__(self, sim: "Sim", events: Iterable[Event[Any]]) -> None:
        """Wait for every event in *events*."""
        super().__init__(sim, Condition.all_events, events)


class AnyOf(Condition):
    """A condition triggered once any of *events* has succeeded.

    Fails immediately if any member fails.
    """

    __slots__ = ()

    def __init__(self, sim: "Sim", events: Iterable[Event[Any]]) -> None:
        """Wait for at least one event in *events*."""
        super().__init__(sim, Condition.any_events, events)
