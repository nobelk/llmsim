"""Fleet-sizing Monte Carlo study for the ride-hailing example (roadmap 5.2a).

Sweeps a grid of (fleet size x demand) scenarios with ``Experiment``, runs
independent replications, and reports a confidence interval per KPI per cell.
This is the Phase 2 showcase: many independent ``Sim``s, one per worker,
bit-identical on any backend or worker count for a fixed master seed.

Confidence intervals use a large-sample normal approximation via
``statistics.NormalDist`` -- pure stdlib, no numpy (``specs/tech-stack.md`` §3).
Run it directly to print a small committed-parameter study:

    python -m examples.ride_hailing.study_fleet_sizing
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from examples.confidence import ConfidenceInterval, confidence_interval
from examples.ride_hailing.kpis import RideHailingConfig, RideHailingKPIs
from examples.ride_hailing.model import run_ride_hailing
from llmsim import run_replications
from llmsim.parallel.backends import BackendName

#: Small, committed study parameters so the printed curve is reproducible.
DEFAULT_FLEET_SIZES = (6, 8, 12)
DEFAULT_DEMAND_RATES = (0.8, 1.2)
DEFAULT_MASTER_SEED = 20260712
DEFAULT_REPLICATIONS = 12


@dataclass(frozen=True, slots=True)
class FleetSizingCell:
    """The confidence intervals for one (fleet size x demand) scenario."""

    #: Fleet size for this cell.
    fleet_size: int
    #: Demand (request arrival rate) for this cell.
    request_rate: float
    #: Number of replications averaged.
    replications: int
    #: Rider wait-time interval.
    mean_wait: ConfidenceInterval
    #: Vehicle-utilization interval.
    utilization: ConfidenceInterval
    #: Abandonment-rate interval.
    abandonment: ConfidenceInterval


def build_configs(
    fleet_sizes: Sequence[int], demand_rates: Sequence[float]
) -> list[RideHailingConfig]:
    """Return the (fleet size x demand) grid of scenario configs."""
    return [
        RideHailingConfig(fleet_size=fleet_size, request_rate=rate)
        for fleet_size in fleet_sizes
        for rate in demand_rates
    ]


def _cell(
    config: RideHailingConfig,
    payloads: Sequence[RideHailingKPIs],
) -> FleetSizingCell:
    """Fold one config's replication KPIs into a :class:`FleetSizingCell`."""
    return FleetSizingCell(
        fleet_size=config.fleet_size,
        request_rate=config.request_rate,
        replications=len(payloads),
        mean_wait=confidence_interval([kpi.mean_wait for kpi in payloads]),
        utilization=confidence_interval([kpi.mean_utilization for kpi in payloads]),
        abandonment=confidence_interval([kpi.abandonment_rate for kpi in payloads]),
    )


def run_fleet_sizing_study(
    *,
    fleet_sizes: Sequence[int] = DEFAULT_FLEET_SIZES,
    demand_rates: Sequence[float] = DEFAULT_DEMAND_RATES,
    master_seed: int = DEFAULT_MASTER_SEED,
    replications: int = DEFAULT_REPLICATIONS,
    backend: BackendName = "auto",
    max_workers: int | None = None,
) -> list[FleetSizingCell]:
    """Run the fleet-sizing study and return one cell per scenario, in order.

    Args:
        fleet_sizes: Fleet sizes to sweep.
        demand_rates: Request arrival rates to sweep.
        master_seed: Master seed; fixes every replication's stream.
        replications: Replications per scenario.
        backend: Execution backend (``"auto"`` picks threads or processes).
        max_workers: Worker cap (``None`` uses the CPU count).

    Returns:
        One :class:`FleetSizingCell` per config, ordered as :func:`build_configs`.
    """
    configs = build_configs(fleet_sizes, demand_rates)
    results = run_replications(
        run_ride_hailing,
        configs,
        master_seed=master_seed,
        replications=replications,
        backend=backend,
        max_workers=max_workers,
    )
    grouped: list[list[RideHailingKPIs]] = [[] for _ in configs]
    for (config_index, _replication_index), result in sorted(results.items()):
        grouped[config_index].append(result.value)
    return [_cell(config, grouped[index]) for index, config in enumerate(configs)]


def main() -> int:
    """Print the committed-parameter fleet-sizing study."""
    cells = run_fleet_sizing_study()
    header = f"{'fleet':>6} {'demand':>7} {'wait (95% CI)':>26} {'util':>18}"
    print(header)
    for cell in cells:
        wait = f"{cell.mean_wait.mean:.3f} +/- {cell.mean_wait.half_width:.3f}"
        util = f"{cell.utilization.mean:.3f} +/- {cell.utilization.half_width:.3f}"
        print(f"{cell.fleet_size:>6} {cell.request_rate:>7.2f} {wait:>26} {util:>18}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
