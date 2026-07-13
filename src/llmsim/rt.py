"""Real-time (wall-clock-synchronized) stepping (Phase 4.2).

``rt.run(sim, ...)`` paces an ordinary :class:`~llmsim.core.sim.Sim` against
``time.monotonic()`` so an event at simulated time ``T`` is processed no
earlier than ``start + (T - t0) * factor`` wall-clock seconds -- ``factor``
is real seconds per simulated time unit. Pacing is a driver concern layered
on the untouched core: sleeps happen strictly between steps, so ``rt.run``
introduces no clock dependence into event ordering, RNG, or values, and a
paced run of a deterministic model is bitwise trace-equivalent to
``sim.run()`` (``strict=False`` offloads are wall-clock-dependent by their
own Phase 4.1 contract under either driver).

Drift policy: when processing falls behind the wall-clock schedule by more
than one ``factor`` unit of slack (SimPy 3's tolerance), ``strict=True``
raises :class:`RealtimeDriftError` naming the simulated time and measured
drift; ``strict=False`` continues without sleeping until the schedule
catches up. Events are never skipped in either mode.

Offload synergy (hardware-in-the-loop): a strict offload's completion slot
becomes a real wall-clock deadline, and its payload computes *during* the
pacing sleep -- the computation hides inside the slot's real-time budget.
``rt.run`` honors the Phase 4.1 offload seam exactly as ``Sim.run`` does.
"""

import time
from typing import Any

from llmsim.core.errors import EmptySchedule, SimulationError
from llmsim.core.events import Event
from llmsim.core.sim import (
    INFINITY,
    Sim,
    _arm_until,
    _finish_empty_run,
    _StopSimulation,
)

#: Injectable clock seam: tests monkeypatch these (like
#: ``backends._runtime_gil_enabled``) to drive pacing deterministically.
_monotonic = time.monotonic
_sleep = time.sleep


class RealtimeDriftError(SimulationError):
    """The paced run fell behind the wall-clock schedule (strict mode).

    Raised by :func:`run` when the next event's wall deadline has passed by
    more than one ``factor`` unit of slack. Carries the event's simulated
    time and the measured drift in wall-clock seconds; drift is surfaced,
    never silently absorbed (docs-honesty rule).
    """

    def __init__(self, simulated_time: float, drift: float) -> None:
        """Store the slipped event's simulated time and the drift seconds."""
        super().__init__(simulated_time, drift)

    def __str__(self) -> str:
        """Describe the slip in both time domains."""
        return (
            f"fell {self.drift:.6f}s of wall-clock time behind the "
            f"real-time schedule at simulated time {self.simulated_time}"
        )

    @property
    def simulated_time(self) -> float:
        """The simulated time of the event that missed its wall deadline."""
        return float(self.args[0])

    @property
    def drift(self) -> float:
        """How many wall-clock seconds behind schedule processing fell."""
        return float(self.args[1])


def run(
    sim: Sim,
    until: "float | Event[Any] | None" = None,
    *,
    factor: float = 1.0,
    strict: bool = True,
) -> Any:
    """Advance *sim* like :meth:`~llmsim.core.sim.Sim.run`, paced in real time.

    Before processing the event at simulated time ``T``, sleeps until
    ``start + (T - t0) * factor`` on the monotonic clock. ``until`` accepts
    exactly what ``Sim.run`` accepts (``None``, a time, or an event whose
    value is returned), and the offload seam (post-step ``poll()``, drain on
    every ``EmptySchedule`` while a pool is attached) matches ``Sim.run``'s
    loop -- keep the two in lockstep (see ``core/sim.py``).

    Args:
        sim: The simulation to drive; it runs on the calling thread, which
            must be the ``Sim``'s owning thread.
        until: Stop condition, as in ``Sim.run``.
        factor: Real seconds per simulated time unit (must be positive).
        strict: Raise on drift beyond one ``factor`` of slack (default), or
            hurry without sleeping until caught up (``strict=False``).

    Raises:
        ValueError: if *factor* is not positive, or *until* is a time at or
            before ``sim.now``.
        RealtimeDriftError: in strict mode, when processing falls behind.
        RuntimeError: if *until* can never trigger because the schedule
            emptied first (identical to ``Sim.run``).
    """
    if factor <= 0:
        raise ValueError(f"factor must be positive, got {factor}")
    if until is not None:
        until, early_value = _arm_until(sim, until)
        if until is None:
            return early_value

    offload = sim._offload
    origin = sim.now
    start_wall = _monotonic()
    try:
        while True:
            next_time = sim.peek()
            if next_time != INFINITY:
                deadline = start_wall + (next_time - origin) * factor
                now_wall = _monotonic()
                if now_wall < deadline:
                    _sleep(deadline - now_wall)
                elif strict and now_wall - deadline > factor:
                    raise RealtimeDriftError(next_time, now_wall - deadline)
            try:
                sim.step()
            except EmptySchedule:
                # Same run-end rule as Sim.run: outstanding non-strict
                # offloads deliver before any EmptySchedule outcome.
                if offload is not None and offload.drain():
                    continue
                raise
            if offload is not None:
                offload.poll()
    except _StopSimulation as stopped:
        return stopped.args[0]
    except EmptySchedule:
        return _finish_empty_run(until)
