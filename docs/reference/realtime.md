# Real-time mode

Wall-clock-synchronized stepping. `llmsim.rt.run` paces a simulation against
`time.monotonic()` so simulated time tracks real time by a chosen factor; in
strict mode it raises `RealtimeDriftError` when the run cannot keep up. `rt` is
re-exported as a submodule of the top-level `llmsim` package; `RealtimeDriftError`
is also re-exported at the top level.

::: llmsim.rt.run

::: llmsim.rt.RealtimeDriftError
