"""Per-Sim RNG determinism (G5) and thread-ownership debug mode (G6)."""

import threading
from collections.abc import Generator
from typing import Any

import pytest

from llmsim.core.events import Event
from llmsim.core.sim import Sim


def test_same_seed_gives_identical_draw_sequence() -> None:
    first = [Sim(seed=12345).rng.random() for _ in range(100)]
    second = [Sim(seed=12345).rng.random() for _ in range(100)]
    assert first == second


def test_different_seeds_diverge() -> None:
    a = [Sim(seed=1).rng.random() for _ in range(20)]
    b = [Sim(seed=2).rng.random() for _ in range(20)]
    assert a != b


def test_same_seed_same_result_baseline() -> None:
    """The sequential same-seed-same-result guarantee for a whole run."""

    def model(sim: Sim, draws: list[float]) -> Generator[Event[Any], Any, None]:
        for _ in range(50):
            wait = sim.rng.expovariate(1.0)
            draws.append(wait)
            yield sim.delay(wait)

    run_one: list[float] = []
    sim_one = Sim(seed=777)
    sim_one.spawn(model, run_one)
    sim_one.run()

    run_two: list[float] = []
    sim_two = Sim(seed=777)
    sim_two.spawn(model, run_two)
    sim_two.run()

    assert run_one == run_two
    assert sim_one.now == sim_two.now


def test_explicit_rng_is_adopted() -> None:
    import random

    stream = random.Random(42)
    sim = Sim(rng=stream)
    assert sim.rng is stream


def test_debug_mode_allows_same_thread_scheduling() -> None:
    sim = Sim(debug=True)
    sim.delay(1.0)  # constructed and scheduled on the owning thread
    sim.run()
    assert sim.now == 1.0


def test_debug_mode_rejects_cross_thread_scheduling() -> None:
    sim = Sim(debug=True)
    error: list[BaseException] = []

    def offend() -> None:
        try:
            event: Event[None] = Event(sim)
            sim.schedule(event)
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=offend)
    thread.start()
    thread.join()

    assert len(error) == 1
    assert isinstance(error[0], RuntimeError)
    assert "one thread" in str(error[0])


def test_env_var_enables_debug_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLMSIM_DEBUG", "1")
    sim = Sim()
    error: list[BaseException] = []

    def offend() -> None:
        try:
            sim.schedule(Event(sim))
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = threading.Thread(target=offend)
    thread.start()
    thread.join()
    assert len(error) == 1
    assert isinstance(error[0], RuntimeError)


def test_debug_disabled_by_default_has_no_owner_thread() -> None:
    sim = Sim()
    assert sim._owner_thread is None
