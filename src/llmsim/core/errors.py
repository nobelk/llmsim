"""The engine's exception hierarchy.

Defines the base error type and the specific exceptions the core raises
(interrupts, stopped simulations, misuse of the event API) so callers can
catch engine faults distinctly from domain faults.
"""

from typing import Any


def copy_with_cause(exception: BaseException) -> BaseException:
    """Return a fresh copy of *exception* with the original chained as its cause.

    Re-raising a copy gives the exception a traceback rooted at the re-raise site
    (the crashing ``Sim.step`` or the resumed process) while ``__cause__``
    preserves the original chain. Shared by the event loop and the process driver
    so the copy-and-chain contract lives in one place.

    A custom exception whose constructor cannot be replayed positionally from
    ``args`` (for example one with keyword-only parameters) is propagated
    unchanged rather than masked by a ``TypeError`` from this helper.
    """
    try:
        copy = type(exception)(*exception.args)
    except Exception:
        return exception
    copy.__cause__ = exception
    return copy


class SimulationError(Exception):
    """Base class for every exception the simulation engine raises.

    Catching ``SimulationError`` distinguishes engine faults (a stopped
    simulation, a misused event, an interrupt) from the domain exceptions a
    model raises out of its own process code.
    """


class Interrupt(SimulationError):  # noqa: N818 -- spec-mandated public name
    """Thrown into a process when another process interrupts it.

    :attr:`cause` carries the reason for the interrupt, or ``None`` when the
    interrupter supplied none. When a process is interrupted several times
    concurrently, the interrupts are thrown in the order they were scheduled.
    """

    def __init__(self, cause: Any = None) -> None:
        """Store *cause* as the single exception argument."""
        super().__init__(cause)

    def __str__(self) -> str:
        """Return ``Interrupt(<cause>)`` for readable tracebacks."""
        return f"{type(self).__name__}({self.cause!r})"

    @property
    def cause(self) -> Any:
        """The reason for the interrupt, or ``None`` if none was provided."""
        return self.args[0]


class EmptySchedule(SimulationError):  # noqa: N818 -- spec-mandated public name
    """Raised by :meth:`~llmsim.core.sim.Sim.step` when no events remain.

    A bare :meth:`~llmsim.core.sim.Sim.run` (``until=None``) catches this to
    stop cleanly once the schedule drains; it surfaces to the caller only when
    a ``run(until=event)`` can never be satisfied because the queue emptied
    first.
    """
