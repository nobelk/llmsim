# Real-time mode

Real-time mode paces a simulation against the **wall clock** instead of running
as fast as possible. It is the tool for hardware-in-the-loop and human-in-the-
loop scenarios, or any demo where simulated time should track real time.

## rt.run

[`rt.run`][llmsim.rt.run] is a drop-in replacement for `sim.run` that
synchronizes stepping on `time.monotonic()`:

```python
from llmsim import rt

sim = llmsim.Sim(seed=0)
# ...build the model...
rt.run(sim, until=100.0, factor=0.1)   # 1 sim unit = 0.1 real seconds
```

- **`factor`** scales simulated time to real time: `factor=1.0` means one
  simulated unit per real second; `factor=0.1` runs ten simulated units per real
  second.
- **`strict`** (default `True`) — if the run cannot keep up (an event falls more
  than one `factor` unit of wall time behind schedule), it raises
  [`RealtimeDriftError`][llmsim.rt.RealtimeDriftError]. With `strict=False`,
  bursts are allowed to hurry to catch up.

Pacing overhead itself is negligible (~0.1 µs per event); drift comes from event
density above the platform's sleep granularity, overlong offload payloads, or
interpreter pauses. The measured overhead and drift regimes are in the
[Performance overview](../perf-notes.md#real-time-mode-42-pacing-overhead-and-drift-regimes).

## Determinism is preserved

Real-time mode changes *when* events are dispatched in wall-clock terms, never
*which* events fire or in what order. The simulated event sequence — and its
trace — is identical to a plain `sim.run`; only the pacing differs. Combined
with strict [compute offload](offload.md), a paced run can drive real hardware
whose responses arrive within each event's real-time budget.
