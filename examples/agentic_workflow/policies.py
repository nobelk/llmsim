"""The CPU-heavy scoring/routing policy for the agentic-workflow example.

:func:`score_request` is a deliberately compute-bound *pure* function of plain
integer features. The core model does not call it; the offload showcase (roadmap
5.4b) hands it to a worker pool via ``sim.offload(..., strict=True)``. Because it
is a pure, importable, module-level callable of picklable arguments, every
offload backend transports and computes it identically -- the property the
trace-equivalence test relies on.
"""

from __future__ import annotations

#: Grind iterations per token. Enough to be measurably CPU-bound, small enough
#: for a per-PR CI smoke run.
_GRIND_PER_TOKEN = 64

#: A large odd multiplier (Knuth) for the integer mixing step.
_MIX = 2654435761


def score_request(token_length: int, task_id: int, step: int) -> float:
    """Return a routing score for one inference request (CPU-heavy, pure).

    The score is a deterministic reduction over ``token_length`` mixing steps
    seeded by the request's identity, so the same features always yield the same
    score on any backend. The work is intentional: this is the payload the
    offload showcase moves off the simulation thread.

    Args:
        token_length: The request's token count (sets the amount of work).
        task_id: The owning task's identity (folded into the seed).
        step: The think-step index within the task (folded into the seed).

    Returns:
        A score in ``[0.0, 1.0)`` rounded for cross-platform bit-stability.
    """
    state = (task_id * _MIX + step) & 0xFFFFFFFF
    iterations = max(1, token_length) * _GRIND_PER_TOKEN
    for index in range(iterations):
        state = (state * _MIX + index) & 0xFFFFFFFF
        state ^= state >> 15
    return round((state & 0xFFFFFF) / float(0x1000000), 9)
