"""Parallel discrete-event simulation of a single model.

Conservative (YAWNS-style) sharding: the model is partitioned into logical
processes that advance in lockstep within a computed safe window, exchanging
timestamped messages over channels. Optimistic/Time Warp is permanently
rejected because generator frames cannot be snapshotted.
"""

from llmsim.parallel.pdes.analyze import PdesAnalysis, analyze
from llmsim.parallel.pdes.channel import Channel, Inbox, LookaheadError, Message
from llmsim.parallel.pdes.shard import (
    RunMode,
    ShardedSim,
    ShardError,
    ShardPorts,
    TopologyError,
)

__all__ = [
    "ShardedSim",
    "ShardPorts",
    "RunMode",
    "Channel",
    "Inbox",
    "Message",
    "ShardError",
    "TopologyError",
    "LookaheadError",
    "analyze",
    "PdesAnalysis",
]
