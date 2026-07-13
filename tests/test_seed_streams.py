"""Seed tree: known-answer, no-collision, stability, and smoke tests (Phase 2.1)."""

import pickle
import random

import pytest

from llmsim.rand.streams import SeedTree, canonical_seed_path, child_seed

#: The reference master seed used across this module's known-answer pins.
_MASTER = 20260712


# --- Known-answer tests: pin the canonical path serialization and the -------
# --- derived child seeds for fixed triples. These literals are the wire ------
# --- format contract; changing them breaks every stored study. ---------------


def test_canonical_path_known_answers() -> None:
    assert canonical_seed_path(_MASTER, 0, 0) == b"llmsim.seed.v1:20260712:0:0"
    assert canonical_seed_path(_MASTER, 3, 7) == b"llmsim.seed.v1:20260712:3:7"
    assert canonical_seed_path(0, 0, 0) == b"llmsim.seed.v1:0:0:0"


def test_child_seed_known_answers() -> None:
    assert child_seed(_MASTER, 0, 0) == 23161004973121179873853684372013997265
    assert child_seed(_MASTER, 0, 1) == 101730132812640050641880596922128815967
    assert child_seed(_MASTER, 3, 7) == 127076731496689178138678904915868040038
    assert child_seed(0, 0, 0) == 212767327859537117638819838327818739025


def test_child_seed_fits_128_bits() -> None:
    for config_index in range(4):
        for replication_index in range(4):
            seed = child_seed(_MASTER, config_index, replication_index)
            assert 0 <= seed < 2**128


# --- Stability: same triple -> same pinned first-N draws, across runs, ------
# --- platforms, and builds (Mersenne Twister seeding is platform-stable). ----


def test_pinned_first_draws() -> None:
    draws = SeedTree(_MASTER).stream(0, 0).rng()
    assert [draws.random() for _ in range(5)] == [
        0.17424072881661623,
        0.7359163103192431,
        0.1639383411876092,
        0.34416615594436273,
        0.7414790905772227,
    ]

    other = SeedTree(0).stream(0, 0).rng()
    assert [other.random() for _ in range(5)] == [
        0.9769606965226724,
        0.41784700783496875,
        0.4891832746255995,
        0.1171928749610679,
        0.8445073156257471,
    ]


def test_same_seed_same_result_stream_level() -> None:
    first = SeedTree(_MASTER).rng(2, 5)
    second = SeedTree(_MASTER).rng(2, 5)
    assert [first.random() for _ in range(100)] == [second.random() for _ in range(100)]


# --- No collisions over a specified sample of (config, replication) triples. -


def test_no_child_seed_collisions_over_sample() -> None:
    tree = SeedTree(_MASTER)
    seeds = {
        tree.child_seed(config_index, replication_index)
        for config_index in range(100)
        for replication_index in range(100)
    }
    assert len(seeds) == 100 * 100


def test_distinct_across_master_seeds() -> None:
    seeds = {child_seed(master, 0, 0) for master in range(1000)}
    assert len(seeds) == 1000


# --- Bounded statistical smoke test: generous thresholds that only catch a --
# --- grossly biased derivation, not a rigorous independence proof. -----------


def test_sibling_streams_statistical_smoke() -> None:
    tree = SeedTree(_MASTER)
    sample_size = 10_000
    for replication_index in range(5):
        rng = tree.rng(0, replication_index)
        draws = [rng.random() for _ in range(sample_size)]
        mean = sum(draws) / sample_size
        # Uniform(0, 1) mean is 0.5 with sd ~0.0029 at n=10_000; +/-0.02 is
        # ~7 sigma -- generous enough to never flake, tight enough to catch a
        # grossly biased child-seed derivation.
        assert abs(mean - 0.5) < 0.02

    # Sibling streams must not be shifted copies of one another.
    a = tree.rng(0, 0)
    b = tree.rng(0, 1)
    first_a = [a.random() for _ in range(100)]
    first_b = [b.random() for _ in range(100)]
    assert first_a != first_b
    matches = sum(1 for x, y in zip(first_a, first_b) if x == y)
    assert matches == 0


# --- SeedStream is the picklable per-replication spec backends transport. ----
# (Pickle here round-trips our own in-process object, mirroring what
# ProcessPoolExecutor does internally -- no untrusted data is ever loaded.)


def test_seed_stream_carries_identity_and_seed() -> None:
    stream = SeedTree(_MASTER).stream(3, 7)
    assert stream.config_index == 3
    assert stream.replication_index == 7
    assert stream.seed == child_seed(_MASTER, 3, 7)


def test_seed_stream_pickles_round_trip() -> None:
    stream = SeedTree(_MASTER).stream(1, 2)
    clone = pickle.loads(pickle.dumps(stream))
    assert clone == stream
    assert clone.rng().random() == stream.rng().random()


def test_seed_stream_equality_and_repr() -> None:
    tree = SeedTree(_MASTER)
    assert tree.stream(1, 2) == tree.stream(1, 2)
    assert tree.stream(1, 2) != tree.stream(2, 1)
    assert "config_index=1" in repr(tree.stream(1, 2))


# --- The seam the Phase 1 Sim(rng=...) constructor consumes. -----------------


def test_tree_rng_is_adoptable_by_sim() -> None:
    from llmsim.core.sim import Sim

    rng = SeedTree(_MASTER).rng(0, 0)
    sim = Sim(rng=rng)
    assert sim.rng is rng
    assert sim.rng.random() == 0.17424072881661623


def test_rng_returns_fresh_stream_each_call() -> None:
    tree = SeedTree(_MASTER)
    first = tree.rng(0, 0)
    second = tree.rng(0, 0)
    assert first is not second
    assert isinstance(first, random.Random)


# --- Input validation. --------------------------------------------------------


def test_master_seed_must_be_int() -> None:
    with pytest.raises(TypeError, match="master_seed"):
        SeedTree("42")  # type: ignore[arg-type]


def test_indices_must_be_non_negative() -> None:
    tree = SeedTree(_MASTER)
    with pytest.raises(ValueError, match="config_index"):
        tree.child_seed(-1, 0)
    with pytest.raises(ValueError, match="replication_index"):
        tree.child_seed(0, -1)


def test_negative_master_seed_is_allowed_and_stable() -> None:
    assert child_seed(-1, 0, 0) == child_seed(-1, 0, 0)
    assert child_seed(-1, 0, 0) != child_seed(1, 0, 0)
