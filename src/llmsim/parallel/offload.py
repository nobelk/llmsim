"""In-run compute offload with deterministic completion slots (Phase 4.1).

``yield sim.offload(fn, ...)`` runs a CPU-heavy payload on a worker pool
without breaking determinism. The mechanism is the **completion slot**: in
strict mode (the default) the result is delivered at the simulated time
``now + delay`` -- a pure function of model state, like PDES lookahead --
never at a time derived from how long the computation took. If the payload
has not finished when the event loop reaches the slot, the loop blocks
wall-clock there; the simulated event order is identical either way, so the
strict mode's trace is bitwise-equal to the inline sequential reference.

``strict=False`` opts out: the result is delivered as soon as the owning
thread observes it between steps (no earlier than ``now + delay`` when a
delay is given). Delivery order then depends on wall-clock completion, so
debug mode flags every non-strict call with :class:`NonStrictOffloadWarning`.

Payloads follow the Phase 2 reference rule on every backend: an importable
module-level callable (validated at submission) plus arguments -- never live
model objects. Arguments are pickle-preflighted only on transport backends
(interpreters/processes); on the thread backend they pass by live reference,
so payload arguments must not be ``Sim``-owned mutable state.

Known hazard (documented, not solvable in 1.0): a payload that never returns
cannot be interrupted on any backend -- ``Future.cancel()`` cannot stop
running work -- so a strict slot or :meth:`OffloadPool.close` blocks forever.
There is no offload timeout; keep payloads finite.
"""

import pickle
import warnings
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Executor, Future, wait
from types import TracebackType
from typing import Any, Literal, TypeVar

from llmsim.core.events import NORMAL, PENDING, Event, EventCallback
from llmsim.core.sim import Sim
from llmsim.parallel.backends import (
    PICKLE_HINT,
    ExecutionBackend,
    TransportError,
    _worker_backend,
    validate_factory,
)
from llmsim.parallel.replicate import _import_factory

T = TypeVar("T")

#: The offload backend vocabulary: the Phase 2 names plus the offload-local
#: ``"inline"`` reference mode (run synchronously on the owning thread).
OffloadBackendName = Literal["auto", "inline", "threads", "interpreters", "processes"]

#: The one nesting the Group 2 spike found broken on CPython 3.14: a process
#: pool created inside a subinterpreter worker dies with ``BrokenProcessPool``
#: (multiprocessing is not subinterpreter-safe). Everything else -- threads or
#: interpreters anywhere, processes inside thread/process workers -- works and
#: is honored when explicitly requested.
_REJECTED_NESTINGS = {("interpreters", "processes")}


class NonStrictOffloadWarning(RuntimeWarning):
    """A ``strict=False`` offload was submitted while debug mode is on.

    Non-strict delivery times depend on wall-clock completion, so event
    ordering is not reproducible across runs -- exactly the property debug
    mode exists to guard. Emitted per call, naming the payload and call site.
    """


