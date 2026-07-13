"""Timestamped inter-shard channels.

The only locked structures in the parallel layer: ordered, delayed message
queues carrying events between shards, with the link lookahead that bounds how
far apart shard clocks may drift.

A :class:`Channel` is the sender-side endpoint owned by one shard; its
:class:`Mailbox` is the receiver-side buffer drained by the synchronizer at
window edges; an :class:`Inbox` is the receiving shard's Store-like endpoint
that turns delivered messages into local events. Every message is stamped
``(timestamp, channel id, per-channel sequence)`` — the normative composite
key that makes delivery order globally deterministic regardless of how sender
threads interleave (tech-stack constraint 7).
"""

import threading
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llmsim.core.events import Event, Timeout
from llmsim.resources.store import Store, StoreGet

if TYPE_CHECKING:
    from llmsim.core.sim import Sim


class LookaheadError(ValueError):
    """A channel's lookahead contract was violated.

    Raised when a channel is declared with a non-positive lookahead (the
    safe-window algorithm cannot make progress without positive lookahead on
    every channel) or when ``send()`` is called with ``delay < lookahead``
    (the lookahead is a promise to the synchronizer; breaking it would let a
    message land inside an already-executed window).
    """


@dataclass(frozen=True, slots=True)
class Message:
    """One cross-shard message with its deterministic ordering stamp."""

    #: Simulation time the payload becomes visible at the destination.
    timestamp: float
    #: The sending channel's topology-assigned id (ordering tie-break #1).
    channel_id: int
    #: Per-channel monotonic send counter (ordering tie-break #2).
    sequence: int
    #: The user payload; should be plain data, never a ``Sim``-owned object.
    payload: Any

    @staticmethod
    def sort_key(message: "Message") -> tuple[float, int, int]:
        """Return the normative delivery order key: (timestamp, channel, seq)."""
        return (message.timestamp, message.channel_id, message.sequence)


class Mailbox:
    """A receiver-side message buffer — one of the library's only locks.

    Sender shards append concurrently during a window; the owning shard
    drains at window edges while every sender is quiescent at the barrier.
    All mutation happens under the one lock (tech-stack constraint 2: locked
    structures live only here, touched at safe-window edges).
    """

    __slots__ = ("_lock", "_messages")

    def __init__(self) -> None:
        """Create an empty, lock-guarded buffer."""
        self._lock = threading.Lock()
        self._messages: deque[Message] = deque()

    def append(self, message: Message) -> None:
        """Buffer *message* (called by the sending shard's thread)."""
        with self._lock:
            self._messages.append(message)

    def drain(self) -> list[Message]:
        """Remove and return everything buffered (called by the owner)."""
        with self._lock:
            messages = list(self._messages)
            self._messages.clear()
        return messages


class Channel:
    """The sender-side endpoint of one directed inter-shard link.

    Owned by exactly one shard; ``send()`` may only be called from that
    shard's processes while it executes a window. The *lookahead* is the
    channel's normative promise: every message carries
    ``timestamp >= sender_now + lookahead``.
    """

    __slots__ = ("name", "channel_id", "lookahead", "_sim", "_mailbox", "_sequence")

    def __init__(self, *, name: str, lookahead: float, sim: "Sim") -> None:
        """Create the endpoint; the topology wires it via :meth:`bind`.

        A ``ShardedSim`` assigns channel ids in sorted-name order after every
        builder has declared its endpoints, so ids are deterministic
        regardless of build interleaving.
        """
        if lookahead <= 0:
            raise LookaheadError(
                f"channel {name!r}: lookahead must be > 0, got {lookahead}; "
                f"the safe-window horizon cannot advance past a zero-lookahead "
                f"link (see the progress property in the Phase 3 requirements)"
            )
        #: The topology-level channel name (diagnostics and wiring).
        self.name = name
        #: Deterministic id assigned by the topology (sorted-name order).
        self.channel_id = -1
        #: Minimum send delay; the synchronizer's per-link drift bound.
        self.lookahead = lookahead
        self._sim = sim
        self._mailbox: Mailbox | None = None
        self._sequence = 0

    def bind(self, *, channel_id: int, mailbox: Mailbox) -> None:
        """Wire the endpoint to its id and destination (topology-internal)."""
        self.channel_id = channel_id
        self._mailbox = mailbox

    def send(self, payload: Any, *, delay: float) -> None:
        """Send *payload* to arrive ``delay`` after the sender's current time.

        Raises:
            LookaheadError: if ``delay < lookahead`` — the channel's promise
                to the synchronizer would be broken.
        """
        if delay < self.lookahead:
            raise LookaheadError(
                f"channel {self.name!r}: send delay {delay} is below the "
                f"declared lookahead {self.lookahead}; either send with "
                f"delay >= lookahead or declare a smaller lookahead on "
                f"ports.out(...)"
            )
        if self._mailbox is None:
            raise RuntimeError(
                f"channel {self.name!r} is not wired to a destination yet; "
                f"sends are only possible once the topology has validated"
            )
        sequence = self._sequence
        self._sequence = sequence + 1
        self._mailbox.append(
            Message(
                timestamp=self._sim.now + delay,
                channel_id=self.channel_id,
                sequence=sequence,
                payload=payload,
            )
        )

    def __repr__(self) -> str:
        """Show the wiring identity for debugging."""
        return (
            f"Channel(name={self.name!r}, channel_id={self.channel_id}, "
            f"lookahead={self.lookahead})"
        )


class Inbox:
    """The receiving shard's Store-like endpoint for one channel.

    ``yield inbox.get()`` in a shard process resolves to the next delivered
    payload, in the globally deterministic delivery order. Deliveries are
    performed by the synchronizer at window edges via :meth:`deliver`: each
    message becomes a ``Timeout`` at its stamped time (an already-successful
    event carrying the payload) whose processing deposits the payload into
    this inbox's store, waking any waiting ``get()``.
    """

    __slots__ = ("name", "_sim", "_store", "_deposit_callback")

    def __init__(self, *, sim: "Sim", name: str) -> None:
        """Create the endpoint local to the receiving shard's *sim*."""
        #: The topology-level channel name this inbox receives from.
        self.name = name
        self._sim = sim
        self._store: Store[Any] = Store(sim)
        # One bound method reused by every delivery (per-message path).
        self._deposit_callback = self._deposit

    def get(self) -> StoreGet[Any]:
        """Return an event resolving to the next delivered payload."""
        return self._store.get()

    def deliver(self, message: Message) -> None:
        """Schedule *message*'s payload to land at its timestamp.

        Called by the synchronizer while the shard is quiescent, in the
        normative sorted order — the resulting event-id assignment makes
        same-timestamp delivery ordering deterministic.

        Raises:
            RuntimeError: if the message's timestamp is in the shard's past —
                a causality violation that the safe-window algorithm can
                never legitimately produce.
        """
        delay = message.timestamp - self._sim.now
        if delay < 0:
            raise RuntimeError(
                f"causality violation: inbox {self.name!r} received a message "
                f"stamped {message.timestamp} but the shard clock is already "
                f"at {self._sim.now}; the safe-window horizon must prevent "
                f"this"
            )
        event: Timeout[Any] = Timeout(self._sim, delay, message.payload)
        event.callbacks.append(self._deposit_callback)  # type: ignore[union-attr]

    def _deposit(self, event: Event[Any]) -> None:
        """Move a processed delivery's payload into the store (at its time)."""
        self._store.put(event._value)

    def __repr__(self) -> str:
        """Show the wiring identity for debugging."""
        return f"Inbox(name={self.name!r})"
