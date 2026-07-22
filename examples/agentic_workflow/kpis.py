"""Configuration and KPI types for the agentic-workflow example.

Frozen, ``__slots__`` dataclasses so a config and its KPI result cross the
pickle boundary to a process/interpreter worker unchanged
(``specs/tech-stack.md`` §5). Every KPI float is rounded so same-seed and
trace-equivalence assertions are bit-stable across platforms.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Decimal places every KPI float is rounded to for cross-platform bit-stability.
KPI_PRECISION = 9


@dataclass(frozen=True, slots=True)
class AgenticConfig:
    """A single, fully-specified agentic-workflow scenario.

    Models an LLM-serving system -- never a real LLM call. Inference service
    times are token-length dependent and drawn deterministically; tool calls
    have stochastic latency, failures, and bounded retries.
    """

    #: Poisson task-arrival rate (tasks per unit time).
    arrival_rate: float = 1.5
    #: Number of shared, batching LLM-inference servers.
    num_servers: int = 2
    #: Maximum inference requests served together in one batch.
    batch_size: int = 4
    #: Maximum number of agents running concurrently (a bounded worker pool).
    agent_concurrency: int = 6
    #: Number of think/act step pairs each task performs.
    steps_per_task: int = 3
    #: Minimum inference request token length.
    min_tokens: int = 16
    #: Maximum inference request token length.
    max_tokens: int = 256
    #: Fixed inference service time per batch, before the token term.
    inference_base: float = 0.5
    #: Inference service time added per token of the batch's longest request.
    inference_per_token: float = 0.01
    #: Cost charged per inference token.
    token_cost: float = 0.002
    #: Mean latency of a tool (act) call.
    tool_latency_mean: float = 1.0
    #: Probability a tool call fails and must be retried.
    tool_failure_prob: float = 0.15
    #: Maximum tool-call retries before the task surfaces a failure.
    max_retries: int = 2
    #: Cost charged per tool-call attempt.
    tool_cost: float = 0.05
    #: Simulated time horizon.
    duration: float = 200.0


@dataclass(frozen=True, slots=True)
class AgenticKPIs:
    """Headline outcomes of one agentic-workflow run.

    A deterministic function of ``(seed, config)``: identical on any backend,
    worker count, or build.
    """

    #: Mean end-to-end task latency (arrival to completion or surfaced failure).
    mean_latency: float
    #: Number of tasks that completed all their steps.
    completed: int
    #: Number of tasks that surfaced a failure after exhausting retries.
    failed: int
    #: Fraction of tasks that failed.
    failure_rate: float
    #: Mean inference-queue depth seen at each enqueue.
    mean_queue_depth: float
    #: Largest inference-queue depth observed.
    peak_queue_depth: int
    #: Mean cost per task (inference tokens + tool attempts).
    mean_cost: float
    #: Mean number of requests served per inference batch.
    mean_batch_size: float
    #: Simulated time of the last event.
    makespan: float


class AgenticAccumulator:
    """Mutable per-run tally that :meth:`finalize` folds into a result."""

    __slots__ = (
        "latencies",
        "costs",
        "failed",
        "queue_samples",
        "peak_queue",
        "batch_sizes",
    )

    def __init__(self) -> None:
        """Start an empty tally."""
        #: End-to-end latency of every finished task (completed or failed).
        self.latencies: list[float] = []
        #: Cost of every finished task.
        self.costs: list[float] = []
        #: Count of tasks that surfaced a failure.
        self.failed = 0
        #: Inference-queue depth sampled at each enqueue.
        self.queue_samples: list[int] = []
        #: Largest inference-queue depth observed.
        self.peak_queue = 0
        #: Size of every inference batch served.
        self.batch_sizes: list[int] = []

    def record_task(self, latency: float, cost: float, *, failed: bool) -> None:
        """Record a finished task's latency, cost, and failure outcome."""
        self.latencies.append(latency)
        self.costs.append(cost)
        if failed:
            self.failed += 1

    def record_enqueue(self, depth: int) -> None:
        """Record the inference-queue depth observed at an enqueue."""
        self.queue_samples.append(depth)
        self.peak_queue = max(self.peak_queue, depth)

    def record_batch(self, size: int) -> None:
        """Record the size of one served inference batch."""
        self.batch_sizes.append(size)

    def finalize(self, *, makespan: float) -> AgenticKPIs:
        """Fold the tally into a rounded, immutable :class:`AgenticKPIs`."""
        finished = len(self.latencies)
        mean_latency = sum(self.latencies) / finished if finished else 0.0
        failure_rate = self.failed / finished if finished else 0.0
        mean_cost = sum(self.costs) / finished if finished else 0.0
        mean_queue = (
            sum(self.queue_samples) / len(self.queue_samples)
            if self.queue_samples
            else 0.0
        )
        mean_batch = (
            sum(self.batch_sizes) / len(self.batch_sizes) if self.batch_sizes else 0.0
        )
        return AgenticKPIs(
            mean_latency=round(mean_latency, KPI_PRECISION),
            completed=finished - self.failed,
            failed=self.failed,
            failure_rate=round(failure_rate, KPI_PRECISION),
            mean_queue_depth=round(mean_queue, KPI_PRECISION),
            peak_queue_depth=self.peak_queue,
            mean_cost=round(mean_cost, KPI_PRECISION),
            mean_batch_size=round(mean_batch, KPI_PRECISION),
            makespan=round(makespan, KPI_PRECISION),
        )
