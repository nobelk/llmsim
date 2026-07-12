"""The replication runner -- the flagship parallel capability.

Runs N independent replications of a model across cores and collects their
results keyed by ``(config index, replication index)``, never by completion
order, so the outcome is identical regardless of how the work is scheduled.
Home to :class:`Experiment`, :func:`run_replications`, and
:class:`ReplicationResult`.

The 80% use case is a module-level factory plus one call::

    def my_model(stream: SeedStream, config: dict[str, float]) -> dict[str, float]:
        sim = Sim(rng=stream.rng())
        ...
        return kpis

    results = Experiment(my_model, configs, master_seed=42).run(replications=100)

The factory contract: a module-level callable (validated at construction)
called as ``factory(stream, config)``, where *stream* is the
:class:`~llmsim.rand.streams.SeedStream` derived for this exact
``(config_index, replication_index)`` and *config* is the caller's config
object. A factory that declares a third positional parameter is
cancellation-aware and receives a :class:`~llmsim.parallel.backends.CancelToken`
to consult between ``step()`` calls (live on the thread backend, inert on
interpreter/process backends -- one API, two granularities).

Failure contract (fail-fast): the first failing replication cancels all
pending work and raises :class:`ReplicationError` naming the offending
``(config_index, replication_index)`` with the original exception chained --
never a silent partial result set.
"""

import importlib
import inspect
import pickle
import sys
from collections.abc import Callable, Iterator, Sequence
from compression import zstd
from concurrent.futures import Executor, Future
from itertools import product
from queue import SimpleQueue
from types import TracebackType
from typing import Any

from llmsim.parallel.backends import (
    PICKLE_HINT,
    BackendName,
    CancelToken,
    ExecutionBackend,
    TransportError,
    preflight_config,
    resolve_qualname,
    validate_factory,
    warn_if_gil_reenabled,
)
from llmsim.rand.streams import SeedStream, SeedTree

#: The factory shape: ``(stream, config)`` or ``(stream, config, cancel)``.
Factory = Callable[..., Any]

#: A result set: ``(config_index, replication_index)`` -> result, in key order.
ResultSet = dict[tuple[int, int], "ReplicationResult"]


class ReplicationError(RuntimeError):
    """One replication failed (fail-fast contract).

    Names the offending ``(config_index, replication_index)`` and chains the
    worker's original exception as ``__cause__``. Raising instead of returning
    a partial result set keeps a study's output all-or-nothing.
    """


class ReplicationResult:
    """One replication's identity, seed, and returned value.

    Results are keyed and compared by ``(config_index, replication_index)``
    plus the derived seed and the factory's value; completion order is nowhere
    in the type, by construction.
    """

    __slots__ = ("config_index", "replication_index", "seed", "_payload", "_spooled")

    def __init__(
        self,
        config_index: int,
        replication_index: int,
        seed: int,
        payload: Any,
        *,
        spooled: bool = False,
    ) -> None:
        """Wrap one replication's *payload* (raw, or zstd-spooled bytes)."""
        #: Position of the config in the experiment's config list.
        self.config_index = config_index
        #: Zero-based replication number within the config.
        self.replication_index = replication_index
        #: The 128-bit child seed this replication's stream was built from.
        self.seed = seed
        self._payload = payload
        self._spooled = spooled

    @property
    def spooled(self) -> bool:
        """Whether the value is held as zstd-compressed bytes (``spool=True``)."""
        return self._spooled

    @property
    def value(self) -> Any:
        """The factory's returned value.

        When the experiment spools (``spool=True``), the value is stored as
        zstd-compressed pickle bytes to bound peak memory and decompressed on
        each access; hold onto the returned object if you read it repeatedly.
        """
        if self._spooled:
            return _decode_payload(self._payload, transported=True, spooled=True)
        return self._payload

    def __eq__(self, other: object) -> bool:
        """Compare identity, seed, and value (not spooling representation)."""
        if not isinstance(other, ReplicationResult):
            return NotImplemented
        return (
            self.config_index == other.config_index
            and self.replication_index == other.replication_index
            and self.seed == other.seed
            and self.value == other.value
        )

    def __repr__(self) -> str:
        """Show the identity key and spooling state for debugging."""
        return (
            f"ReplicationResult(config_index={self.config_index}, "
            f"replication_index={self.replication_index}, seed={self.seed}, "
            f"spooled={self._spooled})"
        )


def _import_factory(module_name: str, qualname: str) -> Factory:
    """Import the factory by reference on the worker side.

    Uses the same :func:`~llmsim.parallel.backends.resolve_qualname` rule the
    construction-time validator used, so the two cannot disagree.
    """
    module = importlib.import_module(module_name)
    return resolve_qualname(module, qualname)  # type: ignore[no-any-return]


