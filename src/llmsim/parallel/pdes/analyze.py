"""Speedup estimation before you shard: the window-model critical path.

``analyze()`` reads per-shard traces of a partitioned model (recorded by the
Phase 1 tracer against the Group 2 sequential reference runner, or any plain
``Sim`` run whose events you have assigned to a proposed partition) and
predicts the speedup the safe-window synchronizer could deliver — so a user
can see whether partitioning is worth the modeling effort *before* investing
in it (mission principle 3: honest performance claims).

The model, and its stated assumptions: simulated time is cut into windows of
width *lookahead*; within a window shards run in parallel, so the window's
parallel cost is the busiest shard's event count and the whole run's parallel
cost is the sum of per-window maxima. ``predicted_speedup`` is total events
over that cost. Assumptions: uniform event cost, zero barrier/synchronization
overhead, and a fixed window width equal to the minimum lookahead. Every one
of those flatters the parallel run, so treat the result as an upper-bound
*estimate* — a model predicted at ~1x will not go faster by sharding; a model
predicted at ~Nx may approach it with balanced shards and cheap barriers.
"""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import floor

from llmsim.trace import TraceRecord


@dataclass(frozen=True, slots=True)
class PdesAnalysis:
    """The window-model estimate for one proposed partition."""

    #: Events each shard executed in the analyzed trace.
    per_shard_events: dict[int, int]
    #: Speedup ceiling from load balance alone: total / busiest shard.
    balance_speedup: float
    #: Number of lookahead-width windows spanning the trace.
    window_count: int
    #: The window-model estimate: total events / sum of per-window maxima.
    #: Bounded above by ``balance_speedup`` and by the shard count.
    predicted_speedup: float


def analyze(
    traces: Mapping[int, Sequence[TraceRecord]], *, lookahead: float
) -> PdesAnalysis:
    """Estimate achievable PDES speedup for a partition from its traces.

    Args:
        traces: Per-shard trace records (shard index -> records), e.g. from
            running the topology through the sequential reference runner with
            a tracer attached per shard.
        lookahead: The window width — use the minimum lookahead the topology's
            channels would declare.

    Raises:
        ValueError: if *traces* is empty or *lookahead* is not positive.
    """
    if lookahead <= 0:
        raise ValueError(f"lookahead must be > 0, got {lookahead}")
    if not traces:
        raise ValueError("traces must contain at least one shard")

    per_shard_events = {
        shard_index: len(records) for shard_index, records in traces.items()
    }
    total_events = sum(per_shard_events.values())
    if total_events == 0:
        return PdesAnalysis(
            per_shard_events=per_shard_events,
            balance_speedup=1.0,
            window_count=0,
            predicted_speedup=1.0,
        )

    # Bucket each shard's events into lookahead-width windows anchored at the
    # earliest traced event: conservative-PDES behavior is invariant under a
    # global time offset, so the estimate must not depend on the trace origin.
    origin = min(record.time for records in traces.values() for record in records)
    window_load: defaultdict[int, Counter[int]] = defaultdict(Counter)
    for shard_index, records in traces.items():
        for record in records:
            window_load[floor((record.time - origin) / lookahead)][shard_index] += 1

    parallel_cost = sum(max(loads.values()) for loads in window_load.values())
    busiest_shard = max(per_shard_events.values())
    return PdesAnalysis(
        per_shard_events=per_shard_events,
        balance_speedup=total_events / busiest_shard,
        window_count=len(window_load),
        predicted_speedup=total_events / parallel_cost,
    )
