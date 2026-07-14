# Tracing

The deterministic event trace. `trace(sim)` attaches a `Tracer` that records a
canonical `TraceRecord` per processed event; the resulting sequence is the
same-seed-same-result oracle used throughout the parallel test suites.
`llmsim.trace` is a public submodule of the `llmsim` package.

## Functions

::: llmsim.trace.trace

::: llmsim.trace.disable_trace

## Records

::: llmsim.trace.Tracer

::: llmsim.trace.TraceRecord
