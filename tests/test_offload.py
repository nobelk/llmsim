"""Compute offload: slot semantics, payload validation, inline mode (4.1)."""

from collections.abc import Generator
from typing import Any

import pytest

from llmsim import (
    Event,
    NonStrictOffloadWarning,
    OffloadEvent,
    OffloadPool,
    Process,
    Sim,
    SimulationError,
    Timeout,
)
from llmsim.core.errors import Interrupt
from llmsim.parallel.backends import FactoryValidationError
from llmsim.trace import trace
from tests.parallel_support import (
    offload_add,
    offload_fail,
    offload_square,
)

#: The process-body shape every inline test model uses.
Gen = Generator[Event[Any], Any, None]


def make_inline_sim() -> tuple[Sim, OffloadPool]:
    """Return a fresh ``Sim`` with an inline offload pool attached."""
    sim = Sim()
    pool = OffloadPool(sim, backend="inline")
    return sim, pool


class TestStrictSlot:
    """The deterministic completion slot: results land at ``now + delay``."""

    def test_result_delivered_exactly_at_slot(self) -> None:
        sim, _pool = make_inline_sim()
        seen: list[tuple[float, float]] = []

        def waiter(sim: Sim) -> Gen:
            value = yield sim.offload(offload_square, 3.0, delay=5.0)
            seen.append((sim.now, value))

        sim.spawn(waiter)
        sim.run()
        assert seen == [(5.0, 9.0)]

    def test_slot_is_relative_to_submission_time(self) -> None:
        sim, _pool = make_inline_sim()
        seen: list[float] = []

        def waiter(sim: Sim) -> Gen:
            yield sim.delay(2.0)
            yield sim.offload(offload_square, 2.0, delay=3.0)
            seen.append(sim.now)

        sim.spawn(waiter)
        sim.run()
        assert seen == [5.0]

    def test_keyword_payload_arguments_pass_through(self) -> None:
        sim, _pool = make_inline_sim()
        seen: list[float] = []

        def waiter(sim: Sim) -> Gen:
            value = yield sim.offload(offload_add, 2.0, delay=1.0, increment=40.0)
            seen.append(value)

        sim.spawn(waiter)
        sim.run()
        assert seen == [42.0]

    def test_same_time_ties_break_by_submission_order(self) -> None:
        """An offload slot and a Timeout at the same time keep insertion order."""
        sim, _pool = make_inline_sim()
        tracer = trace(sim)

        def model(sim: Sim) -> Gen:
            offload_event = sim.offload(offload_square, 2.0, delay=5.0)
            timeout = sim.delay(5.0)
            yield offload_event & timeout

        sim.spawn(model)
        sim.run()
        same_time = [r.kind for r in tracer.records if r.time == 5.0]
        # The offload was submitted (and scheduled) before the timeout, so it
        # processes first at the shared (time, priority).
        assert same_time.index("OffloadEvent") < same_time.index("Timeout")

    def test_offload_event_appears_in_trace_with_result_payload(self) -> None:
        sim, _pool = make_inline_sim()
        tracer = trace(sim)

        def waiter(sim: Sim) -> Gen:
            yield sim.offload(offload_square, 4.0, delay=2.5)

        sim.spawn(waiter)
        sim.run()
        offload_records = [r for r in tracer.records if r.kind == "OffloadEvent"]
        assert [(r.time, r.payload) for r in offload_records] == [(2.5, 16.0)]


class TestArgumentValidation:
    """Misuse is rejected at the ``sim.offload`` call, not at the slot."""

    def test_strict_requires_delay(self) -> None:
        sim, _pool = make_inline_sim()
        with pytest.raises(ValueError, match="strict.*delay"):
            sim.offload(offload_square, 2.0)

    def test_negative_delay_rejected(self) -> None:
        sim, _pool = make_inline_sim()
        with pytest.raises(ValueError, match="negative"):
            sim.offload(offload_square, 2.0, delay=-1.0)

    def test_negative_delay_rejected_non_strict_too(self) -> None:
        sim, _pool = make_inline_sim()
        with pytest.raises(ValueError, match="negative"):
            sim.offload(offload_square, 2.0, delay=-1.0, strict=False)

    def test_lambda_payload_rejected(self) -> None:
        sim, _pool = make_inline_sim()
        with pytest.raises(FactoryValidationError, match="lambda"):
            sim.offload(lambda: 1.0, delay=1.0)

    def test_closure_payload_rejected(self) -> None:
        sim, _pool = make_inline_sim()

        def local_payload() -> float:
            return 1.0

        with pytest.raises(FactoryValidationError, match="local function"):
            sim.offload(local_payload, delay=1.0)

    def test_offload_without_pool_raises(self) -> None:
        sim = Sim()
        with pytest.raises(SimulationError, match="OffloadPool"):
            sim.offload(offload_square, 2.0, delay=1.0)

    def test_second_pool_on_same_sim_rejected(self) -> None:
        sim, _pool = make_inline_sim()
        with pytest.raises(RuntimeError, match="already has an offload pool"):
            OffloadPool(sim, backend="inline")

    def test_submit_after_close_rejected(self) -> None:
        sim, pool = make_inline_sim()
        pool.close()
        with pytest.raises(RuntimeError, match="closed"):
            sim.offload(offload_square, 2.0, delay=1.0)


