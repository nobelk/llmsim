"""Real-time mode: pacing, drift, until parity, offload synergy (4.2)."""

import re
from typing import Any

import pytest
from benchmarks import skip_if_shared_macos_ci

from llmsim import OffloadPool, RealtimeDriftError, Resource, Sim, rt
from llmsim.trace import trace
from tests.parallel_support import (
    Gen,
    offload_slow_square,
    offload_square,
)


class FakeClock:
    """A deterministic monotonic/sleep pair for pacing tests.

    ``sleep`` advances the fake wall clock exactly; tests advance it
    directly (``clock.now_wall += ...``) to simulate slow event processing.
    """

    def __init__(self) -> None:
        self.now_wall = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now_wall

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0, f"negative sleep {seconds}"
        self.sleeps.append(seconds)
        self.now_wall += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(rt, "_monotonic", fake.monotonic)
    monkeypatch.setattr(rt, "_sleep", fake.sleep)
    return fake


class TestPacing:
    """Events process at ``start + (T - t0) * factor`` wall offsets."""

    def test_events_process_at_their_wall_offsets(self, clock: FakeClock) -> None:
        sim = Sim()
        seen: list[tuple[float, float]] = []

        def ticker(sim: Sim) -> Gen:
            for _ in range(3):
                yield sim.delay(1.0)
                seen.append((sim.now, clock.now_wall))

        sim.spawn(ticker)
        rt.run(sim, factor=0.5)
        assert seen == [(1.0, 0.5), (2.0, 1.0), (3.0, 1.5)]

    def test_factor_scales_wall_time(self, clock: FakeClock) -> None:
        sim = Sim()
        sim.delay(4.0)
        rt.run(sim, factor=2.0)
        assert clock.now_wall == 8.0

    def test_nonzero_initial_time_is_the_pacing_origin(self, clock: FakeClock) -> None:
        sim = Sim(initial_time=10.0)
        sim.delay(1.0)
        rt.run(sim, factor=1.0)
        assert clock.now_wall == 1.0  # paced from t0=10, not from t=0

    def test_zero_delay_bursts_need_no_sleep(self, clock: FakeClock) -> None:
        sim = Sim()
        for _ in range(5):
            sim.delay(1.0)  # five events at the same simulated time
        rt.run(sim, factor=1.0)
        assert clock.now_wall == 1.0  # FakeClock.sleep rejects negatives

    def test_factor_must_be_positive(self, clock: FakeClock) -> None:
        sim = Sim()
        with pytest.raises(ValueError, match="factor"):
            rt.run(sim, factor=0.0)
        with pytest.raises(ValueError, match="factor"):
            rt.run(sim, factor=-1.0)

    def test_empty_schedule_returns_immediately(self, clock: FakeClock) -> None:
        sim = Sim()
        assert rt.run(sim) is None
        assert clock.now_wall == 0.0


class TestDriftPolicy:
    """Behind-schedule behavior: strict raises, non-strict hurries."""

    def test_strict_raises_when_processing_overruns(self, clock: FakeClock) -> None:
        sim = Sim()

        def slow_then_tick(sim: Sim) -> Gen:
            yield sim.delay(1.0)
            # Simulate event processing that takes 5 wall seconds -- far
            # beyond the one-factor slack -- before the next event at t=2.
            clock.now_wall += 5.0
            yield sim.delay(1.0)

        sim.spawn(slow_then_tick)
        with pytest.raises(RealtimeDriftError) as caught:
            rt.run(sim, factor=1.0)
        assert caught.value.simulated_time == 2.0
        assert caught.value.drift == pytest.approx(4.0)  # 5s late minus 1s budget

    def test_slack_of_one_factor_is_tolerated(self, clock: FakeClock) -> None:
        sim = Sim()

        def slightly_slow(sim: Sim) -> Gen:
            yield sim.delay(1.0)
            clock.now_wall += 1.5  # 0.5s late at t=2: within the 1-factor slack
            yield sim.delay(1.0)

        sim.spawn(slightly_slow)
        rt.run(sim, factor=1.0)  # must not raise

    def test_non_strict_hurries_then_resyncs(self, clock: FakeClock) -> None:
        sim = Sim()
        seen: list[tuple[float, float]] = []

        def slow_then_tick(sim: Sim) -> Gen:
            yield sim.delay(1.0)
            clock.now_wall += 5.0  # now at wall 6.0, sim time 1.0
            for _ in range(2):
                yield sim.delay(1.0)
                seen.append((sim.now, clock.now_wall))
            # By t=3 the schedule (wall 3.0) is far behind; no sleeping
            # happens until the wall deadline catches up again.
            yield sim.delay(10.0)  # t=13 -> wall deadline 13.0 > 6.0: resync
            seen.append((sim.now, clock.now_wall))

        sim.spawn(slow_then_tick)
        rt.run(sim, factor=1.0, strict=False)
        assert seen == [(2.0, 6.0), (3.0, 6.0), (13.0, 13.0)]


