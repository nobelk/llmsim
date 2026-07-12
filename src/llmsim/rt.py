"""Real-time (wall-clock) execution mode.

Optionally paces the event loop against ``time.monotonic()`` so simulated time
tracks real time, for interactive demos and hardware-in-the-loop use. Disabled
by default; never affects deterministic (as-fast-as-possible) runs.
"""
