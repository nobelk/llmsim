"""The seed tree and per-replication RNG streams.

Derives child seeds from the master seed via a hash-based tree (SHA-256 ->
128-bit child seeds) so each ``(config, replication)`` gets a statistically
independent ``random.Random`` stream that is stable across runs, platforms,
backends, worker counts, and GIL/free-threaded builds.

The derivation is normative (Phase 2 requirements): a child seed is the first
128 bits (big-endian) of ``SHA-256(canonical_seed_path(master_seed,
config_index, replication_index))``, where the canonical path is the ASCII
string ``"llmsim.seed.v1:<master_seed>:<config_index>:<replication_index>"``
with each integer in decimal. These literals are a wire-format contract --
changing them changes every derived stream, so they are pinned by
known-answer tests and must never drift.

The 128-bit child seed is also the documented seam for a future
``llmsim[numpy]`` adapter: it is directly usable as a Philox/PCG64 key, so a
vectorized-draw stream can be derived from the same tree without changing the
derivation.
"""

import hashlib
import random
from dataclasses import dataclass

#: Version tag baked into every canonical seed path. Bump only with a new,
#: co-existing derivation -- never mutate v1 in place.
_PATH_VERSION = "llmsim.seed.v1"

#: Number of bytes of the SHA-256 digest kept for the child seed (128 bits).
_SEED_BYTES = 16


def _require_int_master_seed(master_seed: object) -> None:
    """Reject non-``int`` master seeds with the one canonical message."""
    if not isinstance(master_seed, int):
        raise TypeError(
            f"master_seed must be an int, got {type(master_seed).__name__!r}; "
            f"the reproducibility guarantee is defined only for an explicit "
            f"integer master seed"
        )


def canonical_seed_path(
    master_seed: int, config_index: int, replication_index: int
) -> bytes:
    """Return the fixed, documented serialization of a seed-tree path.

    The format is ``b"llmsim.seed.v1:<master_seed>:<config_index>:
    <replication_index>"`` with each integer rendered in decimal. It is pinned
    by known-answer tests; the same triple yields the same bytes on every
    platform and build.

    Raises:
        TypeError: if *master_seed* is not an ``int``.
        ValueError: if either index is negative.
    """
    _require_int_master_seed(master_seed)
    if config_index < 0:
        raise ValueError(f"config_index must be >= 0, got {config_index}")
    if replication_index < 0:
        raise ValueError(f"replication_index must be >= 0, got {replication_index}")
    return f"{_PATH_VERSION}:{master_seed}:{config_index}:{replication_index}".encode(
        "ascii"
    )


def child_seed(master_seed: int, config_index: int, replication_index: int) -> int:
    """Derive the 128-bit child seed for one ``(config, replication)`` triple.

    ``SHA-256`` of the canonical path, truncated to its first 16 bytes and
    read big-endian. Deterministic and platform-independent by construction.
    """
    digest = hashlib.sha256(
        canonical_seed_path(master_seed, config_index, replication_index)
    ).digest()
    return int.from_bytes(digest[:_SEED_BYTES], "big")


@dataclass(frozen=True, slots=True)
class SeedStream:
    """A picklable spec for one derived stream.

    Carries the ``(config_index, replication_index)`` identity plus the
    derived child seed -- exactly what an execution backend transports to a
    worker (a seed spec, never a live ``random.Random``). Call :meth:`rng`
    worker-side to construct the actual stream. A frozen dataclass, so
    transported clones compare equal and hash consistently.
    """

    #: The 128-bit child seed derived by :func:`child_seed`.
    seed: int
    #: Position of this stream's config in the experiment's config list.
    config_index: int
    #: Zero-based replication number within the config.
    replication_index: int

    def rng(self) -> random.Random:
        """Return a fresh ``random.Random`` seeded with this child seed."""
        return random.Random(self.seed)


class SeedTree:
    """Mints independent, reproducible streams from one master seed.

    The entry point of the Phase 2 randomness design: construct one tree from
    the study's explicit ``master_seed``, then draw one stream per
    ``(config_index, replication_index)``. :meth:`rng` is the exact seam the
    Phase 1 ``Sim(rng=...)`` constructor consumes::

        tree = SeedTree(master_seed=20260712)
        sim = Sim(rng=tree.rng(config_index=0, replication_index=3))
    """

    __slots__ = ("master_seed",)

    def __init__(self, master_seed: int) -> None:
        """Root the tree at *master_seed* (validated to be an ``int``)."""
        _require_int_master_seed(master_seed)
        #: The explicit study-level seed every child derives from.
        self.master_seed = master_seed

    def child_seed(self, config_index: int, replication_index: int) -> int:
        """Derive the 128-bit child seed for one triple under this master."""
        return child_seed(self.master_seed, config_index, replication_index)

    def stream(self, config_index: int, replication_index: int) -> SeedStream:
        """Return the picklable :class:`SeedStream` spec for one triple."""
        return SeedStream(
            self.child_seed(config_index, replication_index),
            config_index,
            replication_index,
        )

    def rng(self, config_index: int, replication_index: int) -> random.Random:
        """Return a fresh ``random.Random`` for one triple (the Sim seam)."""
        return random.Random(self.child_seed(config_index, replication_index))

    def __repr__(self) -> str:
        """Show the master seed for debugging."""
        return f"SeedTree(master_seed={self.master_seed})"