class TestUntilParity:
    """``until`` behaves exactly like ``Sim.run``'s."""

    def test_until_time_waits_the_full_wall_budget(self, clock: FakeClock) -> None:
        sim = Sim()
        sim.delay(1.0)
        assert rt.run(sim, until=5.0, factor=1.0) is None
        assert sim.now == 5.0
        assert clock.now_wall == 5.0

    def test_until_event_returns_its_value(self, clock: FakeClock) -> None:
        sim = Sim()
        event = sim.delay(2.0, "payload")
        assert rt.run(sim, until=event, factor=1.0) == "payload"
        assert clock.now_wall == 2.0

    def test_until_already_processed_returns_value(self, clock: FakeClock) -> None:
        sim = Sim()
        event = sim.delay(1.0, "done")
        sim.run()
        assert rt.run(sim, until=event) == "done"

    def test_until_at_or_before_now_rejected(self, clock: FakeClock) -> None:
        sim = Sim()
        sim.delay(1.0)
        sim.run()
        with pytest.raises(ValueError, match="must be greater"):
            rt.run(sim, until=1.0)

    def test_until_never_triggered_raises_like_sim_run(self, clock: FakeClock) -> None:
        sim = Sim()
        never = sim.event()
        sim.delay(1.0)
        with pytest.raises(RuntimeError, match="was not triggered"):
            rt.run(sim, until=never, factor=1.0)


class TestOffloadParity:
    """The Phase 4.1 seam behaves under rt.run exactly as under Sim.run."""

    def test_non_strict_delivery_between_paced_steps(self, clock: FakeClock) -> None:
        sim = Sim()
        seen: list[tuple[float, float]] = []

        def waiter(sim: Sim) -> Gen:
            yield sim.delay(1.0)
            value = yield sim.offload(offload_square, 3.0, strict=False)
            seen.append((sim.now, value))

        def ticker(sim: Sim) -> Gen:
            for _ in range(4):
                yield sim.delay(1.0)

        with OffloadPool(sim, backend="inline"):
            sim.spawn(waiter)
            sim.spawn(ticker)
            rt.run(sim, factor=1.0)
        assert seen == [(1.0, 9.0)]

    def test_run_end_drain_delivers_under_pacing(self, clock: FakeClock) -> None:
        sim = Sim()
        seen: list[tuple[float, float]] = []

        def waiter(sim: Sim) -> Gen:
            value = yield sim.offload(offload_square, 4.0, strict=False)
            seen.append((sim.now, value))

        with OffloadPool(sim, backend="inline"):
            sim.spawn(waiter)
            rt.run(sim, factor=1.0)
        assert seen == [(0.0, 16.0)]

    def test_strict_slot_blocking_counts_as_drift(self, clock: FakeClock) -> None:
        """A slot whose wall deadline slipped raises like any late event."""
        sim = Sim()

        def submitter(sim: Sim) -> Gen:
            event = sim.offload(offload_square, 3.0, delay=2.0)  # slot t=2
            yield sim.delay(1.0)
            clock.now_wall += 5.0  # processing overruns before the slot
            yield event

        with OffloadPool(sim, backend="inline"):
            sim.spawn(submitter)
            with pytest.raises(RealtimeDriftError) as caught:
                rt.run(sim, factor=1.0)
        assert caught.value.simulated_time == 2.0

    def test_until_with_outstanding_offloads_matches_sim_run(
        self, clock: FakeClock
    ) -> None:
        """The combined path: drain delivers, then the until outcome matches."""

        def build_and_run(paced: bool) -> tuple[list[tuple[float, float]], str]:
            sim = Sim()
            seen: list[tuple[float, float]] = []

            def waiter(sim: Sim) -> Gen:
                value = yield sim.offload(offload_square, 5.0, strict=False)
                seen.append((sim.now, value))

            with OffloadPool(sim, backend="inline"):
                never = sim.event()
                sim.spawn(waiter)
                try:
                    if paced:
                        rt.run(sim, until=never, factor=1.0)
                    else:
                        sim.run(until=never)
                except RuntimeError as error:
                    return seen, str(error)
            return seen, "no error"

        paced_seen, paced_error = build_and_run(paced=True)
        plain_seen, plain_error = build_and_run(paced=False)
        # The offload result was drained and delivered, never dropped, and
        # the until-never-triggered outcome is identical under both drivers
        # (up to the stop event's memory address in its repr).
        assert paced_seen == plain_seen == [(0.0, 25.0)]
        assert "was not triggered" in paced_error
        strip_address = re.compile(r"0x[0-9a-f]+")
        assert strip_address.sub("0x", paced_error) == strip_address.sub(
            "0x", plain_error
        )


