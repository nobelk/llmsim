"""Fixtures for the ported SimPy 3 behavioral suite.

This suite is the phase acceptance gate (requirements.md 1.10). It ports SimPy
3's own behavioral tests to the llmsim clean-break API, so ``env`` becomes
``sim``, ``env.timeout`` becomes ``sim.delay``, ``env.process(fn(env, ...))``
becomes ``sim.spawn(fn, ...)`` (the ``Sim`` is injected as the first argument),
and ``env.event()`` stays ``sim.event()``. Every deliberate divergence from
SimPy 3 behavior is annotated at its test with a one-line rationale.
"""

from typing import Any

import pytest

from llmsim import Sim


@pytest.fixture
def sim() -> Sim:
    """A fresh simulation, mirroring SimPy's ``env`` fixture."""
    return Sim()


@pytest.fixture
def log() -> list[Any]:
    """A shared list processes append observations to, mirroring SimPy's ``log``."""
    return []
