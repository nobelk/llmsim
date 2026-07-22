"""Shared confidence-interval helper for the example studies.

Both parameter-sweep studies report a confidence interval per KPI per cell. The
interval is a large-sample normal approximation via ``statistics.NormalDist`` --
pure stdlib, no numpy (``specs/tech-stack.md`` §3) -- and a deterministic
function of its inputs, so a study built on seed-derived replications is
backend-reproducible.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

#: Decimal places interval bounds are rounded to for cross-platform stability.
_PRECISION = 9


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    """A KPI's sample mean and its symmetric confidence half-width."""

    #: Sample mean across replications.
    mean: float
    #: Half-width of the confidence interval (``0`` for a single replication).
    half_width: float

    @property
    def low(self) -> float:
        """Lower confidence bound."""
        return round(self.mean - self.half_width, _PRECISION)

    @property
    def high(self) -> float:
        """Upper confidence bound."""
        return round(self.mean + self.half_width, _PRECISION)


def confidence_interval(
    values: Sequence[float], *, confidence: float = 0.95
) -> ConfidenceInterval:
    """Return the normal-approximation confidence interval for *values*."""
    mean = statistics.mean(values)
    if len(values) < 2:
        return ConfidenceInterval(mean=round(mean, _PRECISION), half_width=0.0)
    z = statistics.NormalDist().inv_cdf(0.5 + confidence / 2)
    half_width = z * statistics.stdev(values) / len(values) ** 0.5
    return ConfidenceInterval(
        mean=round(mean, _PRECISION), half_width=round(half_width, _PRECISION)
    )
