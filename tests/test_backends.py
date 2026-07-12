"""Execution backends: resolution, transport validation, trivial-task runs (2.2)."""

import functools
import warnings
from typing import Any

import pytest

from llmsim.parallel import backends
from llmsim.parallel.backends import (
    CancelToken,
    ExecutionBackend,
    FactoryValidationError,
    TransportError,
    _SharedCancelToken,
    preflight_config,
    validate_factory,
    warn_if_gil_reenabled,
)
from llmsim.rand.streams import SeedTree
from tests.parallel_support import trivial_task

_MASTER = 20260712


# --- backend="auto" resolution and explicit selection. -----------------------


def test_auto_picks_threads_when_gil_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backends, "_runtime_gil_enabled", lambda: False)
    assert ExecutionBackend.resolve("auto").kind == "threads"


def test_auto_picks_processes_on_gil_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends, "_runtime_gil_enabled", lambda: True)
    assert ExecutionBackend.resolve("auto").kind == "processes"


def test_explicit_backend_honored_verbatim() -> None:
    for kind in ("threads", "interpreters", "processes"):
        assert ExecutionBackend.resolve(kind).kind == kind


def test_unknown_backend_rejected_with_valid_options() -> None:
    with pytest.raises(ValueError, match="threads.*interpreters.*processes"):
        ExecutionBackend.resolve("gpu")
    with pytest.raises(ValueError, match="auto"):
        ExecutionBackend("auto")  # concrete constructor rejects the sentinel


def test_backend_traits() -> None:
    assert not ExecutionBackend("threads").requires_transport
    assert ExecutionBackend("interpreters").requires_transport
    assert ExecutionBackend("processes").requires_transport
    assert ExecutionBackend("threads").supports_shared_cancellation
    assert not ExecutionBackend("processes").supports_shared_cancellation


# --- Every backend runs a trivial importable task to identical results. ------


@pytest.mark.parametrize("kind", ["threads", "interpreters", "processes"])
def test_backend_runs_trivial_task(kind: str) -> None:
    stream = SeedTree(_MASTER).stream(0, 0)
    expected = trivial_task(stream, {"x": 1})
    with ExecutionBackend(kind).executor(max_workers=2) as pool:
        assert pool.submit(trivial_task, stream, {"x": 1}).result(60) == expected


def test_max_workers_none_defaults_sensibly() -> None:
    with ExecutionBackend("threads").executor(max_workers=None) as pool:
        assert pool._max_workers >= 1  # type: ignore[attr-defined]


# --- Factory-importability validation (actionable errors). -------------------


def test_module_level_factory_is_accepted() -> None:
    validate_factory(trivial_task)


def test_lambda_rejected_with_actionable_fix() -> None:
    with pytest.raises(
        FactoryValidationError, match="lambda.*top level of an importable"
    ):
        validate_factory(lambda stream, config: None)


def test_local_function_rejected() -> None:
    def local_factory(stream: Any, config: Any) -> None:
        return None

    with pytest.raises(FactoryValidationError, match="local function"):
        validate_factory(local_factory)


def test_non_callable_rejected() -> None:
    with pytest.raises(FactoryValidationError, match="callable"):
        validate_factory("not a function")  # type: ignore[arg-type]


def test_partial_rejected() -> None:
    with pytest.raises(FactoryValidationError):
        validate_factory(functools.partial(trivial_task))


# --- Config picklability preflight. ------------------------------------------


def test_picklable_config_passes_preflight() -> None:
    preflight_config({"rate": 0.9}, 0)


def test_unpicklable_config_raises_actionable_error() -> None:
    with pytest.raises(TransportError, match="config 3"):
        preflight_config(lambda: None, 3)


# --- Cancellation tokens. -----------------------------------------------------


def test_base_token_is_inert_and_picklable() -> None:
    import pickle

    token = CancelToken()
    assert token.cancelled is False
    # Round-trips our own in-process object (executor transport); nothing
    # untrusted is ever loaded.
    clone = pickle.loads(pickle.dumps(token))
    assert clone.cancelled is False


def test_shared_token_observes_cancel() -> None:
    token = _SharedCancelToken()
    assert token.cancelled is False
    token._cancel()
    assert token.cancelled is True


# --- GIL re-enable detection. --------------------------------------------------


def test_gil_reenable_warns_and_names_import() -> None:
    with pytest.warns(RuntimeWarning, match="legacy_ext"):
        warn_if_gil_reenabled("legacy_ext", gil_before=False, gil_after=True)


def test_no_warning_when_gil_state_unchanged() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_if_gil_reenabled("fine_module", gil_before=False, gil_after=False)
        warn_if_gil_reenabled("gil_build", gil_before=True, gil_after=True)
