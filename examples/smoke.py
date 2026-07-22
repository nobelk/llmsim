"""Small-parameter smoke run of every example and showcase (roadmap 5.5).

Executes each example end to end as a *program* -- both core models, both
studies, the zone-sharded PDES variant, and the strict-mode offload showcase --
with tiny parameters so a per-PR CI job can run it in seconds on both the 3.14
and 3.14t builds. It asserts each piece completes and prints a one-line summary;
a non-zero exit means an example failed to run.

    python -m examples.smoke
"""

from __future__ import annotations

from examples.agentic_workflow.kpis import AgenticConfig
from examples.agentic_workflow.model import run_agentic_workflow, run_sequential
from examples.agentic_workflow.offload import run_offload_showcase
from examples.agentic_workflow.study_capacity import run_capacity_study
from examples.ride_hailing.kpis import RideHailingConfig
from examples.ride_hailing.model import run_ride_hailing
from examples.ride_hailing.sharded import run_sharded
from examples.ride_hailing.study_fleet_sizing import run_fleet_sizing_study
from llmsim.rand.streams import SeedTree

_SEED = 20260712


def _smoke_ride_hailing() -> str:
    """Run the ride-hailing core, study, and sharded variant with tiny params."""
    config = RideHailingConfig(duration=40.0)
    tree = SeedTree(_SEED)
    kpis = run_ride_hailing(tree.stream(0, 0), config)
    assert kpis.served + kpis.abandoned >= 0

    study = run_fleet_sizing_study(
        fleet_sizes=(6, 12), demand_rates=(1.0,), replications=2, backend="threads"
    )
    assert len(study) == 2

    sharded_config = RideHailingConfig(num_zones=8, fleet_size=12, duration=40.0)
    sequential = run_sharded(sharded_config, shards=2, seed=_SEED, mode="sequential")
    threaded = run_sharded(sharded_config, shards=2, seed=_SEED, mode="threads")
    assert sequential == threaded
    return (
        f"ride_hailing: served={kpis.served} sharded_migrations={threaded.migrations}"
    )


def _smoke_agentic() -> str:
    """Run the agentic core, capacity sweep, and offload showcase with tiny params."""
    config = AgenticConfig(duration=40.0, max_tokens=64)
    tree = SeedTree(_SEED)
    kpis = run_agentic_workflow(tree.stream(0, 0), config)
    assert kpis.completed + kpis.failed >= 0

    study = run_capacity_study(
        server_counts=(1, 2),
        batch_sizes=(4,),
        agent_concurrency=(6,),
        replications=2,
        backend="threads",
    )
    assert len(study) == 2

    inline = run_offload_showcase(_SEED, config, backend="inline")
    reference = run_sequential(_SEED, config)
    assert inline.makespan == reference.makespan
    return f"agentic: completed={kpis.completed} offload_cost={inline.mean_cost}"


def main() -> int:
    """Run every example smoke check, printing a line each."""
    for line in (_smoke_ride_hailing(), _smoke_agentic()):
        print(line)
    print("all examples ran to completion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
