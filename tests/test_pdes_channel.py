"""Channels, mailboxes, and delivery events: ordering + enforcement (3.1)."""

import random

import pytest

from llmsim.core.sim import Sim
from llmsim.parallel.pdes.channel import (
    Channel,
    Inbox,
    LookaheadError,
    Mailbox,
    Message,
)


def _channel(sim: Sim, mailbox: Mailbox, channel_id: int = 0) -> Channel:
    channel = Channel(name="a_to_b", lookahead=1.0, sim=sim)
    channel.bind(channel_id=channel_id, mailbox=mailbox)
    return channel


# --- Lookahead and send-delay enforcement. ------------------------------------


def test_non_positive_lookahead_rejected() -> None:
    sim = Sim()
    with pytest.raises(LookaheadError, match="lookahead"):
        Channel(name="bad", lookahead=0.0, sim=sim)
    with pytest.raises(LookaheadError, match="lookahead"):
        Channel(name="bad", lookahead=-1.0, sim=sim)


def test_send_delay_below_lookahead_rejected_with_actionable_error() -> None:
    sim = Sim()
    channel = _channel(sim, Mailbox())
    with pytest.raises(LookaheadError) as excinfo:
        channel.send("part", delay=0.5)
    message = str(excinfo.value)
    assert "a_to_b" in message and "0.5" in message and "1.0" in message


def test_send_at_exactly_lookahead_is_allowed() -> None:
    sim = Sim()
    mailbox = Mailbox()
    _channel(sim, mailbox).send("part", delay=1.0)
    assert len(mailbox.drain()) == 1


# --- Message stamping: timestamp, channel id, per-channel sequence. ------------


def test_messages_stamped_with_send_time_plus_delay() -> None:
    sim = Sim(initial_time=10.0)
    mailbox = Mailbox()
    channel = _channel(sim, mailbox)
    channel.send("x", delay=2.5)
    (message,) = mailbox.drain()
    assert message.timestamp == 12.5
    assert message.channel_id == 0
    assert message.payload == "x"


def test_sequence_is_monotonic_per_channel() -> None:
    sim = Sim()
    mailbox = Mailbox()
    channel = _channel(sim, mailbox)
    for _ in range(5):
        channel.send("x", delay=1.0)
    sequences = [message.sequence for message in mailbox.drain()]
    assert sequences == [0, 1, 2, 3, 4]


# --- Mailbox drain: everything out, deterministic order after sorting. ---------


def test_drain_empties_the_mailbox() -> None:
    sim = Sim()
    mailbox = Mailbox()
    _channel(sim, mailbox).send("x", delay=1.0)
    assert len(mailbox.drain()) == 1
    assert mailbox.drain() == []


def test_unbound_channel_send_rejected() -> None:
    sim = Sim()
    unbound = Channel(name="floating", lookahead=1.0, sim=sim)
    with pytest.raises(RuntimeError, match="not wired"):
        unbound.send("x", delay=1.0)


def test_sorted_messages_are_deterministic_under_shuffled_arrival() -> None:
    """Messages from many channels sort identically however sends interleave.

    Each channel sends its own fixed delay sequence; only the interleaving
    *between* channels is shuffled (matching real windows, where each sender
    shard's own send order is deterministic).
    """
    delays = [1.0, 1.0, 2.0]
    expected = sorted(
        (delay, channel_index, sequence)
        for channel_index in range(3)
        for sequence, delay in enumerate(delays)
    )
    rng = random.Random(7)
    for _ in range(3):
        sim = Sim()
        mailboxes = [Mailbox() for _ in range(3)]
        channels = [_channel(sim, mailboxes[i], channel_id=i) for i in range(3)]
        interleaving = [channel_index for channel_index in range(3) for _ in delays]
        rng.shuffle(interleaving)
        cursors = [0, 0, 0]
        for channel_index in interleaving:
            channels[channel_index].send("x", delay=delays[cursors[channel_index]])
            cursors[channel_index] += 1
        drained = [message for mailbox in mailboxes for message in mailbox.drain()]
        ordered = sorted(drained, key=Message.sort_key)
        assert [
            (message.timestamp, message.channel_id, message.sequence)
            for message in ordered
        ] == expected


# --- Inbox delivery: payloads land at message timestamps, causally. ------------


def test_inbox_delivers_payload_at_message_timestamp() -> None:
    sim = Sim()
    inbox = Inbox(sim=sim, name="a_to_b")
    received: list[tuple[float, str]] = []

    def consumer(sim: Sim):  # type: ignore[no-untyped-def]
        part = yield inbox.get()
        received.append((sim.now, part))

    sim.spawn(consumer)
    inbox.deliver(Message(timestamp=4.0, channel_id=0, sequence=0, payload="part"))
    sim.run()
    assert received == [(4.0, "part")]


def test_inbox_rejects_delivery_in_the_past() -> None:
    sim = Sim(initial_time=5.0)
    inbox = Inbox(sim=sim, name="a_to_b")
    with pytest.raises(RuntimeError, match="causality"):
        inbox.deliver(Message(timestamp=4.0, channel_id=0, sequence=0, payload="x"))


def test_inbox_preserves_delivery_order_for_same_timestamp() -> None:
    sim = Sim()
    inbox = Inbox(sim=sim, name="a_to_b")
    received: list[str] = []

    def consumer(sim: Sim):  # type: ignore[no-untyped-def]
        for _ in range(3):
            part = yield inbox.get()
            received.append(part)

    sim.spawn(consumer)
    for sequence, payload in enumerate(["first", "second", "third"]):
        inbox.deliver(
            Message(timestamp=2.0, channel_id=0, sequence=sequence, payload=payload)
        )
    sim.run()
    assert received == ["first", "second", "third"]