def _encode_payload(
    value: Any, stream: SeedStream, *, transport: bool, spool: bool
) -> Any:
    """Encode one result for the trip back to the coordinator (worker side).

    The wire format, defined here and decoded only by :func:`_decode_payload`:
    ``(transport=False, spool=False)`` -> the raw value; ``transport`` ->
    pickle bytes; ``spool`` -> zstd-compressed pickle bytes. Pickling happens
    *here*, not in the executor, so an unpicklable result raises the same
    actionable :class:`TransportError` on every isolated backend.
    """
    if not (transport or spool):
        return value
    try:
        payload = pickle.dumps(value)
    except Exception as error:
        raise TransportError(
            f"result of (config_index={stream.config_index}, "
            f"replication_index={stream.replication_index}) is a "
            f"{type(value).__name__} that cannot be pickled back from the "
            f"worker: {error}; {PICKLE_HINT}"
        ) from error
    return zstd.compress(payload) if spool else payload


def _decode_payload(payload: Any, *, transported: bool, spooled: bool) -> Any:
    """Decode what :func:`_encode_payload` produced (coordinator side).

    The bytes were pickled by this experiment's own worker runner -- the same
    trust boundary as ``concurrent.futures``' own transport.
    """
    if spooled:
        return pickle.loads(zstd.decompress(payload))
    if transported:
        return pickle.loads(payload)
    return payload


def _run_replication(
    module_name: str,
    qualname: str,
    stream: SeedStream,
    config: Any,
    accepts_cancel: bool,
    cancel: CancelToken,
    transport: bool,
    spool: bool,
) -> Any:
    """Run one replication worker-side and encode its result for transport.

    This is the single payload every backend executes: the factory arrives as
    an ``(module, qualified name)`` reference, the seed as a picklable
    :class:`~llmsim.rand.streams.SeedStream` spec -- never live objects.

    Transport is validated, not assumed (normative decision): on backends
    whose results cross an isolation boundary the value is pickled *here*, so
    an unpicklable result raises an actionable :class:`TransportError` naming
    the offending ``(config, replication)`` uniformly on both the process and
    interpreter backends. With ``spool=True`` the pickled bytes are further
    zstd-compressed to bound coordinator memory.
    """
    gil_before = sys._is_gil_enabled()
    factory = _import_factory(module_name, qualname)
    warn_if_gil_reenabled(module_name, gil_before, sys._is_gil_enabled())

    if accepts_cancel:
        value = factory(stream, config, cancel)
    else:
        value = factory(stream, config)
    return _encode_payload(value, stream, transport=transport, spool=spool)


