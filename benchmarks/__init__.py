"""Benchmark harness: SimPy 3 parity models, scaling gates, recorded baselines."""

import os
import sys


def skip_if_shared_macos_ci() -> None:
    """Skip a timing assertion on shared macOS CI runners.

    Phase 2 measured ~20% spread on best-of-N timings there (the same commit
    swung 0.79-0.89x on code benching at parity locally and on ubuntu), so a
    per-run timing ratio carries no signal on that runner class. Correctness
    assertions still run everywhere; timing is enforced on Linux CI and local
    machines. One home for the policy so every timing gate applies it
    identically.
    """
    if sys.platform == "darwin" and os.environ.get("CI"):
        # Imported lazily so `python -m benchmarks.pdes_scaling` (the
        # documented curve-recording path) works without test dependencies.
        import pytest

        pytest.skip("timing ratio not measurable on shared macOS runners")
