"""The ``ExecutionBackend`` abstraction.

One code path over ``ThreadPoolExecutor`` (free-threaded 3.14t),
``InterpreterPoolExecutor`` (PEP 734, opt-in), and ``ProcessPoolExecutor``.
Work is submitted as an importable callable plus a seed spec and config --
never live objects -- so all three backends behave identically and switching
between them is a one-word change.

Backend selection (``backend="auto"``, normative decision): the free-threaded
build (GIL disabled) picks ``"threads"``; a GIL build picks the battle-tested
``"processes"``. ``"interpreters"`` is opt-in via ``backend="interpreters"``
while PEP 734 matures. An explicit ``backend=`` argument is always honored
verbatim.

Cancellation granularity per backend (one API, two granularities): the thread
backend shares a live :class:`CancelToken` with workers, so a token-aware
factory is cancelled mid-replication; interpreter and process workers cannot
see a parent token and are always cancelled at replication granularity
(pending submissions are ``Future.cancel()``-ed, running ones finish).
"""

import importlib
import pickle
import sys
import threading
import warnings
from collections.abc import Callable
from concurrent.futures import (
    Executor,
    InterpreterPoolExecutor,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
)
from contextvars import ContextVar
from os import process_cpu_count
from typing import Any, Literal

#: The public backend-selection vocabulary. ``"auto"`` resolves per build.
BackendName = Literal["auto", "threads", "interpreters", "processes"]

#: The concrete backend kind of the Experiment worker currently executing on
#: this thread, or ``None`` outside any worker. Set by the replication runner
#: around the factory call; read by the offload pool's nested-pool rule. A
#: ``ContextVar`` scopes the flag to the worker's own thread/interpreter, so a
#: thread-backend coordinator never sees its workers' value.
_worker_backend: ContextVar[str | None] = ContextVar(
    "llmsim_worker_backend", default=None
)

#: Concrete backend kinds, in documentation order.
_CONCRETE_KINDS = ("threads", "interpreters", "processes")

#: Executor nestings broken upstream on CPython 3.14, as ``(worker kind,
#: nested pool kind)`` pairs -- a property of the executors themselves, kept
#: here beside ``_worker_backend`` so every pool-nesting feature consults one
#: table. Spike-verified: a process pool created inside a subinterpreter
#: worker dies with ``BrokenProcessPool`` (multiprocessing is not
#: subinterpreter-safe); every other combination works.
_BROKEN_NESTINGS = frozenset({("interpreters", "processes")})


class FactoryValidationError(TypeError):
    """The factory cannot be transported to workers by reference.

    Raised at :class:`~llmsim.parallel.replicate.Experiment` construction when
    the factory is not an importable module-level callable (a lambda, a local
    function or closure, or anything not reachable as
    ``module.qualified_name``). The fix is always the same: define the factory
    with ``def`` at the top level of an importable module.
    """


class TransportError(RuntimeError):
    """A config or result cannot cross the backend's transport boundary.

    Names the offending config (and replication, when known) so a failing
    study points at the exact object to fix -- never a silent partial run.
    """


def _runtime_gil_enabled() -> bool:
    """Report whether the GIL is enabled in this running interpreter.

    A seam over ``sys._is_gil_enabled()`` so tests can simulate either build.
    """
    return sys._is_gil_enabled()


def _inherit_sys_path(entries: tuple[str, ...]) -> None:
    """Make a worker interpreter's ``sys.path`` match the coordinator's.

    Subinterpreters start from the interpreter's base path configuration and
    do not see additions the coordinator made at runtime (a test harness's
    ``pythonpath``, for example); process workers inherit ``sys.path`` through
    the spawn machinery and threads share it outright, so only the interpreter
    backend installs this initializer. The parent's *exact order* is
    replicated -- merely appending missing entries would flip import
    precedence for colliding module names, and then ``backend="interpreters"``
    would not run the same code as the other backends.
    """
    sys.path[:] = entries


