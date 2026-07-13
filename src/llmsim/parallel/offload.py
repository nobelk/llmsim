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
    _BROKEN_NESTINGS,
    ExecutionBackend,
    _worker_backend,
    import_factory,
    preflight_pickle,
    validate_factory,
)

T = TypeVar("T")

#: The offload backend vocabulary: the Phase 2 names plus the offload-local
#: ``"inline"`` reference mode (run synchronously on the owning thread).
OffloadBackendName = Literal["auto", "inline", "threads", "interpreters", "processes"]


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
    fn = import_factory(module_name, qualname)
    return fn(*args, **kwargs)


def _run_offload_packed(module_name: str, qualname: str, packed: bytes) -> Any:
    """Run one payload whose arguments arrived as preflighted pickle bytes.

    Transport backends ship the bytes the submission-time preflight already
    produced, so arguments are serialized exactly once per offload. The bytes
    were pickled by this simulation's own coordinator -- the same trust
    boundary as ``concurrent.futures``' own argument transport (the rule
    ``replicate._decode_payload`` documents).
    """
    args, kwargs = pickle.loads(packed)
    return _run_offload(module_name, qualname, args, kwargs)


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

    __slots__ = ("_pool", "_future", "_qualname", "_strict", "_abandoned", "_earliest")

    def __init__(
        self,
        sim: "Sim",
        pool: "OffloadPool",
        future: "Future[Any]",
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
        #: The payload's outcome. The inline mode fills a pre-completed
        #: Future at submission, so every mode resolves through one path.
        self._future = future
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
            # The placeholder (_ok=True, _value=None) is already the
            # "discarded" outcome; deliver it without touching the future.
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

    __slots__ = (
        "_sim",
        "_backend",
        "_max_workers",
        "_executor",
        "_pending",
        "_strict_live",
        "_closed",
    )

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
        #: The resolved pooled backend, or ``None`` for the inline mode.
        self._backend: ExecutionBackend | None = self._resolve_backend(backend)
        self._sim = sim
        self._max_workers = max_workers
        self._executor: Executor | None = None
        #: Undelivered non-strict events, polled between steps. Strict events
        #: are tracked separately so the per-step poll never scans them.
        self._pending: list[OffloadEvent[Any]] = []
        #: Unresolved strict events, held only so :meth:`close` can abandon
        #: them; identity-keyed for O(1) removal at slot resolution (removal
        #: order never feeds the schedule). Owner-thread only -- no lock.
        self._strict_live: set[OffloadEvent[Any]] = set()
        self._closed = False
        sim._offload = self

    @staticmethod
    def _resolve_backend(backend: OffloadBackendName) -> ExecutionBackend | None:
        """Resolve *backend* (``None`` = inline), honoring explicit choices."""
        worker_kind = _worker_backend.get()
        if backend == "inline":
            return None
        if backend == "auto":
            if worker_kind is not None:
                # Nested-pool rule: inside an Experiment worker, default to
                # inline rather than oversubscribing nproc x nproc workers.
                return None
            return ExecutionBackend.resolve("auto")
        if worker_kind is not None and (worker_kind, backend) in _BROKEN_NESTINGS:
            raise RuntimeError(
                f"offload backend {backend!r} cannot run inside an "
                f"{worker_kind!r}-backend Experiment worker: multiprocessing "
                f"is not subinterpreter-safe (BrokenProcessPool). Use "
                f"backend='inline' (the nested default), 'threads', or "
                f"'interpreters', or run the Experiment on another backend"
            )
        return ExecutionBackend(backend)

    @property
    def kind(self) -> str:
        """The resolved concrete mode: ``"inline"`` or a Phase 2 backend kind."""
        return "inline" if self._backend is None else self._backend.kind

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
        if not strict and sim.debug:
            warnings.warn(
                f"non-strict offload of {fn.__qualname__!r} at t={sim.now}: "
                f"delivery time depends on wall-clock completion, so event "
                f"ordering is not reproducible (pass delay=... with "
                f"strict=True for a deterministic completion slot)",
                NonStrictOffloadWarning,
                stacklevel=3,
            )

        backend = self._backend
        future: Future[Any]
        if backend is None:
            # The inline reference: run now on the owning thread, deliver at
            # the slot through a pre-completed future -- literally the same
            # resolution path as the pooled backends.
            future = Future()
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as raised:  # noqa: BLE001 -- match executors
                future.set_exception(raised)
        elif backend.requires_transport:
            packed = preflight_pickle(
                (args, kwargs),
                f"arguments of offloaded {fn.__qualname__!r}",
                "backend='threads' or backend='inline'",
            )
            future = self._ensure_executor().submit(
                _run_offload_packed, fn.__module__, fn.__qualname__, packed
            )
        else:
            future = self._ensure_executor().submit(
                _run_offload, fn.__module__, fn.__qualname__, args, kwargs
            )

        event: OffloadEvent[Any] = OffloadEvent(
            sim, self, future, fn.__qualname__, strict=strict
        )
        if strict:
            self._strict_live.add(event)
            assert delay is not None
            sim.schedule(event, NORMAL, delay)
        else:
            event._earliest = sim.now + (delay or 0.0)
            self._pending.append(event)
        return event

    def poll(self) -> None:
        """Deliver completed non-strict results (called between steps)."""
        pending = self._pending
        if not pending:
            return
        # Allocation-free in the common nothing-completed case: the surviving
        # list is only rebuilt once a delivery actually happens.
        remaining: list[OffloadEvent[Any]] | None = None
        for index, event in enumerate(pending):
            if event._future.done():
                if remaining is None:
                    remaining = pending[:index]
                self._deliver(event)
            elif remaining is not None:
                remaining.append(event)
        if remaining is not None:
            self._pending = remaining

    def drain(self) -> bool:
        """Block for outstanding non-strict work once the schedule empties.

        The run-end rule: a non-strict result is never silently dropped --
        ``run()`` waits wall-clock for at least one outstanding payload,
        delivers everything then complete, and keeps stepping.
        """
        pending = self._pending
        if not pending:
            return False
        wait([event._future for event in pending], return_when=FIRST_COMPLETED)
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
        for event in list(self._pending) + list(self._strict_live):
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
        if event._strict:
            self._strict_live.discard(event)
        else:
            try:
                self._pending.remove(event)
            except ValueError:
                pass

    def _ensure_executor(self) -> Executor:
        """Create the executor on first pooled submission (lazy startup)."""
        if self._executor is None:
            assert self._backend is not None
            self._executor = self._backend.executor(self._max_workers)
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
        outstanding = len(self._pending) + len(self._strict_live)
        return (
            f"OffloadPool(kind={self.kind!r}, outstanding={outstanding}, "
            f"closed={self._closed})"
        )