def build_mixed_model(offload_backend: str) -> tuple[Sim, "OffloadPool"]:
    """A model mixing timeouts, processes, a resource, and strict offloads."""
    sim = Sim(seed=20260712)
    pool = OffloadPool(sim, backend=offload_backend, max_workers=2)  # type: ignore[arg-type]
    server = Resource(sim, capacity=1)

    def customer(sim: Sim, index: int) -> Gen:
        yield sim.delay(0.1 * index)
        with server.request() as slot:
            yield slot
            score = yield sim.offload(offload_square, float(index), delay=0.5)
            yield sim.delay(sim.rng.expovariate(1.0) + score * 0.01)

    for index in range(4):
        sim.spawn(customer, index)
    return sim, pool


class TestEquivalence:
    """Pacing never changes a deterministic model's trace."""

    @pytest.mark.parametrize("offload_backend", ["inline", "threads"])
    def test_paced_trace_equals_unpaced_trace(
        self, clock: FakeClock, offload_backend: str
    ) -> None:
        sim_plain, pool_plain = build_mixed_model(offload_backend)
        tracer_plain = trace(sim_plain)
        with pool_plain:
            sim_plain.run()

        sim_paced, pool_paced = build_mixed_model(offload_backend)
        tracer_paced = trace(sim_paced)
        with pool_paced:
            rt.run(sim_paced, factor=0.25)

        assert tracer_paced.records == tracer_plain.records

    def test_real_clock_paced_trace_equals_unpaced(self) -> None:
        """A tiny real factor: equivalence holds on the actual clock."""
        sim_plain, pool_plain = build_mixed_model("inline")
        tracer_plain = trace(sim_plain)
        with pool_plain:
            sim_plain.run()

        sim_paced, pool_paced = build_mixed_model("inline")
        tracer_paced = trace(sim_paced)
        with pool_paced:
            rt.run(sim_paced, factor=0.001, strict=False)

        assert tracer_paced.records == tracer_plain.records


class TestDrainDriftExemption:
    """Waiting for non-strict payloads at run end is never drift."""

    def test_run_end_drain_never_raises_drift(self) -> None:
        """The drain wait exceeds the slack by far; strict must not raise."""
        sim = Sim()
        seen: list[float] = []

        def waiter(sim: Sim) -> Gen:
            value = yield sim.offload(offload_slow_square, 3.0, 0.2, strict=False)
            seen.append(value)

        with OffloadPool(sim, backend="threads", max_workers=1):
            sim.spawn(waiter)
            rt.run(sim, factor=0.01)  # strict=True default
        assert seen == [9.0]

    def test_pacing_resynchronizes_after_drain(self, clock: FakeClock) -> None:
        """Events scheduled after a drained delivery pace from the resync."""
        sim = Sim()
        seen: list[tuple[float, float]] = []

        def waiter(sim: Sim) -> Gen:
            value = yield sim.offload(offload_square, 3.0, strict=False)
            yield sim.delay(2.0)
            seen.append((sim.now, value))

        with OffloadPool(sim, backend="inline"):
            sim.spawn(waiter)
            rt.run(sim, factor=1.0)
        # Delivery at t=0 after the drain; the follow-up delay paces two
        # wall seconds from the resynchronized origin.
        assert seen == [(2.0, 9.0)]


class TestOffloadSynergy:
    """HIL showcase: payloads compute inside their slot's real-time budget."""

    def test_payload_inside_budget_completes_without_drift(self) -> None:
        skip_if_shared_macos_ci()
        sim = Sim()
        seen: list[Any] = []

        def waiter(sim: Sim) -> Gen:
            # Slot t=1 gives a 0.2s wall budget; the payload takes ~0.05s,
            # which hides entirely inside the pacing sleep.
            value = yield sim.offload(offload_slow_square, 3.0, 0.05, delay=1.0)
            seen.append(value)

        with OffloadPool(sim, backend="threads", max_workers=1):
            sim.spawn(waiter)
            rt.run(sim, factor=0.2)  # strict: any drift would raise
        assert seen == [9.0]

    def test_payload_beyond_budget_raises_drift(self) -> None:
        sim = Sim()

        def waiter(sim: Sim) -> Gen:
            # Slot t=1 gives a 0.02s budget; the payload takes ~0.3s. The
            # resolver blocks at the slot, so the *next* event is late far
            # beyond the one-factor slack. Slow runners only get later.
            yield sim.offload(offload_slow_square, 3.0, 0.3, delay=1.0)
            yield sim.delay(1.0)

        with OffloadPool(sim, backend="threads", max_workers=1):
            sim.spawn(waiter)
            with pytest.raises(RealtimeDriftError):
                rt.run(sim, factor=0.02)
