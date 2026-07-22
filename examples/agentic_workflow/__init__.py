"""LLM agentic-workflow example (roadmap 5.3--5.4).

A multi-agent task pipeline that *models* an LLM-serving system -- shared,
batching inference servers plus think/act agents -- and never makes a real LLM
or network call. Exercises the sequential core plus both parallelism tiers: a
capacity-planning sweep via ``Experiment`` (5.4a) and a strict-mode
``sim.offload`` scoring showcase (5.4b). The public entry points are the
importable factory :func:`run_agentic_workflow` and the config/KPI dataclasses.
"""

from examples.agentic_workflow.kpis import AgenticConfig, AgenticKPIs
from examples.agentic_workflow.model import run_agentic_workflow, run_sequential

__all__ = [
    "AgenticConfig",
    "AgenticKPIs",
    "run_agentic_workflow",
    "run_sequential",
]
