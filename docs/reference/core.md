# Core engine

The sequential simulation core: the event loop, the generic event, the
process driver, condition composition, and the error hierarchy. Every symbol
here is re-exported from the top-level `llmsim` package.

## Simulation

::: llmsim.core.sim.Sim

## Events

::: llmsim.core.events.Event

::: llmsim.core.events.Timeout

## Processes

::: llmsim.core.process.Process

## Condition composition

::: llmsim.core.conditions.Condition

::: llmsim.core.conditions.AllOf

::: llmsim.core.conditions.AnyOf

## Errors

::: llmsim.core.errors.SimulationError

::: llmsim.core.errors.Interrupt

::: llmsim.core.errors.EmptySchedule
