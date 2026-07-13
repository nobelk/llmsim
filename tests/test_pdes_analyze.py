"""pdes.analyze(): window-model speedup estimation from traces (3.6)."""

import pytest

from llmsim.parallel.pdes.analyze import PdesAnalysis, analyze
from llmsim.trace import TraceRecord


def _records(times: list[float]) -> list[TraceRecord]:
    return [
        TraceRecord(time=t, eid=i, kind="Timeout", priority=1, payload=None)
        for i, t in enumerate(times)
    ]


def _uniform(start: float, stop: float, count: int) -> list[float]:
    step = (stop - start) / count
    return [start + step * i for i in range(count)]


def test_chain_topology_predicts_no_speedup() -> None:
    """Work strictly alternates between shards window by window: ~1x."""
    traces = {
        0: _records(_uniform(0.0, 10.0, 100)),
        1: _records(_uniform(10.0, 20.0, 100)),
    }
    analysis = analyze(traces, lookahead=10.0)
    assert analysis.per_shard_events == {0: 100, 1: 100}
    assert analysis.predicted_speedup == pytest.approx(1.0)


def test_independent_balanced_shards_predict_full_speedup() -> None:
    """Both shards busy in every window: ~Nx."""
    times = _uniform(0.0, 20.0, 200)
    traces = {0: _records(times), 1: _records(times), 2: _records(times)}
    analysis = analyze(traces, lookahead=5.0)
    assert analysis.predicted_speedup == pytest.approx(3.0)
    assert analysis.balance_speedup == pytest.approx(3.0)


def test_unbalanced_split_predicts_balance_bound() -> None:
    """A 90/10 split caps speedup near 1/0.9."""
    traces = {
        0: _records(_uniform(0.0, 10.0, 900)),
        1: _records(_uniform(0.0, 10.0, 100)),
    }
    analysis = analyze(traces, lookahead=1.0)
    assert analysis.predicted_speedup == pytest.approx(1000 / 900)
    assert analysis.balance_speedup == pytest.approx(1000 / 900)


def test_estimate_is_invariant_under_global_time_shift() -> None:
    """PDES behavior does not depend on the trace origin; nor may the estimate."""
    base = {0: _records([0.1]), 1: _records([0.9])}
    shifted = {0: _records([0.3]), 1: _records([1.1])}
    assert (
        analyze(base, lookahead=1.0).predicted_speedup
        == analyze(shifted, lookahead=1.0).predicted_speedup
    )


def test_window_count_reflects_makespan_over_lookahead() -> None:
    traces = {0: _records(_uniform(0.0, 100.0, 10))}
    analysis = analyze(traces, lookahead=10.0)
    assert analysis.window_count == 10


def test_empty_shard_contributes_zero_work() -> None:
    traces = {0: _records([1.0, 2.0]), 1: []}
    analysis = analyze(traces, lookahead=1.0)
    assert analysis.per_shard_events == {0: 2, 1: 0}
    assert analysis.predicted_speedup == pytest.approx(1.0)


def test_validation_errors() -> None:
    with pytest.raises(ValueError, match="lookahead"):
        analyze({0: _records([1.0])}, lookahead=0.0)
    with pytest.raises(ValueError, match="traces"):
        analyze({}, lookahead=1.0)


def test_report_is_a_plain_readable_value() -> None:
    analysis = analyze({0: _records([1.0]), 1: _records([1.5])}, lookahead=1.0)
    assert isinstance(analysis, PdesAnalysis)
    assert "predicted_speedup" in repr(analysis)
