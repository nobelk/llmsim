"""Offload backend conformance: identical trace and values everywhere (4.1)."""

import os

import pytest

from llmsim import Experiment, ReplicationError
from llmsim.parallel.backends import _worker_backend
from llmsim.parallel.offload import OffloadPool
from llmsim.core.sim import Sim
from tests.parallel_support import (
    nested_auto_offload_factory,
    nested_processes_offload_factory,
    nested_threads_offload_factory,
    offload_model_kpis,
)

_MASTER = 20260712

_POOLED_BACKENDS = ("threads", "interpreters", "processes")

#: The spec's enumerated worker counts.
_WORKER_COUNTS = (1, 2, 4, os.process_cpu_count() or 1)


@pytest.fixture(scope="module")
def inline_reference() -> tuple[object, object]:
    """The sequential reference every pooled run must match bitwise."""
    return offload_model_kpis("inline", None, _MASTER)


class TestBackendConformance:
    """Same trace, same outcomes, on every backend and worker count."""

    @pytest.mark.parametrize("backend", _POOLED_BACKENDS)
    def test_backend_matches_inline_reference(
        self, backend: str, inline_reference: tuple[object, object]
    ) -> None:
        reference_trace, reference_outcomes = inline_reference
        records, outcomes = offload_model_kpis(backend, 2, _MASTER)
        assert records == reference_trace, f"{backend} trace diverged"
        assert outcomes == reference_outcomes

    @pytest.mark.parametrize("max_workers", _WORKER_COUNTS)
    def test_worker_count_never_changes_results(
        self, max_workers: int, inline_reference: tuple[object, object]
    ) -> None:
        reference_trace, reference_outcomes = inline_reference
        records, outcomes = offload_model_kpis("processes", max_workers, _MASTER)
        assert records == reference_trace, f"{max_workers} workers diverged"
        assert outcomes == reference_outcomes

    def test_auto_backend_matches_reference_on_this_build(
        self, inline_reference: tuple[object, object]
    ) -> None:
        reference_trace, reference_outcomes = inline_reference
        records, outcomes = offload_model_kpis("auto", 2, _MASTER)
        assert records == reference_trace
        assert outcomes == reference_outcomes


class TestNestedPoolRule:
    """Offload inside Experiment workers: inline by default, opt-in pooled."""

    @pytest.mark.parametrize("backend", _POOLED_BACKENDS)
    def test_auto_resolves_to_inline_inside_workers(self, backend: str) -> None:
        results = Experiment(
            nested_auto_offload_factory, [3], master_seed=_MASTER
        ).run(replications=2, backend=backend, max_workers=2)  # type: ignore[arg-type]
        for result in results.values():
            kind, _value = result.value
            assert kind == "inline"

    def test_auto_resolves_to_inline_in_simulated_worker_context(self) -> None:
        token = _worker_backend.set("threads")
        try:
            pool = OffloadPool(Sim())
        finally:
            _worker_backend.reset(token)
        assert pool.kind == "inline"

    @pytest.mark.parametrize("backend", ("threads", "processes"))
    def test_explicit_threads_opt_in_works_inside_workers(
        self, backend: str
    ) -> None:
        results = Experiment(
            nested_threads_offload_factory, [4], master_seed=_MASTER
        ).run(replications=1, backend=backend, max_workers=2)  # type: ignore[arg-type]
        assert [r.value for r in results.values()] == [16.0]

    def test_explicit_processes_opt_in_works_inside_process_workers(self) -> None:
        results = Experiment(
            nested_processes_offload_factory, [4], master_seed=_MASTER
        ).run(replications=1, backend="processes", max_workers=1)
        assert [r.value for r in results.values()] == [16.0]

    def test_processes_offload_rejected_inside_interpreter_workers(self) -> None:
        with pytest.raises(ReplicationError, match="subinterpreter"):
            Experiment(
                nested_processes_offload_factory, [4], master_seed=_MASTER
            ).run(replications=1, backend="interpreters", max_workers=1)

    def test_same_seed_same_results_with_nested_offloads(self) -> None:
        """Offloads inside Experiment replications keep the Phase 2 guarantee."""
        runs = [
            Experiment(nested_auto_offload_factory, [3, 5], master_seed=_MASTER).run(
                replications=3, backend=backend, max_workers=workers
            )  # type: ignore[arg-type]
            for backend, workers in (
                ("threads", 1),
                ("threads", 4),
                ("processes", 2),
                ("interpreters", 2),
            )
        ]
        first = runs[0]
        for other in runs[1:]:
            assert other == first
