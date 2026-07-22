#!/usr/bin/env python3
"""Render the Phase 5 example showcase curves as committed SVG artifacts.

Every data point below is a **deterministic** output of the example study and
showcase scripts (not a wall-clock timing), transcribed here so the committed
SVGs under ``docs/examples/`` are reproducible: a reviewer regenerates the
numbers by running the named study call and diffs them against these series,
then reruns ``python scripts/generate_example_charts.py``. The wall-clock
speedup/slowdown *regimes* are documented in the example docs pages and the
measured perf record (``docs/perf-notes.md``); they are not plotted here because
absolute speedup on anti-scaling interpreters is recorded-not-blocking
(``specs/roadmap.md`` Phase 3 exit). Pure stdlib -- no plotting dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 5.2a Fleet-sizing Monte Carlo: mean rider wait vs fleet size, two demand
# series. From run_fleet_sizing_study(fleet_sizes=(6,8,12,16),
# demand_rates=(0.8,1.2), replications=12).
# ---------------------------------------------------------------------------
FLEET_SIZING = {
    "demand 0.8": [(6, 4.263), (8, 1.852), (12, 0.003), (16, 0.0)],
    "demand 1.2": [(6, 5.942), (8, 4.688), (12, 1.287), (16, 0.034)],
}

# 5.2b Zone-sharded PDES: served-request throughput vs shard count, at a FIXED
# total demand (each shard serves its zone-group's share, request_rate/shards).
# From run_sharded(RideHailingConfig(num_zones=8, fleet_size=12, duration=200),
# shards=s, mode="sequential"). num_zones must divide the shard count. The shape
# is the honest PDES trade-off: partitioning the same workload fragments the
# fleet, so throughput peaks then falls as shards rise.
SHARDED_THROUGHPUT = {
    "served requests": [(1, 227), (2, 245), (4, 189), (8, 144)],
}

# 5.4a Capacity sweep: mean task latency vs server count, two concurrency
# series. From run_capacity_study(server_counts=(1,2,4), batch_sizes=(4,),
# agent_concurrency=(4,12), replications=12).
CAPACITY = {
    "concurrency 4": [(1, 86.62), (2, 82.16), (4, 74.29)],
    "concurrency 12": [(1, 73.80), (2, 51.35), (4, 36.52)],
}

# 5.4b Strict-mode offload: mean task latency vs agent concurrency for the
# offloaded-scoring model (backend-invariant; inline == threads == processes).
# From run_offload_showcase(AgenticConfig(agent_concurrency=c, num_servers=2,
# max_tokens=64, duration=120), backend="inline").
OFFLOAD = {
    "offloaded scoring": [(2, 51.28), (4, 35.43), (8, 25.57), (16, 8.05)],
}

#: Colour-blind-safe series palette (Okabe-Ito subset).
SERIES_COLORS = ["#0072b2", "#d55e00", "#009e73", "#cc79a7"]

WIDTH, HEIGHT = 680, 420
MARGIN_LEFT, MARGIN_RIGHT = 68, 160
MARGIN_TOP, MARGIN_BOTTOM = 48, 56


def _nice_max(value: float) -> float:
    """Round *value* up to a friendly axis maximum."""
    if value <= 0:
        return 1.0
    for step in (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0):
        if value <= step * 5:
            return -(-value // step) * step
    return value


def render_chart(
    series: dict[str, list[tuple[float, float]]],
    *,
    title: str,
    x_label: str,
    y_label: str,
) -> str:
    """Return an SVG line chart for *series* (a mapping name -> [(x, y), ...])."""
    xs = [x for points in series.values() for x, _ in points]
    ys = [y for points in series.values() for _, y in points]
    x_min, x_max = min(xs), max(xs)
    y_max = _nice_max(max(ys))
    y_min = 0.0

    plot_w = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    plot_h = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    def sx(x: float) -> float:
        if x_max == x_min:
            return MARGIN_LEFT + plot_w / 2
        return MARGIN_LEFT + (x - x_min) / (x_max - x_min) * plot_w

    def sy(y: float) -> float:
        return MARGIN_TOP + (1 - (y - y_min) / (y_max - y_min)) * plot_h

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'font-family="system-ui, sans-serif" role="img" aria-label="{title}">',
        f'<text x="{WIDTH / 2}" y="26" text-anchor="middle" font-size="16" '
        f'font-weight="600" fill="currentColor">{title}</text>',
        f'<rect x="{MARGIN_LEFT}" y="{MARGIN_TOP}" width="{plot_w}" '
        f'height="{plot_h}" fill="none" stroke="currentColor" stroke-opacity="0.25"/>',
    ]

    ticks = 5
    for index in range(ticks + 1):
        y_val = y_max * index / ticks
        yy = sy(y_val)
        parts.append(
            f'<line x1="{MARGIN_LEFT}" y1="{yy:.1f}" x2="{MARGIN_LEFT + plot_w}" '
            f'y2="{yy:.1f}" stroke="currentColor" stroke-opacity="0.08"/>'
        )
        parts.append(
            f'<text x="{MARGIN_LEFT - 8}" y="{yy + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="currentColor" fill-opacity="0.7">{y_val:g}</text>'
        )
    for x_val in sorted(set(xs)):
        xx = sx(x_val)
        parts.append(
            f'<text x="{xx:.1f}" y="{MARGIN_TOP + plot_h + 18}" text-anchor="middle" '
            f'font-size="11" fill="currentColor" fill-opacity="0.7">{x_val:g}</text>'
        )
    parts.append(
        f'<text x="{MARGIN_LEFT + plot_w / 2}" y="{HEIGHT - 8}" text-anchor="middle" '
        f'font-size="12" fill="currentColor" fill-opacity="0.8">{x_label}</text>'
    )
    parts.append(
        f'<text x="16" y="{MARGIN_TOP + plot_h / 2}" text-anchor="middle" '
        f'font-size="12" fill="currentColor" fill-opacity="0.8" '
        f'transform="rotate(-90 16 {MARGIN_TOP + plot_h / 2})">{y_label}</text>'
    )

    legend_y = MARGIN_TOP + 6
    for idx, (name, points) in enumerate(series.items()):
        color = SERIES_COLORS[idx % len(SERIES_COLORS)]
        ordered = sorted(points)
        path = " ".join(
            f"{'M' if i == 0 else 'L'} {sx(x):.1f} {sy(y):.1f}"
            for i, (x, y) in enumerate(ordered)
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5"/>'
        )
        for x, y in ordered:
            parts.append(
                f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.5" fill="{color}"/>'
            )
        ly = legend_y + idx * 20
        lx = MARGIN_LEFT + plot_w + 16
        parts.append(
            f'<line x1="{lx}" y1="{ly}" x2="{lx + 20}" y2="{ly}" '
            f'stroke="{color}" stroke-width="2.5"/>'
        )
        parts.append(f'<circle cx="{lx + 10}" cy="{ly}" r="3.5" fill="{color}"/>')
        parts.append(
            f'<text x="{lx + 26}" y="{ly + 4}" font-size="11" '
            f'fill="currentColor" fill-opacity="0.85">{name}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


CHARTS = [
    (
        "ride-hailing-fleet-sizing.svg",
        FLEET_SIZING,
        "Fleet-sizing study: rider wait vs fleet size",
        "fleet size",
        "mean rider wait (time units)",
    ),
    (
        "ride-hailing-sharded.svg",
        SHARDED_THROUGHPUT,
        "Zone-sharded PDES: throughput vs shard count",
        "shard count",
        "served requests",
    ),
    (
        "agentic-capacity.svg",
        CAPACITY,
        "Capacity sweep: task latency vs server count",
        "inference servers",
        "mean task latency (time units)",
    ),
    (
        "agentic-offload.svg",
        OFFLOAD,
        "Offloaded scoring: latency vs agent concurrency",
        "agent concurrency",
        "mean task latency (time units)",
    ),
]


def main() -> int:
    """Write every example chart SVG into ``docs/examples/``."""
    out_dir = Path(__file__).resolve().parent.parent / "docs" / "examples"
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename, series, title, x_label, y_label in CHARTS:
        svg = render_chart(series, title=title, x_label=x_label, y_label=y_label)
        (out_dir / filename).write_text(svg, encoding="utf-8")
        print(f"wrote {out_dir / filename}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
