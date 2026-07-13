"""Record the replication-throughput-vs-worker-count curve on this build.

Run directly (``uv run python benchmarks/replication_scaling.py``) to print
the measured curve for the current interpreter; run under both 3.14 and 3.14t
to produce the two curves published in ``docs/perf-notes.md``. The enforcing
CI gate lives in ``benchmarks/test_replication_scaling.py``; this module owns
the shared measurement helpers.
"""

import sys
import time

from benchmarks.replication_model import CONFIG, MASTER_SEED, mm1_replication
from llmsim.parallel.backends import ExecutionBackend
from llmsim.parallel.replicate import Experiment
from llmsim.rand.streams import SeedTree

#: Replications per measurement; sized with the model so the sequential
#: baseline runs a few seconds -- enough to amortize pool startup at the
#: worker counts CI exercises.
REPLICATIONS = 64


def sequential_seconds(replications: int = REPLICATIONS) -> float:
    """Time the pure sequential baseline: one in-process loop, no executor."""
    tree = SeedTree(MASTER_SEED)
    start = time.perf_counter()
    for replication_index in range(replications):
        mm1_replication(tree.stream(0, replication_index), CONFIG)
    return time.perf_counter() - start


def parallel_seconds(
    max_workers: int, replications: int = REPLICATIONS, backend: str = "auto"
) -> float:
    """Time the full study through Experiment.run on *backend*.

    Includes executor startup and result transport -- the number a user
    actually experiences, not a best-case inner-loop figure.
    """
    experiment = Experiment(mm1_replication, [CONFIG], master_seed=MASTER_SEED)
    start = time.perf_counter()
    experiment.run(replications, backend=backend, max_workers=max_workers)  # type: ignore[arg-type]
    return time.perf_counter() - start


def main() -> None:
    """Print the scaling curve: ``... replication_scaling [backend] [workers...]``."""
    import os

    backend = sys.argv[1] if len(sys.argv) > 1 else "auto"
    worker_counts = [int(arg) for arg in sys.argv[2:]] or [1, 2, 4, 8]
    resolved = ExecutionBackend.resolve(backend).kind
    gil = sys._is_gil_enabled()
    cores = os.process_cpu_count() or 1
    print(f"build={sys.version.split()[0]} gil={gil} backend={resolved} cores={cores}")
    baseline = sequential_seconds()
    print(f"sequential: {baseline:.3f}s ({REPLICATIONS} replications)")
    for workers in worker_counts:
        if workers > cores:
            break
        elapsed = parallel_seconds(workers, backend=backend)
        speedup = baseline / elapsed
        print(
            f"workers={workers}: {elapsed:.3f}s speedup={speedup:.2f}x "
            f"efficiency={speedup / workers:.2f}"
        )


if __name__ == "__main__":
    main()