class CancelToken:
    """The cancellation handle a factory may consult between ``step()`` calls.

    This base token is inert -- :attr:`cancelled` is always ``False`` -- and
    picklable; it is what factories receive on the interpreter and process
    backends, where a parent's cancellation cannot be observed mid-run. On the
    thread backend the factory receives a live shared token instead, so
    checking :attr:`cancelled` between steps gives mid-replication
    cancellation. Factories annotate the parameter as ``CancelToken`` and need
    not know which they got.
    """

    __slots__ = ()

    @property
    def cancelled(self) -> bool:
        """Whether the experiment has been cancelled (always ``False`` here)."""
        return False

    def _cancel(self) -> None:
        """Do nothing: isolated workers cannot observe a parent's cancel."""


class _SharedCancelToken(CancelToken):
    """A live token shared between the coordinator and thread-backend workers."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        """Whether :meth:`_cancel` has been called."""
        return self._event.is_set()

    def _cancel(self) -> None:
        self._event.set()


class ExecutionBackend:
    """One executor-shaped interface over threads, interpreters, and processes.

    Instances are thin and stateless: they know their concrete *kind*, how to
    create the matching ``concurrent.futures`` executor, and the two traits
    the replication runner branches on (whether payloads cross a pickle
    boundary, and whether workers can share a live cancellation token).
    """

    __slots__ = ("kind",)

    def __init__(self, kind: str) -> None:
        """Wrap the concrete backend *kind* (``"auto"`` is not accepted here)."""
        if kind not in _CONCRETE_KINDS:
            raise ValueError(
                f"unknown backend {kind!r}; expected one of "
                f"{', '.join(repr(k) for k in _CONCRETE_KINDS)} (or 'auto')"
            )
        #: The concrete backend name: ``"threads"``, ``"interpreters"``, or
        #: ``"processes"``.
        self.kind = kind

    @classmethod
    def resolve(cls, backend: str = "auto") -> "ExecutionBackend":
        """Resolve a backend name, honoring an explicit choice verbatim.

        ``"auto"`` picks ``"threads"`` on the free-threaded build (GIL
        disabled) and ``"processes"`` on a GIL build.
        """
        if backend == "auto":
            return cls("threads" if not _runtime_gil_enabled() else "processes")
        return cls(backend)

    @property
    def requires_transport(self) -> bool:
        """Whether payloads cross a pickle boundary on this backend."""
        return self.kind != "threads"

    @property
    def supports_shared_cancellation(self) -> bool:
        """Whether workers can observe a live parent token mid-replication."""
        return self.kind == "threads"

    def cancel_token(self) -> CancelToken:
        """Return the cancellation token this backend's workers should receive.

        A live shared token on the thread backend (mid-replication cancel for
        token-aware factories); the inert base token elsewhere, where isolated
        workers cannot observe the parent. Callers fire either uniformly via
        ``token._cancel()``.
        """
        if self.supports_shared_cancellation:
            return _SharedCancelToken()
        return CancelToken()

    def executor(self, max_workers: int | None = None) -> Executor:
        """Create this backend's executor with *max_workers* workers.

        ``max_workers=None`` defaults to ``os.process_cpu_count()`` on every
        backend, so worker count is uniform and predictable rather than
        executor-specific.
        """
        if max_workers is None:
            max_workers = process_cpu_count() or 1
        if self.kind == "threads":
            return ThreadPoolExecutor(max_workers=max_workers)
        if self.kind == "interpreters":
            # Warm pool: one executor reuses its interpreters across every
            # submission, so a model module is imported once per worker, not
            # once per replication.
            return InterpreterPoolExecutor(
                max_workers=max_workers,
                initializer=_inherit_sys_path,
                initargs=(tuple(sys.path),),
            )
        return ProcessPoolExecutor(max_workers=max_workers)

    def __repr__(self) -> str:
        """Show the concrete kind for debugging."""
        return f"ExecutionBackend(kind={self.kind!r})"


#: The one actionable sentence for anything that fails to pickle across a
#: backend transport; shared so the guidance cannot drift between error sites.
PICKLE_HINT = (
    "make it a plain picklable value (numbers, strings, dicts, dataclasses "
    "without live handles)"
)


def resolve_qualname(namespace: Any, qualname: str) -> Any:
    """Walk dotted *qualname* parts from *namespace* (a module, usually).

    The single resolution rule shared by construction-time validation and the
    worker-side import, so "validated at construction" and "importable in the
    worker" cannot disagree. Raises ``AttributeError`` when a part is missing.
    """
    target = namespace
    for part in qualname.split("."):
        target = getattr(target, part)
    return target


def import_factory(module_name: str, qualname: str) -> Callable[..., Any]:
    """Import a validated callable by reference on the worker side.

    The deserializing half of the "work is submitted as an importable
    callable" rule, kept beside :func:`resolve_qualname` (the validating
    half) so the two cannot disagree. Shared by the replication and offload
    worker runners.
    """
    module = importlib.import_module(module_name)
    return resolve_qualname(module, qualname)  # type: ignore[no-any-return]


def validate_factory(factory: Callable[..., Any]) -> None:
    """Reject a factory that workers could not import by reference.

    Every backend receives the factory as ``(module, qualified name)`` and
    re-imports it worker-side, so it must be a module-level callable. Raises
    :class:`FactoryValidationError` with the concrete fix for lambdas, local
    functions/closures, and objects not reachable from their module.
    """
    fix = (
        "define the factory with 'def' at the top level of an importable "
        "module so workers can import it by name"
    )
    if not callable(factory):
        raise FactoryValidationError(
            f"factory must be callable, got {type(factory).__name__!r}; {fix}"
        )
    module_name = getattr(factory, "__module__", None)
    qualname = getattr(factory, "__qualname__", None)
    if module_name is None or qualname is None:
        raise FactoryValidationError(
            f"factory {factory!r} has no importable module/qualified name; {fix}"
        )
    if qualname == "<lambda>":
        raise FactoryValidationError(
            f"factory is a lambda, which cannot be imported by name; {fix}"
        )
    if "<locals>" in qualname:
        raise FactoryValidationError(
            f"factory {qualname!r} is a local function or closure defined "
            f"inside another function; {fix}"
        )
    try:
        resolved = resolve_qualname(sys.modules[module_name], qualname)
    except KeyError, AttributeError:
        resolved = None
    if resolved is not factory:
        raise FactoryValidationError(
            f"factory {qualname!r} is not reachable as "
            f"{module_name}.{qualname}, so workers cannot import it; {fix}"
        )


def preflight_pickle(payload: Any, described_as: str, alternatives: str) -> bytes:
    """Pickle *payload* for a worker transport, or fail actionably.

    The one transport-preflight rule: callers describe the payload
    (``described_as``) and name the backend switches that avoid the boundary
    (``alternatives``); the pickled bytes are returned so a caller shipping
    them pays for serialization exactly once. Raises :class:`TransportError`.
    """
    try:
        return pickle.dumps(payload)
    except Exception as error:
        raise TransportError(
            f"{described_as} cannot be pickled for the worker transport: "
            f"{error}; {PICKLE_HINT} or use {alternatives}"
        ) from error


def preflight_config(config: Any, config_index: int) -> None:
    """Verify *config* survives a pickle boundary before any work is dispatched.

    Called once per config when the resolved backend requires transport
    (interpreters or processes). Raises :class:`TransportError` naming the
    offending config index; the thread backend never calls this, so
    unpicklable configs remain usable for pure-thread studies.
    """
    preflight_pickle(config, f"config {config_index} ({config!r})", "backend='threads'")


def warn_if_gil_reenabled(module_name: str, gil_before: bool, gil_after: bool) -> None:
    """Warn loudly when importing a model module re-enabled the GIL.

    On the free-threaded build, importing an extension module that does not
    declare free-threading support re-enables the GIL process-wide and
    silently serializes every thread-backend replication. Detection compares
    ``sys._is_gil_enabled()`` before and after the worker-side model import
    and names the offending import so the fix is actionable.
    """
    if gil_after and not gil_before:
        warnings.warn(
            f"importing {module_name!r} re-enabled the GIL in this worker: "
            f"thread-backend replications will run serialized from here on. "
            f"An imported extension module likely predates free-threading "
            f"support; switch to backend='processes' or remove the import",
            RuntimeWarning,
            stacklevel=2,
        )
