"""Concurrency soak: jittered barriers must not change any result (3.5).

The CI soak job runs this module repeatedly on 3.14t (``PYTHON_GIL=0``) with
``LLMSIM_DEBUG=1`` and pytest-repeat (see ``.github/workflows/ci.yml``); the
wall-clock budget is the repeat count there. A single pass runs in the normal
suite too, so the jitter path never rots between soaks.

Jitter injects wall-clock randomness into *scheduling* (sleeps around window
edges) precisely to assert that wall clock never leaks into *results*: every
jittered run must be bitwise-identical to the un-jittered sequential
reference.
"""

import random
import time

from llmsim.parallel.pdes import sync
from tests.test_pdes_equivalence import assert_shard_traces_equal, make_grid_topology
from tests.test_pdes_sync import _pipeline

#: Unseeded on purpose: jitter is scheduling noise, not simulation state.
_jitter_rng = random.Random()


def _jitter() -> None:
    time.sleep(_jitter_rng.random() * 0.0005)


def test_jittered_grid_matches_sequential_reference() -> None:
    sequential_topo, sequential_kpis, sequential_tracers = make_grid_topology(4)
    sequential_topo.run(until=400.0, mode="sequential")

    jittered_topo, jittered_kpis, jittered_tracers = make_grid_topology(4)
    sync.run_threaded(jittered_topo, 400.0, jitter=_jitter)

    assert jittered_kpis == sequential_kpis
    assert_shard_traces_equal(jittered_tracers, sequential_tracers)


def test_jittered_pipeline_matches_sequential_reference() -> None:
    sequential_topo, sequential_received, _ = _pipeline(4)
    sequential_topo.run(until=60.0, mode="sequential")
    jittered_topo, jittered_received, _ = _pipeline(4)
    sync.run_threaded(jittered_topo, 60.0, jitter=_jitter)
    assert jittered_received == sequential_received
