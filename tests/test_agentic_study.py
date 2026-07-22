"""Capacity-sweep tests: grid shape and backend reproducibility (roadmap 5.4a)."""

from examples.agentic_workflow.study_capacity import build_configs, run_capacity_study


def test_build_configs_is_the_full_grid() -> None:
    """The config grid is the product of servers, batch sizes, and concurrency."""
    configs = build_configs((1, 2, 4), (2, 8), (4, 12))
    assert len(configs) == 12
    triples = {
        (config.num_servers, config.batch_size, config.agent_concurrency)
        for config in configs
    }
    assert (1, 2, 4) in triples
    assert (4, 8, 12) in triples
    assert len(triples) == 12


def test_study_is_backend_reproducible() -> None:
    """The capacity sweep is identical across backends for a fixed master seed."""
    on_threads = run_capacity_study(
        server_counts=(1, 2),
        batch_sizes=(4,),
        agent_concurrency=(6,),
        replications=4,
        backend="threads",
    )
    on_processes = run_capacity_study(
        server_counts=(1, 2),
        batch_sizes=(4,),
        agent_concurrency=(6,),
        replications=4,
        backend="processes",
    )
    assert on_threads == on_processes


def test_study_reports_one_cell_per_config() -> None:
    """Each cell carries its scenario and the requested replication count."""
    cells = run_capacity_study(
        server_counts=(1, 2),
        batch_sizes=(4,),
        agent_concurrency=(6,),
        replications=3,
        backend="threads",
    )
    assert len(cells) == 2
    assert all(cell.replications == 3 for cell in cells)
    assert [cell.num_servers for cell in cells] == [1, 2]
