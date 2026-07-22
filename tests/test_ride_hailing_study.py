"""Fleet-sizing study tests: CI math, grid shape, reproducibility (roadmap 5.2a)."""

from examples.confidence import confidence_interval
from examples.ride_hailing.study_fleet_sizing import (
    build_configs,
    run_fleet_sizing_study,
)

_MASTER = 20260712


def test_build_configs_is_the_full_grid() -> None:
    """The config grid is the Cartesian product of fleet sizes and demand."""
    configs = build_configs((6, 8, 12), (0.8, 1.2))
    assert len(configs) == 6
    assert {(config.fleet_size, config.request_rate) for config in configs} == {
        (6, 0.8),
        (6, 1.2),
        (8, 0.8),
        (8, 1.2),
        (12, 0.8),
        (12, 1.2),
    }


def test_confidence_interval_brackets_the_mean() -> None:
    """The interval is centered on the mean with a positive half-width."""
    interval = confidence_interval([1.0, 2.0, 3.0, 4.0])
    assert interval.mean == 2.5
    assert interval.half_width > 0.0
    assert interval.low < interval.mean < interval.high


def test_confidence_interval_single_value_has_zero_width() -> None:
    """A single replication yields a degenerate (zero-width) interval."""
    interval = confidence_interval([7.5])
    assert interval.mean == 7.5
    assert interval.half_width == 0.0
    assert interval.low == interval.high == 7.5


def test_study_is_backend_reproducible() -> None:
    """The study is identical across backends for a fixed master seed."""
    on_threads = run_fleet_sizing_study(replications=4, backend="threads")
    on_processes = run_fleet_sizing_study(replications=4, backend="processes")
    assert on_threads == on_processes


def test_study_reports_one_cell_per_config() -> None:
    """Each cell carries its scenario and the requested replication count."""
    cells = run_fleet_sizing_study(
        fleet_sizes=(6, 12), demand_rates=(1.0,), replications=3, backend="threads"
    )
    assert len(cells) == 2
    assert all(cell.replications == 3 for cell in cells)
    assert [cell.fleet_size for cell in cells] == [6, 12]