class Experiment:
    """N replications x M configs of one model factory, reproducibly.

    Args:
        factory: A module-level callable ``factory(stream, config)`` (or
            ``factory(stream, config, cancel)`` to opt into cooperative
            cancellation). Validated for importability at construction.
        configs: The experiment's configurations; each must survive the
            chosen backend's transport (preflighted per run when the backend
            pickles).
        master_seed: The explicit study seed (required, keyword-only; no
            ambient default). Every replication's stream derives from it via
            the seed tree, so the same seed reproduces the same study.
        spool: When ``True``, worker results are zstd-compressed pickle
            bytes decompressed lazily on access -- bounds peak coordinator
            memory for large per-replication outputs.

    Use as a context manager to cancel any in-flight work on exit::

        with Experiment(my_model, configs, master_seed=42) as exp:
            for result in exp.iter_results(replications=100):
                if good_enough(result):
                    break  # __exit__ cancels the rest
    """

    __slots__ = (
        "_factory_module",
        "_factory_qualname",
        "_accepts_cancel",
        "configs",
        "spool",
        "_tree",
        "_cancelled",
        "_token",
        "_executor",
    )

    def __init__(
        self,
        factory: Factory,
        configs: Sequence[Any],
        *,
        master_seed: int,
        spool: bool = False,
    ) -> None:
        """Validate the factory and root the seed tree at *master_seed*."""
        validate_factory(factory)
        self._factory_module: str = factory.__module__
        self._factory_qualname: str = factory.__qualname__
        self._accepts_cancel = _accepts_cancel_parameter(factory)
        #: The experiment's configurations, in the order that keys results.
        self.configs: list[Any] = list(configs)
        #: Whether results are zstd-spooled (see :class:`ReplicationResult`).
        self.spool = spool
        self._tree = SeedTree(master_seed)
        self._cancelled = False
        self._token: CancelToken | None = None
        self._executor: Executor | None = None

    @property
    def master_seed(self) -> int:
        """The explicit study seed the whole seed tree derives from."""
        return self._tree.master_seed

    def run(
        self,
        replications: int,
        *,
        backend: BackendName = "auto",
        max_workers: int | None = None,
    ) -> ResultSet:
        """Run the full study and return results keyed by identity.

        The returned dict maps ``(config_index, replication_index)`` to
        :class:`ReplicationResult` and iterates in sorted key order --
        completion order never leaks into the result set.
        """
        collected: ResultSet = {}
        for result in self.iter_results(
            replications, backend=backend, max_workers=max_workers
        ):
            collected[(result.config_index, result.replication_index)] = result
        return {key: collected[key] for key in sorted(collected)}

    def iter_results(
        self,
        replications: int,
        *,
        backend: BackendName = "auto",
        max_workers: int | None = None,
    ) -> Iterator[ReplicationResult]:
        """Yield results as they complete (each exactly once, identity-keyed).

        Aggregation stays order-insensitive because every result carries its
        ``(config_index, replication_index)``; only the *arrival* order is
        completion-dependent. After :meth:`cancel`, replications that already
        finished are still yielded, cancelled ones are not, and no new work is
        dispatched.
        """
        backend_obj = ExecutionBackend.resolve(backend)
        if backend_obj.requires_transport:
            for config_index, config in enumerate(self.configs):
                preflight_config(config, config_index)

        self._cancelled = False
        worker_token = backend_obj.cancel_token()
        executor = backend_obj.executor(max_workers)
        futures: dict[Future[Any], tuple[int, int]] = {}
        # Completion is observed through add_done_callback, which fires for
        # set_result, set_exception, AND Future.cancel(). as_completed()/wait()
        # would deadlock here: they treat a future cancelled by Future.cancel()
        # as still pending until an executor worker acknowledges it -- and a
        # queue-drained work item never reaches a worker.
        completion_queue: SimpleQueue[Future[Any]] = SimpleQueue()
        self._token = worker_token
        self._executor = executor
        try:
            for (config_index, config), replication_index in product(
                enumerate(self.configs), range(replications)
            ):
                if self._cancelled:
                    break
                future = executor.submit(
                    _run_replication,
                    self._factory_module,
                    self._factory_qualname,
                    self._tree.stream(config_index, replication_index),
                    config,
                    self._accepts_cancel,
                    worker_token,
                    backend_obj.requires_transport,
                    self.spool,
                )
                futures[future] = (config_index, replication_index)
                future.add_done_callback(completion_queue.put)

            for _ in range(len(futures)):
                future = completion_queue.get()
                if future.cancelled():
                    continue
                config_index, replication_index = futures[future]
                error = future.exception()
                if error is not None:
                    self.cancel()
                    if isinstance(error, TransportError):
                        raise error
                    raise ReplicationError(
                        f"replication (config_index={config_index}, "
                        f"replication_index={replication_index}) failed with "
                        f"{type(error).__name__}: {error}"
                    ) from error
                yield self._make_result(
                    config_index,
                    replication_index,
                    future,
                    transported=backend_obj.requires_transport,
                )
        finally:
            self._token = None
            self._executor = None
            executor.shutdown(wait=True, cancel_futures=True)

    def cancel(self) -> None:
        """Cancel the in-flight run (one API, two granularities).

        Stops dispatching queued work and ``Future.cancel()``-s pending
        submissions on every backend. On the thread backend the shared token
        additionally fires, so a cancellation-aware factory stops
        mid-replication; a factory that owns its own ``sim.run()`` -- and any
        interpreter/process worker -- finishes its current replication first
        (replication granularity). Already-collected results stay valid.
        """
        self._cancelled = True
        if self._token is not None:
            self._token._cancel()
        if self._executor is not None:
            # Cancels every not-yet-started future; each cancellation lands in
            # the completion queue via its done-callback.
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _make_result(
        self,
        config_index: int,
        replication_index: int,
        future: Future[Any],
        *,
        transported: bool,
    ) -> ReplicationResult:
        """Decode one finished future into a :class:`ReplicationResult`."""
        payload = future.result()
        seed = self._tree.child_seed(config_index, replication_index)
        if self.spool:
            # Keep the compressed bytes; ReplicationResult decodes lazily.
            return ReplicationResult(
                config_index, replication_index, seed, payload, spooled=True
            )
        return ReplicationResult(
            config_index,
            replication_index,
            seed,
            _decode_payload(payload, transported=transported, spooled=False),
        )

    def __enter__(self) -> "Experiment":
        """Return self; pair with ``__exit__`` for cancel-on-exit."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Cancel any in-flight work when the ``with`` block exits."""
        self.cancel()

    def __repr__(self) -> str:
        """Show the factory reference, config count, and seed for debugging."""
        return (
            f"Experiment(factory={self._factory_module}."
            f"{self._factory_qualname}, configs={len(self.configs)}, "
            f"master_seed={self.master_seed})"
        )


def _accepts_cancel_parameter(factory: Factory) -> bool:
    """Whether *factory* declares a third positional (cancel-token) parameter."""
    signature = inspect.signature(factory)
    positional = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_var_positional = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    return len(positional) >= 3 or has_var_positional


def run_replications(
    factory: Factory,
    configs: Sequence[Any],
    *,
    master_seed: int,
    replications: int,
    backend: BackendName = "auto",
    max_workers: int | None = None,
) -> ResultSet:
    """Run one study functionally: construct, run, and return the result set.

    Equivalent to ``Experiment(factory, configs,
    master_seed=master_seed).run(replications, backend=backend,
    max_workers=max_workers)``.
    """
    experiment = Experiment(factory, configs, master_seed=master_seed)
    return experiment.run(replications, backend=backend, max_workers=max_workers)