def _run_offload(
    module_name: str, qualname: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    """Run one offloaded payload worker-side.

    Like the replication runner, the payload arrives as an ``(module,
    qualified name)`` reference and is imported worker-side -- one code path
    on every backend (normative decision 5).
    """
    fn = _import_factory(module_name, qualname)
    return fn(*args, **kwargs)


def _preflight_payload(
    fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> None:
    """Verify offload arguments survive a pickle boundary before dispatch.

    Called only on transport backends (interpreters/processes), mirroring
    :func:`~llmsim.parallel.backends.preflight_config`. Raises
    :class:`~llmsim.parallel.backends.TransportError` naming the payload.
    """
    try:
        pickle.dumps((args, kwargs))
    except Exception as error:
        raise TransportError(
            f"arguments of offloaded {fn.__qualname__!r} cannot be pickled "
            f"for the worker transport: {error}; {PICKLE_HINT} or use "
            f"backend='threads' or backend='inline'"
        ) from error


class OffloadEvent(Event[T]):
    """The completion event of one offloaded payload.

    In strict mode the event is born scheduled at its completion slot with a
    placeholder value; its first callback resolves the real outcome (blocking
    wall-clock on the worker future if needed) before any waiter runs, so the
    heap structure -- and therefore the trace -- is identical to the inline
    reference. In non-strict mode it is born untriggered and delivered by the
    pool once the owning thread observes the completed future.

    :meth:`cancel` abandons the computation: the pending future is cancelled
    if not started, and a finished result is discarded, never delivered.
    Interrupting the last process waiting on this event cancels it
    automatically (the requirements' cancellation contract).
    """

    __slots__ = (
        "_pool",
        "_future",
        "_captured",
        "_qualname",
        "_strict",
        "_abandoned",
        "_earliest",
    )

    def __init__(
        self,
        sim: "Sim",
        pool: "OffloadPool",
        future: "Future[Any] | None",
        captured: tuple[bool, Any] | None,
        qualname: str,
        *,
        strict: bool,
    ) -> None:
        """Create the event for one submitted payload (see ``OffloadPool``)."""
        # Event initialization is inlined per the engine convention. Strict
        # events are born "triggered" with a placeholder, like a Timeout, so
        # they can enter the heap at submission; the resolver callback swaps
        # in the real outcome at the slot, before any waiter sees it.
        self._sim = sim
        self._value = None if strict else PENDING
        self._ok = strict
        self.callbacks: list[EventCallback] | None = [self._resolve] if strict else []
        self.defused = False
        self._pool = pool
        self._future = future
        self._captured = captured
        self._qualname = qualname
        self._strict = strict
        self._abandoned = False
        #: Absolute earliest delivery time (non-strict lower bound).
        self._earliest = 0.0

    def _desc(self) -> str:
        """Return ``OffloadEvent(<payload name>)``."""
        return f"{type(self).__name__}({self._qualname})"

    def cancel(self) -> None:
        """Abandon the offload: its result or exception is never delivered.

        Idempotent. Cancels the pending future when the payload has not
        started; a running or finished payload's outcome is discarded. A
        strict event still processes at its slot (delivering ``None`` and
        never blocking); a non-strict event is simply forgotten.
        """
        if self._abandoned:
            return
        self._abandoned = True
        # A discarded failure must never crash the run.
        self.defused = True
        if self._future is not None:
            self._future.cancel()
        self._pool._forget(self)

    def _waiter_unhooked(self) -> None:
        """Abandon the offload once no real waiter remains (interrupt path)."""
        callbacks = self.callbacks
        if callbacks is None:
            return
        if not callbacks or callbacks == [self._resolve]:
            self.cancel()

    def _outcome(self) -> tuple[bool, Any]:
        """Return ``(ok, value)``, blocking on the worker future if needed."""
        if self._captured is not None:
            return self._captured
        assert self._future is not None
        try:
            # Strict mode's wall-clock block at the slot happens here.
            return (True, self._future.result())
        except BaseException as raised:  # noqa: BLE001 -- executors store any
            raised.add_note(
                f"raised by offloaded {self._qualname!r}; delivered at its "
                f"completion slot"
            )
            return (False, raised)

    def _resolve(self, _event: "Event[Any]") -> None:
        """Swap the real outcome in at the completion slot (strict mode)."""
        if self._abandoned:
            self._ok = True
            self._value = None
            return
        self._pool._forget(self)
        self._ok, self._value = self._outcome()


class OffloadPool:
    """The worker pool behind :meth:`~llmsim.core.sim.Sim.offload`.

    Construct one per ``Sim`` **before** calling ``run()`` (attaching a pool
    mid-run is unsupported)::

        sim = Sim(seed=7)
        pool = OffloadPool(sim, backend="processes")
        ...
        sim.run()
        pool.close()

    Args:
        sim: The simulation to attach to. A ``Sim`` accepts exactly one pool.
        backend: ``"inline"`` runs payloads synchronously on the owning
            thread (the sequential reference); the Phase 2 names select a
            worker pool; ``"auto"`` resolves like
            :meth:`~llmsim.parallel.backends.ExecutionBackend.resolve` --
            except inside an ``Experiment`` replication worker, where it
            resolves to ``"inline"`` (the nested-pool rule; pooled offload
            inside workers is explicit opt-in).
        max_workers: Pool size; ``None`` means ``os.process_cpu_count()``.

    The executor starts lazily on the first pooled submission. Use as a
    context manager, or call :meth:`close`, to release workers: outstanding
    offloads are abandoned, pending futures cancelled, and running payloads
    finish with their results discarded.

    Raises:
        RuntimeError: if *sim* already has a pool, or if the requested
            backend cannot host nested pools in this worker context
            (``backend="processes"`` inside an interpreters-backend worker).
    """

    __slots__ = ("_sim", "kind", "_max_workers", "_executor", "_live", "_closed")

    def __init__(
        self,
        sim: Sim,
        *,
        backend: OffloadBackendName = "auto",
        max_workers: int | None = None,
    ) -> None:
        """Resolve the backend, apply the nested-pool rule, and attach."""
        if sim._offload is not None:
            raise RuntimeError(
                "this Sim already has an offload pool attached; a Sim accepts "
                "exactly one OffloadPool"
            )
        #: The resolved concrete mode: ``"inline"`` or a Phase 2 backend kind.
        self.kind: str = self._resolve_kind(backend)
        self._sim = sim
        self._max_workers = max_workers
        self._executor: Executor | None = None
        #: Undelivered events: strict ones until their slot resolves, and
        #: non-strict ones until delivery. Owner-thread only -- no lock.
        self._live: list[OffloadEvent[Any]] = []
        self._closed = False
        sim._offload = self

    @staticmethod
    def _resolve_kind(backend: OffloadBackendName) -> str:
        """Resolve *backend*, honoring an explicit choice where possible."""
        worker_kind = _worker_backend.get()
        if backend == "inline":
            return "inline"
        if backend == "auto":
            if worker_kind is not None:
                # Nested-pool rule: inside an Experiment worker, default to
                # inline rather than oversubscribing nproc x nproc workers.
                return "inline"
            return ExecutionBackend.resolve("auto").kind
        if worker_kind is not None and (worker_kind, backend) in _REJECTED_NESTINGS:
            raise RuntimeError(
                f"offload backend {backend!r} cannot run inside an "
                f"{worker_kind!r}-backend Experiment worker: multiprocessing "
                f"is not subinterpreter-safe (BrokenProcessPool). Use "
                f"backend='inline' (the nested default), 'threads', or "
                f"'interpreters', or run the Experiment on another backend"
            )
        return ExecutionBackend(backend).kind

    @property
    def _transport(self) -> bool:
        """Whether payload arguments cross a pickle boundary."""
        return self.kind in ("interpreters", "processes")

    def submit(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        delay: float | None,
        strict: bool,
    ) -> Event[Any]:
        """Dispatch one payload (the ``OffloadHandler`` seam).

        Called by :meth:`~llmsim.core.sim.Sim.offload`; see that method for
        the user-facing contract.
        """
        if self._closed:
            raise RuntimeError(
                "this offload pool is closed; construct a new OffloadPool to "
                "submit more work"
            )
        validate_factory(fn)
        if delay is not None and delay < 0:
            raise ValueError(f"negative delay {delay}")
        if strict and delay is None:
            raise ValueError(
                "a strict offload requires delay=...: the completion slot "
                "now + delay must be a pure function of model state (pass "
                "strict=False for as-available delivery)"
            )
        sim = self._sim
        if not strict and sim._owner_thread is not None:
            warnings.warn(
                f"non-strict offload of {fn.__qualname__!r} at t={sim.now}: "
                f"delivery time depends on wall-clock completion, so event "
                f"ordering is not reproducible (pass delay=... with "
                f"strict=True for a deterministic completion slot)",
                NonStrictOffloadWarning,
                stacklevel=3,
            )

        future: Future[Any] | None = None
        captured: tuple[bool, Any] | None = None
        if self.kind == "inline":
            # The sequential reference: run now, deliver at the slot -- the
            # failure contract (capture here, re-raise at the slot) is
            # identical to the pooled backends by construction.
            try:
                captured = (True, fn(*args, **kwargs))
            except BaseException as raised:  # noqa: BLE001 -- match executors
                captured = (False, raised)
        else:
            if self._transport:
                _preflight_payload(fn, args, kwargs)
            future = self._ensure_executor().submit(
                _run_offload, fn.__module__, fn.__qualname__, args, kwargs
            )

        event: OffloadEvent[Any] = OffloadEvent(
            sim, self, future, captured, fn.__qualname__, strict=strict
        )
        if strict:
            self._live.append(event)
            assert delay is not None
            sim.schedule(event, NORMAL, delay)
            return event

        event._earliest = sim.now + (delay or 0.0)
        if captured is not None:
            self._deliver(event)
        else:
            self._live.append(event)
        return event

    def poll(self) -> None:
        """Deliver completed non-strict results (called between steps)."""
        live = self._live
        if not live:
            return
        remaining: list[OffloadEvent[Any]] = []
        for event in live:
            future = event._future
            if not event._strict and future is not None and future.done():
                self._deliver(event)
            else:
                remaining.append(event)
        self._live = remaining

    def drain(self) -> bool:
        """Block for outstanding non-strict work once the schedule empties.

        The run-end rule: a non-strict result is never silently dropped --
        ``run()`` waits wall-clock for at least one outstanding payload,
        delivers everything then complete, and keeps stepping.
        """
        futures = [
            event._future
            for event in self._live
            if not event._strict and event._future is not None
        ]
        if not futures:
            return False
        wait(futures, return_when=FIRST_COMPLETED)
        self.poll()
        return True

    def close(self) -> None:
        """Abandon outstanding offloads and shut the executor down.

        Pending futures are cancelled; running payloads finish (they cannot
        be interrupted) and their results are discarded. Idempotent.
        """
        if self._closed:
            return
        self._closed = True
        for event in list(self._live):
            event.cancel()
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    def _deliver(self, event: OffloadEvent[Any]) -> None:
        """Resolve *event* and schedule it no earlier than its lower bound."""
        event._ok, event._value = event._outcome()
        sim = self._sim
        sim.schedule(event, NORMAL, max(0.0, event._earliest - sim.now))

    def _forget(self, event: OffloadEvent[Any]) -> None:
        """Drop *event* from the undelivered set (resolution or cancel)."""
        try:
            self._live.remove(event)
        except ValueError:
            pass

    def _ensure_executor(self) -> Executor:
        """Create the executor on first pooled submission (lazy startup)."""
        if self._executor is None:
            self._executor = ExecutionBackend(self.kind).executor(self._max_workers)
        return self._executor

    def __enter__(self) -> "OffloadPool":
        """Return self; pair with ``__exit__`` for close-on-exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the pool when the ``with`` block exits."""
        self.close()

    def __repr__(self) -> str:
        """Show the resolved kind and pool state for debugging."""
        return (
            f"OffloadPool(kind={self.kind!r}, live={len(self._live)}, "
            f"closed={self._closed})"
        )
