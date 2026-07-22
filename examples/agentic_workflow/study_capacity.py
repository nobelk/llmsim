"""Capacity-planning sweep for the agentic-workflow example (roadmap 5.4a).

Sweeps a grid of (server count x batch size x agent concurrency) scenarios with
``Experiment``, runs independent replications, and reports a confidence interval
per KPI per cell. The Phase 2 showcase applied to LLM-serving capacity planning:
bit-identical on any backend or worker count for a fixed master seed.

Run it directly to print a small committed-parameter study:

    python -m examples.agentic_workflow.study_capacity
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from examples.agentic_workflow.kpis import AgenticConfig, AgenticKPIs
from examples.agentic_workflow.model import run_agentic_workflow
from examples.confidence import ConfidenceInterval, confidence_interval
from llmsim import run_replications
from llmsim.parallel.backends import BackendName

#: Small, committed study parameters so the printed curve is reproducible.
DEFAULT_SERVER_COUNTS = (1, 2, 4)
DEFAULT_BATCH_SIZES = (2, 8)
DEFAULT_AGENT_CONCURRENCY = (4, 12)
DEFAULT_MASTER_SEED = 20260712
DEFAULT_REPLICATIONS = 12


@dataclass(frozen=True, slots=True)
class CapacityCell:
    """The confidence intervals for one capacity scenario."""

    #: Number of inference servers.
    num_servers: int
    #: Inference batch size.
    batch_size: int
    #: Agent concurrency cap.
    agent_concurrency: int
    #: Number of replications averaged.
    replications: int
    #: End-to-end task-latency interval.
    latency: ConfidenceInterval
    #: Inference-queue-depth interval.
    queue_depth: ConfidenceInterval
    #: Cost-per-task interval.
    cost: ConfidenceInterval


def build_configs(
    server_counts: Sequence[int],
    batch_sizes: Sequence[int],
    agent_concurrency: Sequence[int],
) -> list[AgenticConfig]:
    """Return the (servers x batch x concurrency) grid of scenario configs."""
    return [
        AgenticConfig(
            num_servers=servers,
            batch_size=batch,
            agent_concurrency=concurrency,
        )
        for servers in server_counts
        for batch in batch_sizes
        for concurrency in agent_concurrency
    ]


def _cell(config: AgenticConfig, payloads: Sequence[AgenticKPIs]) -> CapacityCell:
    """Fold one config's replication KPIs into a :class:`CapacityCell`."""
    return CapacityCell(
        num_servers=config.num_servers,
        batch_size=config.batch_size,
        agent_concurrency=config.agent_concurrency,
        replications=len(payloads),
        latency=confidence_interval([kpi.mean_latency for kpi in payloads]),
        queue_depth=confidence_interval([kpi.mean_queue_depth for kpi in payloads]),
        cost=confidence_interval([kpi.mean_cost for kpi in payloads]),
    )


def run_capacity_study(
    *,
    server_counts: Sequence[int] = DEFAULT_SERVER_COUNTS,
    batch_sizes: Sequence[int] = DEFAULT_BATCH_SIZES,
    agent_concurrency: Sequence[int] = DEFAULT_AGENT_CONCURRENCY,
    master_seed: int = DEFAULT_MASTER_SEED,
    replications: int = DEFAULT_REPLICATIONS,
    backend: BackendName = "auto",
    max_workers: int | None = None,
) -> list[CapacityCell]:
    """Run the capacity sweep and return one cell per scenario, in order.

    Args:
        server_counts: Inference-server counts to sweep.
        batch_sizes: Inference batch sizes to sweep.
        agent_concurrency: Agent-concurrency caps to sweep.
        master_seed: Master seed; fixes every replication's stream.
        replications: Replications per scenario.
        backend: Execution backend (``"auto"`` picks threads or processes).
        max_workers: Worker cap (``None`` uses the CPU count).

    Returns:
        One :class:`CapacityCell` per config, ordered as :func:`build_configs`.
    """
    configs = build_configs(server_counts, batch_sizes, agent_concurrency)
    results = run_replications(
        run_agentic_workflow,
        configs,
        master_seed=master_seed,
        replications=replications,
        backend=backend,
        max_workers=max_workers,
    )
    grouped: list[list[AgenticKPIs]] = [[] for _ in configs]
    for (config_index, _replication_index), result in sorted(results.items()):
        grouped[config_index].append(result.value)
    return [_cell(config, grouped[index]) for index, config in enumerate(configs)]


def _to_row(cell: CapacityCell) -> str:
    """Format one cell as a fixed-width table row."""
    latency = f"{cell.latency.mean:.2f} +/- {cell.latency.half_width:.2f}"
    return (
        f"{cell.num_servers:>7} {cell.batch_size:>6} "
        f"{cell.agent_concurrency:>6} {latency:>24}"
    )


def main() -> int:
    """Print the committed-parameter capacity sweep."""
    cells = run_capacity_study()
    print(f"{'servers':>7} {'batch':>6} {'conc':>6} {'latency (95% CI)':>24}")
    for cell in cells:
        print(_to_row(cell))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
