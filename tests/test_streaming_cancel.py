"""Result streaming, cancellation granularity, zstd spooling, warm pool (2.4)."""

import threading

import pytest

from llmsim.parallel.backends import BackendName
from llmsim.parallel.replicate import Experiment
from tests import parallel_support as support

_MASTER = 20260712


# --- iter_results: every result exactly once, order-insensitive. --------------


def test_iter_results_yields_every_result_exactly_once() -> None:
    experiment = Experiment(
        support.mm1_kpis, [{"customers": 30}, {"customers": 40}], master_seed=_MASTER
    )
    seen = [
        (result.config_index, result.replication_index)
        for result in experiment.iter_results(
            replications=4, backend="threads", max_workers=4
        )
    ]
    assert sorted(seen) == [(c, r) for c in range(2) for r in range(4)]
    assert len(seen) == len(set(seen))


def test_streamed_aggregation_matches_eager_run() -> None:
    experiment = Experiment(support.mm1_kpis, [{"customers": 30}], master_seed=_MASTER)
    streamed = {
        (result.config_index, result.replication_index): result
        for result in experiment.iter_results(
            replications=5, backend="threads", max_workers=4
        )
    }
    assert streamed == experiment.run(replications=5, backend="threads")


# --- Cancellation: one API, two granularities. ---------------------------------


def test_cancel_stops_further_dispatch_on_threads() -> None:
    experiment = Experiment(
        support.slow_uncooperative_factory, [{}], master_seed=_MASTER
    )
    collected = []
    for result in experiment.iter_results(
        replications=20, backend="threads", max_workers=1
    ):
        collected.append(result)
        experiment.cancel()
    assert 1 <= len(collected) < 20
    # The uncooperative factory always finishes its whole run() (replication
    # granularity): every collected result is complete and consistent.
    assert all(result.value["now"] == 100.0 for result in collected)


def test_cooperative_factory_cancelled_mid_replication_on_threads() -> None:
    experiment = Experiment(support.cooperative_factory, [{}], master_seed=_MASTER)
    timer = threading.Timer(0.02, experiment.cancel)
    timer.start()
    results = list(
        experiment.iter_results(replications=1, backend="threads", max_workers=1)
    )
    timer.cancel()
    assert len(results) == 1
    # The factory consulted the token between step() calls and stopped long
    # before draining its 10_000 scheduled events.
    assert results[0].value["cancelled"] == 1.0
    assert results[0].value["steps"] < 10_000


def test_uncooperative_factory_runs_to_completion_despite_cancel() -> None:
    experiment = Experiment(
        support.slow_uncooperative_factory, [{}], master_seed=_MASTER
    )
    timer = threading.Timer(0.02, experiment.cancel)
    timer.start()
    results = list(
        experiment.iter_results(replications=1, backend="threads", max_workers=1)
    )
    timer.cancel()
    # Mid-replication cancel is impossible without cooperation: the single
    # running replication completed in full (replication granularity).
    assert len(results) == 1
    assert results[0].value["now"] == 100.0


@pytest.mark.parametrize("kind", ["interpreters", "processes"])
def test_isolated_backends_cancel_at_replication_granularity(
    kind: BackendName,
) -> None:
    experiment = Experiment(
        support.slow_uncooperative_factory, [{}], master_seed=_MASTER
    )
    collected = []
    for result in experiment.iter_results(replications=8, backend=kind, max_workers=1):
        collected.append(result)
        experiment.cancel()
    assert 1 <= len(collected) < 8
    assert all(result.value["now"] == 100.0 for result in collected)


def test_context_manager_cancels_on_exit() -> None:
    with Experiment(
        support.slow_uncooperative_factory, [{}], master_seed=_MASTER
    ) as experiment:
        for _ in experiment.iter_results(
            replications=20, backend="threads", max_workers=1
        ):
            break  # __exit__ must cancel the 19 queued replications promptly
    assert experiment._cancelled


def test_collected_results_stay_consistent_after_cancel() -> None:
    experiment = Experiment(support.mm1_kpis, [{"customers": 30}], master_seed=_MASTER)
    reference = experiment.run(replications=6, backend="threads")
    partial = []
    for result in experiment.iter_results(
        replications=6, backend="threads", max_workers=1
    ):
        partial.append(result)
        if len(partial) == 2:
            experiment.cancel()
    for result in partial:
        key = (result.config_index, result.replication_index)
        assert result == reference[key]


def test_run_after_cancel_starts_fresh() -> None:
    experiment = Experiment(support.trivial_task, [{}], master_seed=_MASTER)
    experiment.cancel()
    results = experiment.run(replications=2, backend="threads")
    assert set(results) == {(0, 0), (0, 1)}


# --- zstd spooling: opt-in, bit-identical round-trip. ---------------------------


@pytest.mark.parametrize("kind", ["threads", "processes"])
def test_spooled_results_round_trip_bit_identically(kind: BackendName) -> None:
    plain = Experiment(support.large_payload_factory, [{}], master_seed=_MASTER).run(
        replications=3, backend=kind, max_workers=2
    )
    spooled = Experiment(
        support.large_payload_factory, [{}], master_seed=_MASTER, spool=True
    ).run(replications=3, backend=kind, max_workers=2)
    assert set(spooled) == set(plain)
    for key, result in spooled.items():
        assert result.spooled
        assert not plain[key].spooled
        assert result.value == plain[key].value  # bit-identical payloads
        assert result == plain[key]  # equality ignores representation


def test_spooled_value_is_stable_across_accesses() -> None:
    results = Experiment(
        support.large_payload_factory, [{}], master_seed=_MASTER, spool=True
    ).run(replications=1, backend="threads")
    result = results[(0, 0)]
    assert result.value == result.value


# --- Interpreter warm pool: one worker runs many replications. -----------------


def test_interpreter_warm_pool_reuses_workers() -> None:
    experiment = Experiment(support.counting_factory, [{}], master_seed=_MASTER)
    results = experiment.run(replications=5, backend="interpreters", max_workers=1)
    # A cold pool would import the module fresh per task and always return 1;
    # the warm pool keeps module state, so the single worker counts up.
    assert sorted(result.value for result in results.values()) == [1, 2, 3, 4, 5]