class TestFailureDelivery:
    """Payload exceptions are captured and re-raised at the completion slot."""

    def test_exception_reraised_in_waiter_at_slot(self) -> None:
        sim, _pool = make_inline_sim()
        seen: list[tuple[float, str]] = []

        def waiter(sim: Sim) -> Gen:
            try:
                yield sim.offload(offload_fail, "boom", delay=4.0)
            except ValueError as error:
                seen.append((sim.now, str(error)))

        sim.spawn(waiter)
        sim.run()
        assert seen == [(4.0, "boom")]

    def test_nothing_raises_at_submission(self) -> None:
        """Inline runs the payload eagerly but defers the failure to the slot."""
        sim, _pool = make_inline_sim()
        raised: list[bool] = []

        def waiter(sim: Sim) -> Gen:
            event = sim.offload(offload_fail, "boom", delay=4.0)
            raised.append(True)  # reaching here proves submission didn't raise
            try:
                yield event
            except ValueError:
                pass

        sim.spawn(waiter)
        sim.run()
        assert raised == [True]

    def test_unwaited_failure_crashes_the_run_at_the_slot(self) -> None:
        """A failed offload nobody waits on crashes the Sim (never lost)."""
        sim, _pool = make_inline_sim()
        sim.offload(offload_fail, "boom", delay=4.0)
        with pytest.raises(ValueError, match="boom"):
            sim.run()
        assert sim.now == 4.0


class TestNonStrict:
    """``strict=False``: as-available delivery with an optional lower bound."""

    def test_inline_non_strict_delivers_at_current_time(self) -> None:
        sim, _pool = make_inline_sim()
        seen: list[tuple[float, float]] = []

        def waiter(sim: Sim) -> Gen:
            yield sim.delay(3.0)
            value = yield sim.offload(offload_square, 3.0, strict=False)
            seen.append((sim.now, value))

        sim.spawn(waiter)
        sim.run()
        assert seen == [(3.0, 9.0)]

    def test_delay_is_an_earliest_delivery_lower_bound(self) -> None:
        sim, _pool = make_inline_sim()
        seen: list[tuple[float, float]] = []

        def waiter(sim: Sim) -> Gen:
            value = yield sim.offload(offload_square, 3.0, delay=2.0, strict=False)
            seen.append((sim.now, value))

        sim.spawn(waiter)
        sim.run()
        assert seen == [(2.0, 9.0)]

    def test_debug_mode_flags_non_strict_offloads(self) -> None:
        sim = Sim(debug=True)
        OffloadPool(sim, backend="inline")
        with pytest.warns(NonStrictOffloadWarning, match="offload_square"):
            sim.offload(offload_square, 2.0, strict=False)

    def test_debug_env_var_flags_non_strict_offloads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLMSIM_DEBUG", "1")
        sim = Sim()
        OffloadPool(sim, backend="inline")
        with pytest.warns(NonStrictOffloadWarning):
            sim.offload(offload_square, 2.0, strict=False)

    def test_strict_offloads_never_warn(self) -> None:
        import warnings

        sim = Sim(debug=True)
        OffloadPool(sim, backend="inline")
        with warnings.catch_warnings():
            warnings.simplefilter("error", NonStrictOffloadWarning)
            sim.offload(offload_square, 2.0, delay=1.0)


class TestCancellation:
    """Interrupting the waiter abandons the offload; results never delivered."""

    def test_interrupt_while_waiting_abandons_the_offload(self) -> None:
        sim, _pool = make_inline_sim()
        tracer = trace(sim)
        seen: list[str] = []

        def waiter(sim: Sim) -> Gen:
            try:
                yield sim.offload(offload_square, 3.0, delay=10.0)
            except Interrupt:
                seen.append("interrupted")

        def interruptor(sim: Sim, target: Process[Any]) -> Gen:
            yield sim.delay(1.0)
            target.interrupt()

        target = sim.spawn(waiter)
        sim.spawn(interruptor, target)
        sim.run()
        assert seen == ["interrupted"]
        # The abandoned offload's result is discarded: its record carries no
        # payload value at the slot.
        abandoned = [r for r in tracer.records if r.kind == "OffloadEvent"]
        assert [(r.time, r.payload) for r in abandoned] == [(10.0, None)]

    def test_abandoned_failure_never_crashes_the_run(self) -> None:
        sim, _pool = make_inline_sim()

        def waiter(sim: Sim) -> Gen:
            try:
                yield sim.offload(offload_fail, "boom", delay=10.0)
            except Interrupt:
                pass

        def interruptor(sim: Sim, target: Process[Any]) -> Gen:
            yield sim.delay(1.0)
            target.interrupt()

        target = sim.spawn(waiter)
        sim.spawn(interruptor, target)
        sim.run()  # must not raise ValueError("boom")
        assert sim.now == 10.0

    def test_explicit_cancel_discards_the_result(self) -> None:
        sim, _pool = make_inline_sim()
        seen: list[float] = []

        def model(sim: Sim) -> Gen:
            event = sim.offload(offload_square, 3.0, delay=10.0)
            assert isinstance(event, OffloadEvent)
            event.cancel()
            yield sim.delay(1.0)
            seen.append(sim.now)

        sim.spawn(model)
        sim.run()
        assert seen == [1.0]

    def test_pool_close_is_idempotent(self) -> None:
        sim, pool = make_inline_sim()
        pool.close()
        pool.close()

    def test_pool_context_manager_closes(self) -> None:
        sim = Sim()
        with OffloadPool(sim, backend="inline"):
            pass
        with pytest.raises(RuntimeError, match="closed"):
            sim.offload(offload_square, 2.0, delay=1.0)


class TestRunUntil:
    """Offload events compose with ``run(until=...)`` like any event."""

    def test_run_until_offload_event_returns_its_value(self) -> None:
        sim, _pool = make_inline_sim()
        event = sim.offload(offload_square, 5.0, delay=2.0)
        assert sim.run(until=event) == 25.0
        assert sim.now == 2.0

    def test_offload_event_is_a_timeout_free_event(self) -> None:
        sim, _pool = make_inline_sim()
        event = sim.offload(offload_square, 5.0, delay=2.0)
        assert not isinstance(event, Timeout)
