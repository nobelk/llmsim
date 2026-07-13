"""The process abstraction and its driver.

A process is a generator (SimPy-style ``yield`` of events) or an ``async def``
coroutine; a single driver advances both models by resuming the frame when the
event it is waiting on fires. Generators pin to their home thread.
"""

from collections.abc import Coroutine, Generator
from typing import TYPE_CHECKING, Any, TypeVar

from llmsim.core.errors import Interrupt, copy_with_cause
from llmsim.core.events import PENDING, URGENT, Event

if TYPE_CHECKING:
    from llmsim.core.sim import Sim

T = TypeVar("T")

#: A runnable process body: either a generator or an ``async def`` coroutine.
#: Both expose the identical ``send()``/``throw()`` protocol the driver uses.
Runnable = Generator[Event[Any], Any, T] | Coroutine[Event[Any], Any, T]


class Process(Event[T]):
    """A generator or coroutine advanced by the simulation, and itself an event.

    A process suspends by yielding (or awaiting) an event; the driver resumes it
    with that event's value once it is processed, or throws the event's
    exception into it. ``Process`` is itself an :class:`~llmsim.core.events.Event`
    that is triggered when the body returns (its value becomes the return value)
    or raises (its value becomes the exception), so other processes can wait on
    a process the same way they wait on any event.
    """

    __slots__ = ("_runnable", "_target")

    def __init__(self, sim: "Sim", runnable: Runnable[T]) -> None:
        """Schedule *runnable* to start at the next urgent step.

        Raises:
            ValueError: if *runnable* is neither a generator nor a coroutine
                (it lacks a ``throw`` method).
        """
        if not hasattr(runnable, "throw"):
            raise ValueError(
                f"{runnable!r} is not a generator or coroutine process body"
            )
        # Event initialization is inlined so the process starts life untriggered
        # without a redundant Event.__init__ call.
        self._sim = sim
        self.callbacks = []
        self._value = PENDING
        self._ok = False
        self.defused = False
        self._runnable = runnable
        # The start is scheduled urgently so the body has begun executing before
        # any interrupt could be delivered to it.
        self._target: Event[Any] | None = _Initialize(sim, self)

    def _desc(self) -> str:
        """Return ``Process(<body name>)``."""
        name = getattr(self._runnable, "__name__", type(self._runnable).__name__)
        return f"{type(self).__name__}({name})"

    @property
    def target(self) -> "Event[Any] | None":
        """The event this process is currently waiting on, or ``None`` if dead."""
        return self._target

    @property
    def is_alive(self) -> bool:
        """``True`` until the process body returns or raises."""
        return self._value is PENDING

    def interrupt(self, cause: Any = None) -> None:
        """Interrupt this process, throwing an :class:`Interrupt` into it.

        The interrupt is delivered at the process's next resume, ahead of the
        event it is currently waiting on.

        Raises:
            RuntimeError: if the process has already terminated, or if a process
                tries to interrupt itself.
        """
        _Interruption(self, cause)

    def _resume(self, event: Event[Any]) -> None:
        """Advance the body with *event*'s outcome; the one driver step.

        Sends *event*'s value into the body when it succeeded, or throws its
        exception in when it failed -- the sole branch is on the event outcome,
        never on whether the body is a generator or a coroutine, so both are
        driven by exactly this code (unified-driver key decision).
        """
        self._sim._active_process = self
        runnable = self._runnable
        while True:
            try:
                if event._ok:
                    new_event = runnable.send(event._value)
                else:
                    # The body must handle the failure or fail itself. Hand it a
                    # private copy so another process cannot mutate the shared
                    # exception's traceback.
                    event.defused = True
                    new_event = runnable.throw(copy_with_cause(event._value))
            except StopIteration as returned:
                # The body returned: resolve this process with its return value.
                self._ok = True
                self._value = returned.value
                self._target = None
                self._sim.schedule(self)
                break
            except BaseException as raised:  # noqa: BLE001
                # The body raised: resolve this process as a failure carrying it.
                self._ok = False
                self._value = raised
                self._target = None
                self._sim.schedule(self)
                break

            # Optimistically read the yielded event's callbacks -- the common
            # path. A body that yields a non-event raises AttributeError here,
            # which we turn into a clear error (no per-event isinstance cost).
            try:
                callbacks = new_event.callbacks
            except AttributeError:
                raise RuntimeError(
                    f"{self} yielded {new_event!r}, which is not an event"
                ) from None

            if new_event._sim is not self._sim:
                # Mixing Sims is always a bug (SimPy raises here too), and in
                # a sharded run it is a data race no debug guard can catch
                # deterministically: the foreign event's state is read and
                # mutated cross-thread. Reject at the seam instead.
                raise RuntimeError(
                    f"{self._desc()} yielded an event owned by a different "
                    f"Sim; a process may only wait on events of its own "
                    f"simulation (cross-shard interaction is message-passing "
                    f"only)"
                )

            self._target = new_event
            if callbacks is not None:
                # Not yet processed: resume once it is.
                callbacks.append(self._resume)
                break
            # Already processed: resume immediately with its value on the next
            # loop iteration, so yielding a triggered event never stalls.
            event = new_event

        self._sim._active_process = None


class _Initialize(Event[None]):
    """Internal event that starts a process at the next urgent step."""

    __slots__ = ()

    def __init__(self, sim: "Sim", process: Process[Any]) -> None:
        """Schedule *process*'s first resume urgently."""
        self._sim = sim
        self.callbacks = [process._resume]
        self._value = None
        self._ok = True
        self.defused = False
        sim.schedule(self, URGENT)


class _Interruption(Event[None]):
    """Internal event that throws an :class:`Interrupt` into a process."""

    __slots__ = ("process",)

    def __init__(self, process: Process[Any], cause: Any) -> None:
        """Schedule an interrupt of *process* urgently.

        Raises:
            RuntimeError: if *process* has terminated, or is the active process
                (a process cannot interrupt itself).
        """
        self._sim = process._sim
        self.callbacks = [self._interrupt]
        self._value = Interrupt(cause)
        self._ok = False
        # The interrupt is pre-defused: it is delivered by being thrown into the
        # target, never by crashing the Sim if the target ignores it.
        self.defused = True

        if process._value is not PENDING:
            raise RuntimeError(f"{process} has terminated and cannot be interrupted")
        if process is process._sim._active_process:
            raise RuntimeError("a process is not allowed to interrupt itself")

        self.process = process
        process._sim.schedule(self, URGENT)

    def _interrupt(self, event: Event[Any]) -> None:
        """Deliver the interrupt, first unhooking the process from its target."""
        # A process that died since this interrupt was scheduled (e.g. from an
        # earlier concurrent interrupt) is silently skipped.
        if self.process._value is not PENDING:
            return
        # Remove the process's resume from its target's callbacks so the target
        # firing later cannot resume the process a second time. This is the
        # stale-waiter cleanup that resource queues rely on.
        target = self.process._target
        if target is not None and target.callbacks is not None:
            target.callbacks.remove(self.process._resume)
            # Let the event react to losing a waiter (an offload abandons its
            # pending computation once no real waiter remains).
            target._waiter_unhooked()
        self.process._resume(self)
